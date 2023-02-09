import math
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
from common.constants import NODATA_BYTE, NODATA_FLOAT32, NODATA_UINT16, S2_BANDS, S2_BANDS_TIFF_ORDER
from common.utilities.imagery import create_band_stack, create_blank_tif, create_composite, create_composite_from_paths, create_scene_cog, create_tif_from_vrt, create_vrt, merge_tif_with_blank, write_array_to_tif
from common.utilities.masking import apply_cloud_mask_and_normalize
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
            print(items_count)
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



def get_processed_composite(collection, bbox, dst_dir):

    merged_scenes = download_collection(collection, bbox, S2_BANDS_TIFF_ORDER, dst_dir)
    
    masked_scenes = {}
    for scene in merged_scenes:        
        print(f'\tmasking and normalizing... {scene}')

        scene_dir = f'{dst_dir}/{scene}'        
        meta = merged_scenes[scene]['meta']
        stack_tif_path = merged_scenes[scene]['stack_tif_path']
        masked_tif_path = f'{dst_dir}/{scene}/stack_masked.tif'
        
        apply_cloud_mask_and_normalize(stack_tif_path, meta, masked_tif_path, overwrite=True)
        masked_scenes[scene] = masked_tif_path
        
        #if os.path.exists(stack_tif_path):
        #    os.remove(stack_tif_path)

            
    print('\tcompositing...')
    composite_path = f'{dst_dir}/composite.tif'
    merged_tif_paths = list(masked_scenes.values())    
    print(merged_tif_paths)
    create_composite_from_paths(merged_tif_paths, composite_path, overwrite=True)
    
    return composite_path



def download_bbox(bbox, cog_url, read_all=False):
            
    with rasterio.open(cog_url) as s3_src:

        window = rasterio.windows.from_bounds(
            bbox[0], bbox[1], 
            bbox[2], bbox[3], 
            transform=s3_src.transform
        )
        
        # TODO: get dtype of s3_src and use in astype

        if read_all:
            s3_data = s3_src.read(masked=True, window=window).astype(np.uint16)
        else:
            s3_data = s3_src.read(1, masked=True, window=window).astype(np.uint16)
    
    return s3_data
    
    

def download_collection(collection, bbox, bands, dst_dir):

    bbox_poly_ll = box(*bbox)

    blank_float32_path = f'{dst_dir}/blank_float32.tif'
    create_blank_tif(bbox_poly_ll, dst_path=blank_float32_path, dtype=gdal.GDT_Float32, nodata=NODATA_FLOAT32)
    
    scenes = {}
    for item in list(collection):
        
        print(f'\tdownloading... {item.id}')

        scenes[item.id] = {}
        band_hrefs = [item.assets[band].href for band in bands]
        scenes[item.id]['meta'] = get_scene_metadata(item.assets['metadata'].href)
        
        # reproject bbox into UTM of S2 item 
        item_epsg = f'EPSG:{item.properties["proj:epsg"]}'
        bbox_sw_utm = reproject_shape(Point(bbox[0], bbox[1]), init_proj="EPSG:4326", target_proj=item_epsg)
        bbox_ne_utm = reproject_shape(Point(bbox[2], bbox[3]), init_proj="EPSG:4326", target_proj=item_epsg)
        bbox_utm = [bbox_sw_utm.x, bbox_sw_utm.y, bbox_ne_utm.x, bbox_ne_utm.y]

        # get intersection of bbox and S2 scene for windowed read
        scene_poly_ll = shape(item.geometry) # Polygon of the entire original image
        overlap_poly_ll = bbox_poly_ll.intersection(scene_poly_ll)

        # get overlap in lat/lng for saving TIF
        overlap_bbox_ll = overlap_poly_ll.bounds
        
        scene_dir = f'{dst_dir}/{item.id}'
        if not os.path.exists(scene_dir):
            os.mkdir(scene_dir)
        
        stack_tif_path = f'{scene_dir}/stack.tif'
        stack_masked_tif_path = f'{scene_dir}/stack_masked.tif'  
        if os.path.exists(stack_tif_path) or os.path.exists(stack_masked_tif_path):
            scenes[item.id]['stack_tif_path'] = stack_tif_path
            continue
        
        merged_tif_paths = []
        for s3_href in band_hrefs:
                        
            band_name = s3_href.split('/')[-1].split('.')[0]
            band_path = f'{scene_dir}/{band_name}.tif'
            merged_path = f'{scene_dir}/{band_name}_merged.tif'
            
            if os.path.exists(merged_path):
                merged_tif_paths.append(merged_path)
                continue
            
            s3_data = download_bbox(bbox_utm, s3_href)
            write_array_to_tif(s3_data.astype(np.float32), band_path, overlap_bbox_ll, dtype=np.float32, nodata=NODATA_FLOAT32)
            
            if band_name not in ["B02", "B03", "B04", "B08"]:
                res = 10 / (111.32 * 1000)            
                gdal.Warp(band_path, band_path, xRes=res, yRes=res, outputBounds=overlap_bbox_ll)

            merge_tif_with_blank(band_path, blank_float32_path, band_name, bbox, merged_path=merged_path)
            merged_tif_paths.append(merged_path)
        

        """
        vrt_path = f'{dst_dir}/temp.vrt'
        create_vrt(merged_tif_paths, vrt_path)
        create_tif_from_vrt(vrt_path, stack_tif_path, isCog=True)
        os.remove(vrt_path)
        """
        
        stack_data = []
        for path in merged_tif_paths:
            with rasterio.open(path) as src:
                stack_data.append(src.read(1))
                
        stack_data = np.ma.array(stack_data).transpose((1, 2, 0))
        write_array_to_tif(stack_data, stack_tif_path, bbox, dtype=np.float32, nodata=NODATA_FLOAT32) 
        scenes[item.id]['stack_tif_path'] = stack_tif_path
        
        #for merged_path in merged_tif_paths:
        #    os.remove(merged_path)
        
        
    return scenes


