import gdal2tiles
import numpy as np
import os
from osgeo import gdal, gdalconst, osr
import rasterio
import rasterio.merge
from rasterio.windows import Window
import rioxarray
import shutil
import warnings

from common.constants import NODATA_BYTE, NODATA_FLOAT32, NODATA_FLOAT64, NODATA_UINT16


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


def create_blank_tif(bbox_poly_ll, dst_dir=None, dst_path=None, dtype=gdal.GDT_UInt16, nodata=NODATA_UINT16, res_meters=10):

    assert dst_dir is not None or dst_path is not None
    
    bounds = bbox_poly_ll.bounds
    xmin, xmax = bounds[0], bounds[2] 
    ymin, ymax = bounds[1], bounds[3]

    driver = gdal.GetDriverByName('GTiff')
    spatref = osr.SpatialReference()
    spatref.ImportFromEPSG(4326)
    wkt = spatref.ExportToWkt()

    if dst_path is None:
        dst_path = f'{dst_dir}/blank.tif'
    
    nbands = 1
    
    res = res_meters / (111.32 * 1000)
    xres = res  # resx = 10 / (111.32 * 1000) * cos((ymax-ymin)/2)
    yres = -res
    
    transform = [xmin, xres, 0, ymax, 0, yres]
    
    xsize = int((xmax - xmin) / xres + 0.5)
    ysize = int((ymax - ymin) / -yres + 0.5)

    ds = driver.Create(dst_path, xsize, ysize, nbands, dtype, options=['COMPRESS=LZW', 'TILED=YES'])
    ds.SetProjection(wkt)
    ds.SetGeoTransform(transform)
    ds.GetRasterBand(1).Fill(nodata)
    ds.GetRasterBand(1).SetNoDataValue(nodata)
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

            
            
def create_composite_from_paths(tif_paths, dst_path, nodata=NODATA_FLOAT32):
    
    with rasterio.open(tif_paths[0]) as src:
        band_count = src.count
        meta = src.meta.copy()
        nrows, ncols = src.shape[0], src.shape[1]        
    
    with rasterio.open(dst_path, 'w', **meta) as dst:   
        
        batch_size = 600
        for row in np.arange(0, nrows, batch_size):
            
            bsize = nrows - row if row + batch_size > nrows else batch_size
            window = Window(0, row, ncols, bsize)

            batch_data = []
            for path in tif_paths:
                with rasterio.open(path) as src:
                    data = src.read(masked=True, window=window)   
                    data[data.mask] = np.nan
                    batch_data.append(data)
        
            batch_centre = np.nanmedian(batch_data, axis=0)

            for i in range(band_count):
                band_data = batch_centre[i, :, :]
                masked_data = np.nan_to_num(band_data, nan=nodata)
                dst.write(masked_data, indexes=i+1, window=window)
                    

                    
def merge_tif_with_blank(tif_path, blank_path, band_name, bbox_ll, merged_path=None):

    if merged_path is None:
        merged_path = tif_path.replace(".tif", "_merged.tif")
    
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


def normalize_tif(tif_path, dst_path=None):
    if dst_path is None:
        dst_path = tif_path
        
    with rasterio.open(tif_path) as src:
        data = src.read(masked=True)
        data[data.mask] = np.nan
        bbox = list(src.bounds)
        
    norm_data = np.zeros_like(data)
    p1, p99 = np.nanpercentile(data, [1, 99], axis=[1, 2])
    
    # loop through bands and update norm data
    for i in range(p1.shape[0]):
        band_data = np.clip(data[i, :, :], p1[i], p99[i])
        band_data = (band_data - p1[i]) / (p99[i] - p1[i])
        norm_data[i, :, :] = band_data
                
    norm_data = norm_data.transpose((1, 2, 0))
    write_array_to_tif(norm_data, dst_path, bbox, dtype=norm_data.dtype, epsg=4326, nodata=NODATA_FLOAT32)

        
        
def normalize_3d_array(data):
    
    data[data.mask] = np.nan   
    norm_data = np.zeros_like(data)
    p1, p99 = np.nanpercentile(data, [1, 99], axis=[1, 2])    
    
    for i in range(p1.shape[0]):
        band_data = np.clip(data[i, :, :], p1[i], p99[i])
        band_data = (band_data - p1[i]) / (p99[i] - p1[i])
        norm_data[i, :, :] = band_data
    
    return norm_data


def normalize_1_255(data):
    
    data = (data - data.min()) / (data.max() - data.min()) * 254 + 1
    return data


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


def create_tif_from_vrt(vrt_path, dst_path, isCog=False, nodata=NODATA_FLOAT64):

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
        meta = src.meta.copy()
        bbox = list(src.bounds)
        red = src.read(3, masked=True)
        green = src.read(2, masked=True)
        blue = src.read(1, masked=True)

    red = normalize_1_255(red)
    green = normalize_1_255(green)
    blue = normalize_1_255(blue)    
    rgb_data = np.ma.array([red, green, blue]).transpose((1, 2, 0)).astype(np.uint8)
    
    write_array_to_tif(rgb_data, dst_path, bbox, dtype=np.uint8, nodata=NODATA_BYTE)

   
    
def write_array_to_tif(data, dst_path, bbox, dtype=np.float32, epsg=4326, nodata=NODATA_FLOAT32):
        
    height, width = data.shape[0], data.shape[1]

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
           
    with rasterio.open(dst_path, "w", **meta) as dst:
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



