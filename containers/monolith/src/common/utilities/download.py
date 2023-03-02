import numpy as np
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
from common.constants import NODATA_FLOAT32, S2_BANDS_TIFF_ORDER
from common.utilities.imagery import merge_scenes, normalize_original_s2_array, write_array_to_tif
from common.utilities.masking import apply_nn_cloud_mask
from common.utilities.projections import get_collection_bbox_coverage, reproject_shape



def get_collection(start_date, end_date, bbox, dst_path, max_cloud_cover=20, max_tile_count=6, min_tile_count=3):
        
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
        if items_count[square] < min_tile_count:
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


def get_processed_composite(collection, bbox, dst_dir, cloud_mask_model_path):

    composite_path = f'{dst_dir}/composite.tif'
    #if os.path.exists(composite_path):
    #    return composite_path

    res = 10 / (111.32 * 1000)

    original_scenes = download_collection(collection, bbox, S2_BANDS_TIFF_ORDER, dst_dir, res)
    
    masked_scenes = {}
    for scene in original_scenes:        
        print(f'\tmasking... {scene}')

        scene_dir = f'{dst_dir}/{scene}'   
        meta = original_scenes[scene]['meta']
        
        stack_original_tif_path = original_scenes[scene]['stack_original_tif_path']    # 1. original, normalized
        stack_masked_tif_path = f'{scene_dir}/stack_masked.tif'                        # 2. masked        
        
        if not apply_nn_cloud_mask(stack_original_tif_path, meta, stack_masked_tif_path, cloud_mask_model_path):
            print(f'\t\tskipping {scene}: too many clouds')
            continue
        
        masked_scenes[scene] = stack_masked_tif_path
        
    merge_scenes(masked_scenes, composite_path)

    return composite_path


def download_bbox(bbox, cog_url, read_all=False):
            
    with rasterio.open(cog_url) as s3_src:
        window = rasterio.windows.from_bounds(
            bbox[0], bbox[1], 
            bbox[2], bbox[3], 
            transform=s3_src.transform
        )
        
        if read_all:
            s3_data = s3_src.read(masked=True, window=window).astype(np.uint16)
        else:
            s3_data = s3_src.read(1, masked=True, window=window).astype(np.uint16)
    
        return (s3_data, rasterio.windows.transform(window, s3_src.transform))



def download_collection(collection, bbox, bands, dst_dir, res):

    bbox_poly_ll = box(*bbox)
       
    scenes = {}
    for item in list(collection):
        
        print(f'\tdownloading... {item.id}')

        scenes[item.id] = {}
        band_hrefs = [item.assets[band].href for band in bands]
        scenes[item.id]['meta'] = get_scene_metadata(item.assets['metadata'].href)
        
        # reproject bbox into UTM zone of S2 scene 
        item_epsg_int = int(item.properties["proj:epsg"])
        item_epsg_str = f'EPSG:{item_epsg_int}'       
        
        # get intersection of bbox and S2 scene for windowed read
        scene_poly_ll = shape(item.geometry) # polygon of the entire scene
        overlap_poly_ll = bbox_poly_ll.intersection(scene_poly_ll) # polygon of intersection between entire scene and bbox
        
        # reproject overlap polygon into UTM and round to nearest 10 meter
        overlap_poly_utm = reproject_shape(overlap_poly_ll, init_proj="EPSG:4326", target_proj=item_epsg_str)
        overlap_bbox_utm = np.round(overlap_poly_utm.bounds  , -1)        
        overlap_poly_utm = box(*overlap_bbox_utm)
        
        overlap_poly_ll = reproject_shape(overlap_poly_utm, init_proj=item_epsg_str, target_proj="EPSG:4326")
        overlap_bbox_ll = list(overlap_poly_ll.bounds)
        
        scene_dir = f'{dst_dir}/{item.id}'
        stack_original_tif_path = f'{scene_dir}/stack_original.tif'
        
        ### TESTING ###
        #if os.path.exists(stack_original_tif_path):
        #    scenes[item.id]['stack_original_tif_path'] = stack_original_tif_path
        #    continue

        if not os.path.exists(scene_dir):
            os.mkdir(scene_dir)
        
        band_tif_paths = []               
        for s3_href in band_hrefs:                        
            band_name = s3_href.split('/')[-1].split('.')[0]
            band_path = f'{scene_dir}/{band_name}.tif'
            
            s3_data, s3_transform = download_bbox(overlap_bbox_utm, s3_href)
            s3_data = normalize_original_s2_array(s3_data)
                                    
            write_array_to_tif(s3_data, band_path, overlap_bbox_utm, dtype=np.float32, epsg=item_epsg_int, nodata=NODATA_FLOAT32, transform=s3_transform)
            gdal.Warp(band_path, band_path, dstSRS="EPSG:4326", xRes=res, yRes=res, outputBounds=overlap_bbox_ll)
            
            band_tif_paths.append(band_path)
            
        stack_data = []
        for path in band_tif_paths:
            with rasterio.open(path) as src:
                stack_data.append(src.read(1))
                
        stack_data = np.array(stack_data).transpose((1, 2, 0))     
        write_array_to_tif(stack_data, stack_original_tif_path, overlap_bbox_ll, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32)        

        scenes[item.id]['stack_original_tif_path'] = stack_original_tif_path

    return scenes



