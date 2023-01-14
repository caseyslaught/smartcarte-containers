import gdal2tiles
import glob
import numpy as np
import numpy.ma as ma
import os
from osgeo import gdal, gdalconst, osr
import rasterio
import rasterio.merge
from rasterio.windows import Window

from common.aws import s3 as s3_utils
from common.constants import NODATA_BYTE, NODATA_UINT16, S3_TASKS_BUCKET


BLANK_TIF_PATH = '/tmp/{}/blank.tif'



def create_byte_rgb_vrt(band_dict, step):

    red = band_dict['B04']
    green = band_dict['B03']
    blue = band_dict['B02']

    vrt_path = f'/tmp/{step}/RGB.vrt'
    print('vrt_path', vrt_path)

    vrt_options = gdal.BuildVRTOptions(separate=True)
    gdal.BuildVRT(vrt_path, [red, green, blue], options=vrt_options)

    vrt_byte_path = vrt_path.replace('RGB.vrt', 'RGB_Byte.vrt')
    translate_options = gdal.TranslateOptions(
        format="VRT", 
        outputType=gdalconst.GDT_Byte, 
        scaleParams=[[0, 2000, 0, 255]],
        noData=NODATA_BYTE
    )
    gdal.Translate(vrt_byte_path, vrt_path, options=translate_options)

    return vrt_path


def create_rgb_map_tiles(rgb_vrt, step):
    tiles_dir = f'/tmp/{step}/tiles/'
    print(f'generating tiles from {rgb_vrt}: {tiles_dir}')

    options = {
        'kml': True,
        'nb_processes': 4,
        'title': 'Smart Carte',
        'zoom': (2, 12),
    }

    gdal2tiles.generate_tiles(rgb_vrt, tiles_dir, **options)
    return tiles_dir


def create_blank_tif(bbox_poly_ea, dir_name):

    temp_bounds_ea = bbox_poly_ea.bounds
    xmin_ea = temp_bounds_ea[0]
    xmax_ea = temp_bounds_ea[2] 
    ymin_ea = temp_bounds_ea[1]
    ymax_ea = temp_bounds_ea[3]

    driver = gdal.GetDriverByName('GTiff')
    spatref = osr.SpatialReference()
    spatref.ImportFromEPSG(3857)
    wkt = spatref.ExportToWkt()

    outfn = BLANK_TIF_PATH.format(dir_name)
    nbands = 1
    xres_ea = 10
    yres_ea = -10

    dtype = gdal.GDT_UInt16

    xsize = int(np.rint(np.abs((xmax_ea - xmin_ea)) / xres_ea))
    ysize = int(np.rint(np.abs((ymax_ea - ymin_ea) / yres_ea)))

    ds = driver.Create(outfn, xsize, ysize, nbands, dtype, options=['COMPRESS=LZW', 'TILED=YES'])
    ds.SetProjection(wkt)
    ds.SetGeoTransform([xmin_ea, xres_ea, 0, ymax_ea, 0, yres_ea])
    ds.GetRasterBand(1).Fill(NODATA_UINT16)
    ds.GetRasterBand(1).SetNoDataValue(NODATA_UINT16)
    ds.FlushCache()
    ds = None

    return outfn



def create_composite(band, stack_path, dir_name, method="median"):
    
    if not os.path.exists(stack_path):
        raise ValueError(f'{stack_path} does not exist')

    with rasterio.open(stack_path) as stack_src:
    
        width, height = stack_src.width, stack_src.height
        composite_path = f'/tmp/{dir_name}/{band}_composite.tif'
        if os.path.exists(composite_path):
            return composite_path
        
        meta = stack_src.meta.copy()
        meta.update(count=1) # NOTE: update count if adding variance
        
        with rasterio.open(composite_path, "w", **meta) as composite_dst:
            for row in range(height):    
                chunk = stack_src.read(window=Window(0, row, width, 1), masked=True)
                centre = np.rint(ma.median(chunk, axis=0)).astype(np.uint16)
                centre_data = centre.data
                centre_data[centre.mask] = NODATA_UINT16   
                composite_dst.write(centre_data, window=Window(0, row, width, 1), indexes=1)

    return composite_path



def create_stack(band, dir_name):
    
    masked_paths = glob.glob(f'/tmp/{dir_name}/*/{band}_masked.tif')
    with rasterio.open(masked_paths[0]) as meta_src:
        meta = meta_src.meta.copy()

    meta.update(count=len(masked_paths))

    stack_path = f'/tmp/{dir_name}/{band}_stack.tif'
    with rasterio.open(stack_path, 'w', **meta) as stack_dst:
        for id, layer in enumerate(masked_paths, start=1):
            with rasterio.open(layer) as band_src:
                stack_dst.write_band(id, band_src.read(1))

    return stack_path


def merge_image_with_blank(image_path, band_name, bbox_poly_ea, dir_name):

    blank_path = BLANK_TIF_PATH.format(dir_name)
    with rasterio.open(blank_path) as blank_src:
        
        with rasterio.open(image_path) as image_src:
            
            # if the bounds are the same then just skip merging
            tbnds, dbnds = blank_src.bounds, image_src.bounds
            if tbnds.left == dbnds.left and tbnds.bottom == dbnds.bottom and \
            tbnds.right == dbnds.right and tbnds.top == dbnds.top:
                return

            merged, transform_ = rasterio.merge.merge([image_src, blank_src], bounds=bbox_poly_ea.bounds)
            merged = merged[0, :, :]

            merged_profile = blank_src.profile.copy()
            if band_name == "SCL":
                merged_profile["dtype"] = "uint8"
                merged_profile["nodata"] = NODATA_BYTE

    with rasterio.open(image_path, "w", **merged_profile) as new_src:
        new_src.write(merged, 1)

    return image_path



def save_tif_to_s3(task_uid, tif_path, step):

    file_name = tif_path.split('/')[-1]
    object_key = f'{task_uid}/{step}/{file_name}'
    
    print(f'uploading {tif_path} to s3://{S3_TASKS_BUCKET}/{object_key}')

    s3_utils.put_item(tif_path, S3_TASKS_BUCKET, object_key)



def save_photo_to_s3(task_uid, photo_path, step):

    file_name = photo_path.split('/')[-1]
    object_key = f'{task_uid}/{step}/{file_name}'

    print(f'uploading {photo_path} to s3://{S3_TASKS_BUCKET}/{object_key}')

    s3_utils.put_item(photo_path, S3_TASKS_BUCKET, object_key)



def save_tiles_dir_to_s3(task_uid, tiles_dir, step):

    print(f'saving {tiles_dir} to S3')

    for root, dirs, files in os.walk(tiles_dir):
        for file in files:
            file_path = os.path.join(root, file)
            subpath = file_path.replace(tiles_dir, '')
            object_key = f'{task_uid}/{step}/tiles/{subpath}'
            
            s3_utils.put_item(file_path, S3_TASKS_BUCKET, object_key)
