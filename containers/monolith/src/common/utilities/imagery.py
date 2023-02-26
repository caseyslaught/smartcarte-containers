import gdal2tiles
import numpy as np
import os
from osgeo import gdal, gdalconst, osr
import rasterio
import rasterio.merge
import rioxarray
import shutil
import warnings

from common.constants import NODATA_BYTE, NODATA_UINT16


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


def create_blank_tif(bbox_poly_ll, dst_dir):

    bounds = bbox_poly_ll.bounds
    xmin, xmax = bounds[0], bounds[2] 
    ymin, ymax = bounds[1], bounds[3]

    driver = gdal.GetDriverByName('GTiff')
    spatref = osr.SpatialReference()
    spatref.ImportFromEPSG(4326)
    wkt = spatref.ExportToWkt()

    blank_path = f'{dst_dir}/blank.tif'
    nbands = 1
    
    res = 10 / (111.32 * 1000)
    xres = res  # resx = 10 / (111.32 * 1000) * cos((ymax-ymin)/2)
    yres = -res
    
    transform = [xmin, xres, 0, ymax, 0, yres]

    dtype = gdal.GDT_UInt16

    xsize = int(np.rint(np.abs((xmax - xmin)) / xres))
    ysize = int(np.rint(np.abs((ymax - ymin) / yres)))

    ds = driver.Create(blank_path, xsize, ysize, nbands, dtype, options=['COMPRESS=LZW', 'TILED=YES'])
    ds.SetProjection(wkt)
    ds.SetGeoTransform(transform)
    ds.GetRasterBand(1).Fill(NODATA_UINT16)
    ds.GetRasterBand(1).SetNoDataValue(NODATA_UINT16)
    ds.FlushCache()
    ds = None
    
    return blank_path


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


def merge_tif_with_blank(tif_path, blank_path, band_name, bbox_poly_ll, merged_path=None):

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

            merged, transform_ = rasterio.merge.merge([tif_src, blank_src], bounds=bbox_poly_ll.bounds)
            merged = merged[0, :, :]

            merged_profile = blank_src.profile.copy()
            if band_name == "SCL":
                merged_profile["dtype"] = "uint8"
                merged_profile["nodata"] = NODATA_BYTE

    with rasterio.open(merged_path, "w", **merged_profile) as new_src:
        new_src.write(merged, 1)

    return merged_path



### VRT and TIF creation ###

def create_vrt(band_paths, dst_path):

    vrt_options = gdal.BuildVRTOptions(separate=True)
    gdal.BuildVRT(dst_path, band_paths, options=vrt_options)


def create_tif(vrt_path, dst_path, isCog=False):

    _format = "COG" if isCog else "GTiff"

    translate_options = gdal.TranslateOptions(
        format=_format, 
        noData=NODATA_UINT16,
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
