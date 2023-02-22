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
from common.utilities.imagery import create_blank_tif, create_composite_from_paths, merge_stack_with_blank, normalize_original_s2_array, write_array_to_tif
from common.utilities.masking import apply_cloud_mask, apply_nn_cloud_mask
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

    composite_path = f'{dst_dir}/composite.tif'
    if os.path.exists(composite_path):
        return composite_path

    blank_float32_path = f'{dst_dir}/blank_float32.tif'
    create_blank_tif(bbox, dst_path=blank_float32_path, dtype=gdal.GDT_Float32, nodata=NODATA_FLOAT32)
    
    original_scenes = download_collection(collection, bbox, S2_BANDS_TIFF_ORDER, dst_dir)
    
    processed_scenes = {}
    for scene in original_scenes:        
        print(f'\tmasking and normalizing... {scene}')

        scene_dir = f'{dst_dir}/{scene}'        
        meta = original_scenes[scene]['meta']
        
        stack_original_tif_path = original_scenes[scene]['stack_original_tif_path']  # 1. original, normalized
        stack_masked_tif_path = f'{scene_dir}/stack_masked.tif'                      # 2. masked
        stack_masked_merged_tif_path = f'{scene_dir}/stack_masked_merged.tif'        # 3. merged with blank
        
        model_path = './best_resnet18_dice_virunga_cloud_model.pth'
        apply_nn_cloud_mask(stack_original_tif_path, meta, stack_masked_tif_path, model_path)
        
        merge_stack_with_blank(stack_masked_tif_path, blank_float32_path, bbox, merged_path=stack_masked_merged_tif_path)
        processed_scenes[scene] = stack_masked_merged_tif_path
        
        #if os.path.exists(stack_original_tif_path):
        #    os.remove(stack_original_tif_path)

        #if os.path.exists(stack_masked_tif_path):
        #    os.remove(stack_masked_tif_path)
                        
    print('\tcompositing...')
    stacks_processed_tif_paths = list(processed_scenes.values())    
    create_composite_from_paths(stacks_processed_tif_paths, composite_path)
    
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
    
    return s3_data
    
    
def download_collection(collection, bbox, bands, dst_dir):

    bbox_poly_ll = box(*bbox)

    scenes = {}
    for item in list(collection):
        
        print(f'\tdownloading... {item.id}')

        scenes[item.id] = {}
        band_hrefs = [item.assets[band].href for band in bands]
        scenes[item.id]['meta'] = get_scene_metadata(item.assets['metadata'].href)
        
        # reproject bbox into UTM zone of S2 scene 
        item_epsg = f'EPSG:{item.properties["proj:epsg"]}'
        bbox_sw_utm = reproject_shape(Point(bbox[0], bbox[1]), init_proj="EPSG:4326", target_proj=item_epsg)
        bbox_ne_utm = reproject_shape(Point(bbox[2], bbox[3]), init_proj="EPSG:4326", target_proj=item_epsg)
        bbox_utm = [bbox_sw_utm.x, bbox_sw_utm.y, bbox_ne_utm.x, bbox_ne_utm.y]

        # get intersection of bbox and S2 scene for windowed read
        scene_poly_ll = shape(item.geometry) # polygon of the entire scene
        overlap_poly_ll = bbox_poly_ll.intersection(scene_poly_ll) # polygon of intersection between entire scene and bbox
        overlap_bbox_ll = overlap_poly_ll.bounds
        
        scene_dir = f'{dst_dir}/{item.id}'
        stack_original_tif_path = f'{scene_dir}/stack_original.tif'

        if not os.path.exists(scene_dir):
            os.mkdir(scene_dir)
        
        band_tif_paths = []
        
        for s3_href in band_hrefs:
                        
            band_name = s3_href.split('/')[-1].split('.')[0]
            band_path = f'{scene_dir}/{band_name}.tif'
            
            s3_data = download_bbox(bbox_utm, s3_href)
            s3_data = normalize_original_s2_array(s3_data)
            
            write_array_to_tif(s3_data.astype(np.float32), band_path, overlap_bbox_ll, dtype=np.float32, nodata=NODATA_FLOAT32)

            res = 10 / (111.32 * 1000) # is this kosher ?     
            gdal.Warp(band_path, band_path, xRes=res, yRes=res, outputBounds=overlap_bbox_ll)
            
            band_tif_paths.append(band_path)
            
        stack_data = []
        for path in band_tif_paths:
            with rasterio.open(path) as src:
                stack_data.append(src.read(1))
                
        stack_data = np.array(stack_data).transpose((1, 2, 0))
                
        write_array_to_tif(stack_data, stack_original_tif_path, overlap_bbox_ll, dtype=np.float32, nodata=NODATA_FLOAT32) 
        scenes[item.id]['stack_original_tif_path'] = stack_original_tif_path
        
    return scenes


