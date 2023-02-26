import gdal2tiles
import numpy as np
import os
from osgeo import gdal, gdalconst, osr
import rasterio
import rasterio.merge
from rasterio.windows import Window
import rioxarray
from shapely.geometry import box
import shutil
import warnings

from common.constants import NODATA_BYTE, NODATA_FLOAT32


warnings.filterwarnings("ignore", category=RuntimeWarning)


### imagery preparation ###

def create_band_stack(band_name, tif_paths, dst_dir):
    
    with rasterio.open(tif_paths[0]) as meta_src:
        meta = meta_src.meta.copy()

    meta.update(count=len(tif_paths))

    stack_path = f'{dst_dir}/{band_name}_stack.tif'
    with rasterio.open(stack_path, 'w', **meta) as stack_dst:
        for id, layer in enumerate(tif_paths, start=1):
            with rasterio.open(layer) as lyr_src:
                stack_dst.write_band(id, lyr_src.read(1))

    return stack_path



from common.utilities.projections import reproject_shape

def create_blank_tif(bbox, dst_dir=None, dst_path=None, dtype=gdal.GDT_Float32, nbands=1, nodata=NODATA_FLOAT32, res=None):

    bbox_poly = box(*bbox)
    
    bbox_poly = reproject_shape(bbox_poly, init_proj="EPSG:4326", target_proj="ESRI:102022")    
    
    assert dst_dir is not None or dst_path is not None
    
    bounds = bbox_poly.bounds
    xmin, xmax = bounds[0], bounds[2] 
    ymin, ymax = bounds[1], bounds[3]

    driver = gdal.GetDriverByName('GTiff')
    spatref = osr.SpatialReference()
    spatref.ImportFromEPSG(4326)
    wkt = spatref.ExportToWkt()
    
    
    
    proj = osr.SpatialReference()
    proj.SetProjCS('Africa_Albers_Equal_Area_Conic')
    proj.SetWellKnownGeogCS('WGS84')    
    

    if dst_path is None:
        dst_path = f'{dst_dir}/blank.tif'
        
    xres = res 
    yres = -res
    
    transform = [xmin, xres, 0, ymax, 0, yres]
    
    xsize = int((xmax - xmin) / xres + 0.5)
    ysize = int((ymax - ymin) / -yres + 0.5)

    ds = driver.Create(dst_path, xsize, ysize, nbands, dtype, options=['COMPRESS=LZW', 'TILED=YES'])
    # ds.SetProjection(wkt)
    ds.SetProjection(proj.ExportToWkt())
    ds.SetGeoTransform(transform)
    
    for i in range(nbands):
        ds.GetRasterBand(i+1).Fill(nodata)
        ds.GetRasterBand(i+1).SetNoDataValue(nodata)
        
    ds.FlushCache()
    ds = None
    
    return dst_path


def create_composite(band, stack_path, dst_dir, method="median"):
    
    composite_path = f'{dst_dir}/{band}_composite.tif' 
    
    if not os.path.exists(stack_path):
        raise ValueError(f'{stack_path} does not exist')
    
    with rasterio.open(stack_path) as stack_src:
        band_count = stack_src.count
        meta = stack_src.meta.copy()
        meta.update(count=1)
        
    stack = rioxarray.open_rasterio(stack_path, chunks=(band_count, 1000, 1000), masked=True)
    
    centre = stack.median(axis=0, skipna=True)
    centre = np.rint(centre).astype(np.uint16)
    centre = centre.compute()
        
    with rasterio.open(composite_path, "w", **meta) as composite_dst:
        composite_dst.write(centre.data, indexes=1)

    return composite_path

            
            
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
    
    

def merge_stack_with_blank(stack_path, blank_path, bbox, res, merged_path=None):
    
    bbox_poly = box(*bbox)
    bbox_poly = reproject_shape(bbox_poly, init_proj="EPSG:4326", target_proj="ESRI:102022")    
    bbox = bbox_poly.bounds
    
    
    if merged_path is None:
        merged_path = stack_path.replace(".tif", "_merged.tif")
        
    with rasterio.open(stack_path) as stack_src:
        with rasterio.open(blank_path) as blank_src:
            merged_data, merged_transform = rasterio.merge.merge([stack_src, blank_src], indexes=[1, 2, 3, 4], method="first", nodata=NODATA_FLOAT32)    
    
    write_array_to_tif(merged_data.transpose((1,2,0)), merged_path, bbox, esri="ESRI:102022", transform=merged_transform)
    
    gdal.Warp(merged_path, merged_path, xRes=res, yRes=res, outputBounds=bbox)              
    
    return merged_path
            


def merge_stack_with_blank_old(stack_path, blank_path, bbox, merged_path=None):
        
    if merged_path is None:
        merged_path = stack_path.replace(".tif", "_merged.tif")
        
    with rasterio.open(blank_path) as blank_src:
        with rasterio.open(stack_path) as stack_src:
    
            bbnds, sbnds = blank_src.bounds, stack_src.bounds
            
            #if bbnds.left == sbnds.left and bbnds.bottom == sbnds.bottom and \
            #bbnds.right == sbnds.right and bbnds.top == sbnds.top:
            #    shutil.copy2(stack_path, merged_path)
            #    return merged_path

            # create a temp directory to store individual masked band files
            temp_dir = stack_path.replace('.tif', '_temp')
            os.makedirs(temp_dir, exist_ok=True)
            
            temp_meta = stack_src.meta.copy()
            temp_meta.update(count=1)

            merged_meta = blank_src.meta.copy()
            merged_meta.update(count=stack_src.count)
                        
            merged_stack_data = []
            for i in range(1, stack_src.count+1):
                temp_data = stack_src.read(i) # masked?
                                
                temp_band_path = f'{temp_dir}/b{i}.tif'
                with rasterio.open(temp_band_path, "w", **temp_meta) as temp_dst:
                    temp_dst.write(temp_data, indexes=1)
                
                with rasterio.open(temp_band_path) as temp_src:
                    
                    merged_band_data, output_transform = rasterio.merge.merge([temp_src, blank_src], bounds=bbox)
                    merged_band_data = merged_band_data[0, :, :]
                    merged_stack_data.append(merged_band_data)           
                    
            merged_stack_data = np.array(merged_stack_data)
            merged_stack_data = merged_stack_data.transpose((1, 2, 0))            
            write_array_to_tif(merged_stack_data, merged_path, bbox)
            
            shutil.rmtree(temp_dir)
          
    res = 10 / (111.32 * 1000)
    gdal.Warp(merged_path, merged_path, xRes=res, yRes=res, outputBounds=bbox)      
        
    return merged_path
            
            
        
def merge_tif_with_blank(tif_path, blank_path, band_name, bbox_ll, merged_path=None):

    if merged_path is None:
        merged_path = tif_path.replace(".tif", "_merged.tif")
    
    # TODO: handle stack input tif
    
    with rasterio.open(blank_path) as blank_src:
        
        with rasterio.open(tif_path) as tif_src:
            
            # if the bounds are the same then just skip merging
            tbnds, dbnds = blank_src.bounds, tif_src.bounds
            if tbnds.left == dbnds.left and tbnds.bottom == dbnds.bottom and \
            tbnds.right == dbnds.right and tbnds.top == dbnds.top:
                shutil.copy2(tif_path, merged_path)
                return merged_path

            merged, transform_ = rasterio.merge.merge([tif_src, blank_src], bounds=bbox_ll)
            merged = merged[0, :, :]
            
            merged_profile = blank_src.profile.copy()

    with rasterio.open(merged_path, "w", **merged_profile) as new_src:
        new_src.write(merged, 1)

    return merged_path

    
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

def create_scene_cog(src_paths, dst_path):
    print(src_paths)
    print(dst_path)

    vrt_path = dst_path.replace('.tif', '_temp.vrt')
    print(vrt_path)
    
    create_vrt(src_paths, vrt_path)
    create_tif(vrt_path, dst_path, isCog=True)


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

    

def create_rgb_byte_tif_from_composite(composite_path, dst_path):
    
    with rasterio.open(composite_path) as src:
        bbox = list(src.bounds)
        rgb_stack = src.read((3, 2, 1), masked=True)

    rgb_stack = normalize_3d_array_percentiles(rgb_stack, 1, 99)
    rgb_stack = (rgb_stack * 254).astype(np.uint8)        
    rgb_stack = rgb_stack.transpose((1, 2, 0))
    
    write_array_to_tif(rgb_stack, dst_path, bbox, dtype=np.uint8, nodata=255)

   
    
def write_array_to_tif(data, dst_path, bbox, dtype=np.float32, epsg=4326, esri=None, nodata=NODATA_FLOAT32, is_cog=False, transform=None):
        
    height, width = data.shape[0], data.shape[1]

    if transform is None:
        transform = rasterio.transform.from_bounds(
            bbox[0], bbox[1],
            bbox[2], bbox[3], 
            width, height
        )

    count = 1 if data.ndim == 2 else data.shape[2]
    
    crs = rasterio.crs.CRS.from_string("ESRI:102022") if esri is not None else rasterio.crs.CRS.from_epsg(epsg)
    
    meta = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": count,
        "dtype": dtype,
        "crs": crs,
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



