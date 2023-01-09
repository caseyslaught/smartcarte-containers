import boto3
import glob
import numpy as np
import numpy.ma as ma
import os
from osgeo import gdal, osr
from pystac import ItemCollection
from pystac_client import Client
import rasterio
import rasterio.merge
from rasterio.windows import Window
from shapely.geometry import box, shape, Point

from common import exceptions
from common.constants import NODATA_BYTE, NODATA_UINT16, S2_BANDS, S3_TASKS_BUCKET
from common.utilities.masking import apply_cloud_mask
from common.utilities.projections import get_collection_bbox_coverage, reproject_shape


BLANK_TIF_PATH = '/tmp/{}/blank.tif'


def get_collection(start_date, end_date, bbox, dir_name, max_cloud_cover=20):
    """
    Gets a STAC collection
    Arguments:
        start_date: datetime
        end_date: datetime
        bbox: list as [min_lon, min_lat, max_lon, max_lat]
        dir_name: directory name in /tmp where data is saved
        max_cloud_cover: integer percentage
    Returns:
        ItemCollection
    """

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
        sortby='-properties.datetime',
        query={
            "eo:cloud_cover":{
                "lt": str(max_cloud_cover)
            },
        },
    )

    print(f"{dir_name}: {search.matched()} items found")

    # limit number of images per Sentinel grid square
    limit = 8
    items, items_count = [], {}
    for item in list(search.items()):
        square = item.properties['sentinel:grid_square']
        count = items_count.get(square, 0)
        if count < limit:
            items.append(item)
            items_count[square] = count + 1

    print(f'{dir_name}: {len(items)} filtered items')

    if len(items) == 0:
        raise exceptions.EmptyCollectionException()
            
    collection = ItemCollection(items=items)
    _verify_collection_coverage(collection, bbox)

    collection.save_object(f'/tmp/{dir_name}/s2_collection.json')

    return collection


def _verify_collection_coverage(collection, bbox):
    coverage_pct = get_collection_bbox_coverage(collection, bbox)
    if coverage_pct < 100:
        raise exceptions.IncompleteCoverageException()


def _create_blank_tif(bbox_poly_ea, dir_name):
    """
    Creates a blank TIF with bounds that match the bbox
    Arguments:
        bbox_poly_ea: bbox Polygon object in equal-area projection
        dir_name: directory in /tmp where data is saved
    Returns:
        file path to TTIF
    """

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


def _merge_image_with_blank(image_path, band_name, bbox_poly_ea, dir_name):
    """
    Merges a band image with a blank TIF so that all files have the same shape.
    This is necessary for later creating a composite with multiple images that
    have different original extents.

    Arguments:
        image_path 
        band_name
        bbox_poly_ea
        dir_name
    Returns:
        None
    """

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


def _download_images(collection, bbox, dir_name):

    bbox_poly_ll = box(*bbox)
    bbox_poly_ea = reproject_shape(bbox_poly_ll, "EPSG:4326", "EPSG:3857")

    _create_blank_tif(bbox_poly_ea, dir_name)

    image_paths = []
    for item in list(collection):
        print(item.id)
        print(item.properties["sentinel:grid_square"], "-", str(item.properties['sentinel:utm_zone']) + item.properties["sentinel:latitude_band"])

        band_hrefs = [item.assets[band].href for band in S2_BANDS]
        
        # reproject bbox into projection of S2 scene 
        item_epsg = f'EPSG:{item.properties["proj:epsg"]}'
        bbox_sw_utm = reproject_shape(Point(bbox[0], bbox[1]), init_proj="EPSG:4326", target_proj=item_epsg)
        bbox_ne_utm = reproject_shape(Point(bbox[2], bbox[3]), init_proj="EPSG:4326", target_proj=item_epsg)
        
        # calculate intersection between Sentinel scene and bounding box so that we can save data properly to tif
        scene_poly_ll = shape(item.geometry) # Polygon of the entire original image
        overlap_poly_ll = bbox_poly_ll.intersection(scene_poly_ll)
        overlap_poly_ea = reproject_shape(overlap_poly_ll, "EPSG:4326", "EPSG:3857")

        # get overlap in item UTM projection so we can save subset of data to tif
        overlap_bbox_ll = overlap_poly_ll.bounds
        overlap_sw_utm = reproject_shape(
            Point(overlap_bbox_ll[0], overlap_bbox_ll[1]),
            init_proj="EPSG:4326", 
            target_proj=item_epsg
        )
        overlap_ne_utm = reproject_shape(
            Point(overlap_bbox_ll[2], overlap_bbox_ll[3]), 
            init_proj="EPSG:4326", 
            target_proj=item_epsg
        )
        
        scene_dir = f'/tmp/{dir_name}/{item.id}'
        if not os.path.exists(scene_dir):
            os.mkdir(scene_dir)

        for s3_href in band_hrefs:
            
            band_name = s3_href.split('/')[-1].split('.')[0]
            band_path = f'{scene_dir}/{band_name}.tif'
            image_paths.append(band_path)
            
            if os.path.exists(band_path):
                continue

            with rasterio.open(s3_href) as s3_src:

                # create window and only read data from the window, rather than entire file
                window = rasterio.windows.from_bounds(
                    bbox_sw_utm.x, bbox_sw_utm.y, 
                    bbox_ne_utm.x, bbox_ne_utm.y, 
                    transform=s3_src.transform
                )

                data = s3_src.read(1, window=window)
                height, width = data.shape[0], data.shape[1]
                print(f'\t{band_name}... rows: {height}, cols: {width}')

                new_transform = rasterio.transform.from_bounds(
                    overlap_sw_utm.x, overlap_sw_utm.y, 
                    overlap_ne_utm.x, overlap_ne_utm.y, 
                    width, height
                )

                kwargs = {
                    "mode": "w",
                    "driver": "GTiff",
                    "height": height,
                    "width": width,
                    "count": 1,
                    "dtype": data.dtype,
                    "crs": s3_src.crs,
                    "transform": new_transform
                }

                kwargs["nodata"] = NODATA_BYTE if band_name == "SCL" else NODATA_UINT16

                # write the S3 data that overlaps with the bbox to file
                with rasterio.open(band_path,  **kwargs) as new_src:
                    new_src.write(data, 1)

                # convert the file to equal area proj and 10 meter resolution
                gdal.Warp(band_path, band_path, dstSRS="EPSG:3857", xRes=10, yRes=10, outputBounds=overlap_poly_ea.bounds)

                # merge the image with the blank TIF with full region bounds
                _merge_image_with_blank(band_path, band_name, bbox_poly_ea, dir_name)
                
    return image_paths
            

def _create_stack(band, dir_name):
    
    masked_paths = glob.glob(f'/tmp/{dir_name}/*/{band}_masked.tif')
    with rasterio.open(masked_paths[0]) as meta_src:
        meta = meta_src.meta.copy()

    meta.update(count=len(masked_paths))

    stack_path = f'/tmp/{dir_name}/{band}_stack.tif'
    with rasterio.open(stack_path, 'w', **meta) as stack_dst:
        for id, layer in enumerate(masked_paths, start=1):
            with rasterio.open(layer) as band_src:
                stack_dst.write_band(id, band_src.read(1))
    

def _create_composite(band, dir_name, method="median"):
    
    stack_path = f'/tmp/{dir_name}/{band}_stack.tif'

    if not os.path.exists(stack_path):
        raise ValueError(f'{stack_path} does not exist')

    with rasterio.open(stack_path) as stack_src:
    
        width, height = stack_src.width, stack_src.height
        composite_path = f'/tmp/{dir_name}/{band}_composite.tif'
        print(composite_path)
        
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


def save_composite_images(collection, bbox, dir_name):
    """
    Downloads, processes and saves analysis ready Sentinel-2 images.
    Arguments:
        start_date: datetime
        end_date: datetime
        bbox: list as [min_lon, min_lat, max_lon, max_lat]
        dir_name: directory in /tmp where images are saved
    Returns:
        Dictionary of band to composite path mappings.
    """

    original_paths = _download_images(collection, bbox, dir_name)

    for path in original_paths:
        apply_cloud_mask(path)

    composite_dict = {}
    for band in S2_BANDS:
        if band == "SCL": continue 

        _create_stack(band, dir_name)
        comp_path = _create_composite(band, dir_name)
        composite_dict[band] = comp_path

    return composite_dict


def save_tif_to_s3(task_uid, tif_path, step):

    file_name = tif_path.split('/')[-1]
    object_key = f'{task_uid}/{step}_{file_name}'
    
    print(f'uploading {tif_path} to s3://{S3_TASKS_BUCKET}/{object_key}')

    s3 = boto3.resource('s3')
    s3.meta.client.upload_file(tif_path, S3_TASKS_BUCKET, object_key)


