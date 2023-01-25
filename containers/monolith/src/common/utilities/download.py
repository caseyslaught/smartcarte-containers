import os
from osgeo import gdal
from pystac import ItemCollection
from pystac_client import Client
import rasterio
import rasterio.merge
import requests
from shapely.geometry import box, shape, Point
import xml.etree.ElementTree as ET

from common.exceptions import EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException
from common.constants import NODATA_BYTE, NODATA_UINT16, S2_BANDS
from common.utilities.imagery import create_band_stack, create_blank_tif, create_composite, merge_tif_with_blank
from common.utilities.masking import save_cloud_masked_images
from common.utilities.projections import get_collection_bbox_coverage, reproject_shape



def get_collection(start_date, end_date, bbox, dst_path, max_cloud_cover=20, max_tile_count=6):

    assert end_date > start_date

    stac_date_format = '%Y-%m-%dT%H:%M:%SZ'
    stac_date_string = start_date.strftime(stac_date_format) + '/' + end_date.strftime(stac_date_format)

    # Open a catalog
    client = Client.open("https://earth-search.aws.element84.com/v0")

    # Get results for a collection in the catalog
    search = client.search(
        bbox=bbox,
        collections=['sentinel-s2-l2a-cogs'], 
        datetime=stac_date_string,
        #sortby='-properties.datetime',
        sortby='properties.eo:cloud_cover',
        query={
            "eo:cloud_cover":{
                "lt": str(max_cloud_cover)
            },
        },
    )

    # limit number of images per Sentinel grid square
    items, items_count = [], {}
    for item in list(search.items()):
        square = item.properties['sentinel:grid_square']
        count = items_count.get(square, 0)
        if count < max_tile_count:
            items.append(item)
            items_count[square] = count + 1
            
    collection = ItemCollection(items=items)

    if len(items) == 0:
        raise EmptyCollectionException(f'no items with cloud cover {max_cloud_cover}% and bbox {bbox}')

    for square in items_count:
        if items_count[square] < 3:
            raise NotEnoughItemsException(f'only {items_count[square]} items for square {square} with cloud cover {max_cloud_cover}%')

    bbox_coverage = get_collection_bbox_coverage(collection, bbox)
    if bbox_coverage < 100:
        raise IncompleteCoverageException(f'coverage is {bbox_coverage}% of bbox {bbox}')

    print(f"{dst_path}: {items_count}")

    collection.save_object(dst_path)
    return collection



def get_scene_metadata(href):
    
    res = requests.get(href)
    data = res.content
    root = ET.fromstring(data)
            
    mean_angle = root.find(".//Mean_Sun_Angle")
    azimuth = float(mean_angle.find("AZIMUTH_ANGLE").text)
    zenith = float(mean_angle.find("ZENITH_ANGLE").text)
    
    return {
        'AZIMUTH_ANGLE': azimuth,
        'ZENITH_ANGLE': zenith
    }



def get_processed_composites(collection, bbox, dst_dir):

    original_scenes_dict = __download_original_imagery(collection, bbox, S2_BANDS, dst_dir)
        
    masked_scenes_dict = {}
    for scene in original_scenes_dict:
        print(f'masking... {scene}')
        scene_dir = f'{dst_dir}/{scene}'
        scene_dict = original_scenes_dict[scene]
        masked_scenes_dict[scene] = save_cloud_masked_images(scene_dict, scene_dir)  
        
    composite_dict = {}
    for band in S2_BANDS:
        if band == "SCL": continue

        print(f'stacking... {band}')
        masked_paths = [masked_scenes_dict[scene][band] for scene in masked_scenes_dict]
        stack_path = create_band_stack(band, masked_paths, dst_dir)
        
        print(f'compositing... {band}')
        composite_path = create_composite(band, stack_path, dst_dir, method="median")        
        composite_dict[band] = composite_path

    return composite_dict



def __download_original_imagery(collection, bbox, bands, dst_dir):

    bbox_poly_ll = box(*bbox)

    blank_path = create_blank_tif(bbox_poly_ll, dst_dir)

    scenes_dict = {}
    for item in list(collection):
        print(f'downloading... {item.id}')
        scenes_dict[item.id] = {}

        band_hrefs = [item.assets[band].href for band in bands]

        scenes_dict[item.id]['meta'] = get_scene_metadata(item.assets['metadata'].href)
        
        # reproject bbox into UTM of S2 item 
        item_epsg = f'EPSG:{item.properties["proj:epsg"]}'
        bbox_sw_utm = reproject_shape(Point(bbox[0], bbox[1]), init_proj="EPSG:4326", target_proj=item_epsg)
        bbox_ne_utm = reproject_shape(Point(bbox[2], bbox[3]), init_proj="EPSG:4326", target_proj=item_epsg)
        
        # get intersection of bbox and S2 scene for windowed read
        scene_poly_ll = shape(item.geometry) # Polygon of the entire original image
        overlap_poly_ll = bbox_poly_ll.intersection(scene_poly_ll)

        # get overlap in lat/lng for saving TIF
        overlap_bbox_ll = overlap_poly_ll.bounds
        
        scene_dir = f'{dst_dir}/{item.id}'
        if not os.path.exists(scene_dir):
            os.mkdir(scene_dir)
            
        for s3_href in band_hrefs:
            
            band_name = s3_href.split('/')[-1].split('.')[0]
            band_path = f'{scene_dir}/{band_name}.tif'
            merged_path = f'{scene_dir}/{band_name}_merged.tif'

            if os.path.exists(merged_path):
                scenes_dict[item.id][band_name] = merged_path
                continue

            with rasterio.open(s3_href) as s3_src:

                window = rasterio.windows.from_bounds(
                    bbox_sw_utm.x, bbox_sw_utm.y, 
                    bbox_ne_utm.x, bbox_ne_utm.y, 
                    transform=s3_src.transform
                )

                s3_data = s3_src.read(1, window=window)
                
                height, width = s3_data.shape[0], s3_data.shape[1]

                new_transform = rasterio.transform.from_bounds(
                    overlap_bbox_ll[0], overlap_bbox_ll[1], 
                    overlap_bbox_ll[2], overlap_bbox_ll[3], 
                    width, height
                )
                
                kwargs = {
                    "driver": "GTiff",
                    "height": height,
                    "width": width,
                    "count": 1,
                    "dtype": s3_data.dtype,
                    "crs": rasterio.crs.CRS.from_epsg(4326),
                    "transform": new_transform
                }
                                
                kwargs["nodata"] = NODATA_BYTE if band_name == "SCL" else NODATA_UINT16

                with rasterio.open(band_path, "w", **kwargs) as new_src:
                    new_src.write(s3_data, 1)

                res = 10 / (111.32 * 1000)
                gdal.Warp(band_path, band_path, xRes=res, yRes=res, outputBounds=overlap_poly_ll.bounds)
                
                merged_path = merge_tif_with_blank(band_path, blank_path, band_name, bbox_poly_ll, merged_path=merged_path)
                scenes_dict[item.id][band_name] = merged_path

    return scenes_dict
            
