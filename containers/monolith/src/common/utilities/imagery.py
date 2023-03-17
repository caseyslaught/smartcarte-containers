import gdal2tiles
import numpy as np
import os
from osgeo import gdal, gdalconst, osr
import rasterio
import rasterio.merge
from rasterio.windows import Window
import shutil
import warnings

from common.constants import NODATA_BYTE, NODATA_FLOAT32
from common.exceptions import NotEnoughItemsException

warnings.filterwarnings("ignore", category=RuntimeWarning)


### imagery preparation ###


def create_blank_tif(bbox, dst_dir=None, dst_path=None, dtype=gdal.GDT_Float32, nbands=4, nodata=NODATA_FLOAT32, res=None):
        
    assert dst_dir is not None or dst_path is not None
    
    xmin, xmax = bbox[0], bbox[2] 
    ymin, ymax = bbox[1], bbox[3]

    driver = gdal.GetDriverByName('GTiff')
    spatref = osr.SpatialReference()
    spatref.ImportFromEPSG(4326)
    wkt = spatref.ExportToWkt()
    
    if dst_path is None:
        dst_path = f'{dst_dir}/blank.tif'
        
    xres = res 
    yres = -res
    
    transform = [xmin, xres, 0, ymax, 0, yres]
    
    xsize = int((xmax - xmin) / xres + 0.5)
    ysize = int((ymax - ymin) / -yres + 0.5)

    ds = driver.Create(dst_path, xsize, ysize, nbands, dtype, options=['COMPRESS=LZW', 'TILED=YES'])
    ds.SetProjection(wkt)
    ds.SetGeoTransform(transform)
    
    for i in range(nbands):
        ds.GetRasterBand(i+1).Fill(nodata)
        ds.GetRasterBand(i+1).SetNoDataValue(nodata)
        
    ds.FlushCache()
    ds = None
    
    return dst_path

            
def create_composite_from_paths(stack_paths, dst_path, nodata=NODATA_FLOAT32):
    
    if len(stack_paths) == 0:
        return False
    
    elif len(stack_paths) == 1:
        shutil.copy2(stack_paths[0], dst_path)
        return True
    
    with rasterio.open(stack_paths[0]) as src:
        band_count = src.count
        meta = src.meta.copy()
        nrows, ncols = src.height, src.width
        # nrows, ncols = src.shape[0], src.shape[1]        
    
    with rasterio.open(dst_path, 'w', **meta) as dst:   
        
        # process batch_size rows at a time
        batch_size = 1600
        for row in np.arange(0, nrows, batch_size):
            
            # current bsize is batch_size unless we are near the end of the file
            bsize = nrows - row if row + batch_size > nrows else batch_size
            window = Window(0, row, ncols, bsize)

            # loop through each stack and read the data into a list
            batch_data = []
            for path in stack_paths:
                with rasterio.open(path) as src:
                    data = src.read(masked=True, window=window)   
                    data[data.mask] = np.nan
                    batch_data.append(data)
        
            # calculate the median of the batch along the 0th axis (band)
            batch_data = np.array(batch_data)            
            batch_centre = np.nanmedian(batch_data, axis=0)
            # batch_centre = np.nanmean(batch_data, axis=0)

            # write the data to the output file
            for i in range(band_count):
                band_data = batch_centre[i, :, :]
                masked_data = np.nan_to_num(band_data, nan=nodata)
                dst.write(masked_data, indexes=i+1, window=window)
                
    return True
    

def merge_scenes(scenes_dict, merged_path):

    masked_sources = []
    for scene in scenes_dict:
        src = rasterio.open(scenes_dict[scene])
        masked_sources.append(src)

    if len(masked_sources) == 0:
        raise NotEnoughItemsException("Not masked sources to merge")
    elif len(masked_sources) == 1:
        shutil.copy2(masked_sources[0].name, merged_path)
        return
    
    masked_sources = [masked_sources[0]]

    sum_data, sum_transform = rasterio.merge.merge(masked_sources, indexes=[1, 2, 3, 4], method="sum", nodata=NODATA_FLOAT32)  
    sum_data = np.ma.array(sum_data, mask=(sum_data==NODATA_FLOAT32))

    count_data, count_transform = rasterio.merge.merge(masked_sources, indexes=[1, 2, 3, 4], method="count", nodata=NODATA_FLOAT32)  
    count_data = np.ma.array(count_data, mask=(count_data==NODATA_FLOAT32))
    
    mean_data = sum_data / count_data    
    mean_data = mean_data.transpose((1, 2, 0))
    
    write_array_to_tif(mean_data, merged_path, None, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32, transform=sum_transform) 


def merge_stack_with_blank(stack_path, blank_path, bbox, res, merged_path=None):  
    
    if merged_path is None:
        merged_path = stack_path.replace(".tif", "_merged.tif")
        
    with rasterio.open(stack_path) as stack_src:
        with rasterio.open(blank_path) as blank_src:
            merged_data, merged_transform = rasterio.merge.merge([stack_src, blank_src], indexes=[1, 2, 3, 4], method="first", nodata=NODATA_FLOAT32)    
    
    write_array_to_tif(merged_data.transpose((1,2,0)), merged_path, None, epsg=4326, transform=merged_transform)    
    # gdal.Warp(merged_path, merged_path, xRes=res, yRes=res) # , outputBounds=bbox)              
    
    return merged_path   

    
def normalize_3d_array_percentiles(data, p_low=1, p_high=99, is_transposed=False):
    # data.shape = (c, h, w)
    
    if np.ma.is_masked(data):
        data = data.filled(np.nan)
            
    norm_data = np.zeros_like(data)
    
    if is_transposed:
        p1, p99 = np.nanpercentile(data, [p_low, p_high], axis=[0, 1])
    else:
        p1, p99 = np.nanpercentile(data, [p_low, p_high], axis=[1, 2])
                
    for i in range(p1.shape[0]):
        if is_transposed:
            band_data = np.clip(data[:, :, i], p1[i], p99[i])
            band_data = (band_data - p1[i]) / (p99[i] - p1[i])
            norm_data[:, :, i] = band_data
        else:
            band_data = np.clip(data[i, :, :], p1[i], p99[i])
            band_data = (band_data - p1[i]) / (p99[i] - p1[i])
            norm_data[i, :, :] = band_data
    
    return norm_data


def normalize_original_s2_array(data):

    norm_data = data.astype(np.float32) / 4095 # 4095 is the max value according to ESA
    norm_data[norm_data > 1] = 1
    return norm_data
    

def normalize_tif(tif_path, dst_path=None):
    if dst_path is None:
        dst_path = tif_path
        
    with rasterio.open(tif_path) as src:
        data = src.read(masked=True)
        bbox = list(src.bounds)
        
    norm_data = normalize_original_s2_array(data)
    
    norm_data = norm_data.transpose((1, 2, 0))
    write_array_to_tif(norm_data, dst_path, bbox, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32)


### VRT and GeoTIFF creation ###


def create_vrt(band_paths, dst_path):

    vrt_options = gdal.BuildVRTOptions(separate=True)
    gdal.BuildVRT(dst_path, band_paths, options=vrt_options)


def create_tif_from_vrt(vrt_path, dst_path, isCog=False, nodata=NODATA_FLOAT32):

    _format = "COG" if isCog else "GTiff"

    translate_options = gdal.TranslateOptions(
        format=_format, 
        noData=nodata,
    )

    gdal.Translate(dst_path, vrt_path, options=translate_options)


def create_byte_vrt(full_vrt_path, dst_path):

    translate_options = gdal.TranslateOptions(
        format="VRT", 
        outputType=gdalconst.GDT_Byte, 
        scaleParams=[[0, 2000, 0, 255]],
        noData=NODATA_BYTE,
    )
    gdal.Translate(dst_path, full_vrt_path, options=translate_options)

    

def create_rgb_byte_tif_from_composite(composite_path, dst_path, is_cog=False):
    
    with rasterio.open(composite_path) as src:
        bbox = list(src.bounds)
        rgb_stack = src.read((3, 2, 1), masked=True)

    alpha = (rgb_stack[0, :, :] != NODATA_FLOAT32).astype(np.uint8) * 255

    rgb_stack = normalize_3d_array_percentiles(rgb_stack, 0.1, 99.9)
    rgb_stack = (rgb_stack * 254).astype(np.uint8)      

    rgbA_stack = np.stack((rgb_stack[0, :, :], rgb_stack[1, :, :], rgb_stack[2, :, :], alpha), axis=0)
    rgbA_stack = rgbA_stack.transpose((1, 2, 0))
    
    write_array_to_tif(rgbA_stack, dst_path, bbox, dtype=np.uint8, is_cog=is_cog, nodata=255)

   
    
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

    wb_file_path = file_path.replace('.tif', '_wm.tif')
    gdal.Warp(wb_file_path, file_path, dstSRS="EPSG:3857")

    print(wb_file_path)

    options = {
        'kml': True,
        'nb_processes': 4,
        'profile': 'mercator',
        's_srs': 'EPSG:3857',
        'tile_size': 256,
        'title': 'Smart Carte',
        'zoom': (min_zoom, max_zoom),
    }

    gdal2tiles.generate_tiles(wb_file_path, tiles_dir, **options)


