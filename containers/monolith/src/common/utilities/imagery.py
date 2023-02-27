import gdal2tiles
import numpy as np
import os
from osgeo import gdal
import rasterio
import rasterio.merge
import shutil
import warnings

from common.constants import NODATA_FLOAT32


warnings.filterwarnings("ignore", category=RuntimeWarning)


### imagery preparation ###

def merge_scenes(scenes_dict, merged_path):
    
    if len(scenes_dict) == 1:
        print('only one scene to merge; copying')
        only_path = list(scenes_dict.values())[0]
        shutil.copy2(only_path, merged_path)
        return

    masked_sources = []
    for scene in scenes_dict:
        src = rasterio.open(scenes_dict[scene])
        masked_sources.append(src)
        
    sum_data, sum_transform = rasterio.merge.merge(masked_sources, indexes=[1, 2, 3, 4], method="sum", nodata=NODATA_FLOAT32)  
    sum_data = np.ma.array(sum_data, mask=(sum_data==NODATA_FLOAT32))

    count_data, count_transform = rasterio.merge.merge(masked_sources, indexes=[1, 2, 3, 4], method="count", nodata=NODATA_FLOAT32)  
    count_data = np.ma.array(count_data, mask=(count_data==NODATA_FLOAT32))
    
    mean_data = sum_data / count_data    
    mean_data = mean_data.transpose((1, 2, 0))
    
    write_array_to_tif(mean_data, merged_path, None, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32, transform=sum_transform) 


### normalization ###

def normalize_3d_array_percentiles(data, p_low=1, p_high=99):
    # data.shape = (c, h, w)
    data[data.mask] = np.nan   
    norm_data = np.zeros_like(data)
    p1, p99 = np.nanpercentile(data.data, [p_low, p_high], axis=[1, 2])
    
    for i in range(p1.shape[0]):
        band_data = np.clip(data[i, :, :], p1[i], p99[i])
        band_data = (band_data - p1[i]) / (p99[i] - p1[i])
        norm_data[i, :, :] = band_data
    
    return norm_data


def normalize_original_s2_array(data):

    norm_data = data.astype(np.float32) / 4095 # 4095 is the max value according to ESA
    norm_data[norm_data > 1] = 1
    return norm_data


### TIF creation ###

def create_rgb_byte_tif_from_composite(composite_path, dst_path, is_cog=False):
    
    with rasterio.open(composite_path) as src:
        bbox = list(src.bounds)
        rgb_stack = src.read((3, 2, 1), masked=True)

    rgb_stack = normalize_3d_array_percentiles(rgb_stack, 0.1, 99.9)
    rgb_stack = (rgb_stack * 254).astype(np.uint8)        
    rgb_stack = rgb_stack.transpose((1, 2, 0))
    
    write_array_to_tif(rgb_stack, dst_path, bbox, dtype=np.uint8, is_cog=is_cog, nodata=255)


def write_array_to_tif(data, dst_path, bbox, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32, is_cog=False, transform=None):
        
    height, width = data.shape[0], data.shape[1]

    if transform is None:
        transform = rasterio.transform.from_bounds(
            bbox[0], bbox[1],
            bbox[2], bbox[3], 
            width, height
        )

    count = 1 if data.ndim == 2 else data.shape[2]
    
    meta = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": count,
        "dtype": dtype,
        "crs": rasterio.crs.CRS.from_epsg(epsg),
        "transform": transform,
        "nodata": nodata
    }
    
    if is_cog:
        write_path = dst_path.replace('.tif', '_temp.tif')
    else:
        write_path = dst_path
        
    with rasterio.open(write_path, "w", **meta) as dst:
        if count == 1:
            dst.write(data, indexes=1)
        else:
            for i in range(count):
                band_data = data[:, :, i]
                
                if np.ma.is_masked(band_data):
                    mask = band_data.mask
                    band_data = band_data.data
                    band_data[mask] = nodata
                    
                dst.write(band_data, indexes=i+1)
    
    if is_cog:
        translate_options = gdal.TranslateOptions(format="COG")
        gdal.Translate(dst_path, write_path, options=translate_options)
        os.remove(write_path)


### Map tile creation ###

def create_map_tiles(file_path, tiles_dir, min_zoom=2, max_zoom=14):

    print(f'generating tiles from {file_path} to {tiles_dir}/')

    options = {
        'kml': True,
        'nb_processes': 4,
        'title': 'Smart Carte',
        'zoom': (min_zoom, max_zoom),
    }

    gdal2tiles.generate_tiles(file_path, tiles_dir, **options)
