import numpy as np
import os
from osgeo import gdal, osr
from pystac import ItemCollection
from pystac_client import Client
import rasterio
import rasterio.merge
from shapely.geometry import box, shape, Point

from src.common.utilities.projections import reproject_shape

BLANK_TIF_PATH = '/tmp/blank.tif'

S2_BANDS = ['SCL', 'B02', 'B03', 'B04', 'B08'] # make sure SCL first
NODATA_UINT16 = 65535
NODATA_BYTE = 255


def _get_collection(start_date, end_date, bbox, max_cloud_cover=10):
    """
    Gets a STAC collection
    Arguments:
        start_date: datetime
        end_date: datetime
        bbox: list as [min_lon, min_lat, max_lon, max_lat]
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

    print(f"{search.matched()} items found")

    # limit number of images per Sentinel grid square
    limit = 8
    items, items_count = [], {}
    for item in list(search.items()):
        square = item.properties['sentinel:grid_square']
        count = items_count.get(square, 0)
        if count < limit:
            items.append(item)
            items_count[square] = count + 1

    print(f'{len(items)} filtered items')
            
    collection = ItemCollection(items=items)
    collection.save_object('/tmp/s2_collection.json')

    return collection


def _create_blank_tif(bbox_poly_ea):
    """
    Creates a blank TIF with bounds that match the bbox
    Arguments:
        bbox_poly_ea: bbox Polygon object in equal-area projection
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

    outfn = BLANK_TIF_PATH
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




def _create_composite(imagesList, method="median"):
    """
    """
    pass


def _download_images(collection, bbox):

    bbox_poly_ll = box(*bbox)
    bbox_poly_ea = reproject_shape(bbox_poly_ll, "EPSG:4326", "EPSG:3857")

    _create_blank_tif(bbox_poly_ea)

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
        
        scene_dir = f'/tmp/{item.id}'
        if not os.path.exists(scene_dir):
            os.mkdir(scene_dir)

        for s3_href in band_hrefs:
            
            band_name = s3_href.split('/')[-1].split('.')[0]
            band_path = f'{scene_dir}/{band_name}.tif'
            
            #if os.path.exists(band_path):
            #    continue

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

                if band_name == "SCL":
                    kwargs["nodata"] = NODATA_BYTE
                else:
                    kwargs["nodata"] = NODATA_UINT16

                # write the S3 data that overlaps with the bbox to file
                with rasterio.open(band_path,  **kwargs) as new_src:
                    new_src.write(data, 1)

                # convert the file to equal area proj and 10 meter resolution
                gdal.Warp(band_path, band_path, dstSRS="EPSG:3857", xRes=10, yRes=10, outputBounds=overlap_poly_ea.bounds)

                # merge data with blank raster so that all files have same bounds (facilitates making composite)       
                with rasterio.open(BLANK_TIF_PATH) as temp_src:
                    
                    with rasterio.open(band_path) as data_src:
                        
                        # if the bounds are the same then just skip merging
                        tbnds, dbnds = temp_src.bounds, data_src.bounds
                        if tbnds.left == dbnds.left and tbnds.bottom == dbnds.bottom and \
                        tbnds.right == dbnds.right and tbnds.top == dbnds.top:
                            continue

                        merged, transform_ = rasterio.merge.merge([data_src, temp_src], bounds=bbox_poly_ea.bounds)
                        merged = merged[0, :, :]

                        merged_profile = temp_src.profile.copy()
                        if band_name == "SCL":
                            merged_profile["dtype"] = "uint8"
                            merged_profile["nodata"] = NODATA_BYTE

                with rasterio.open(band_path, "w", **merged_profile) as new_src:
                    new_src.write(merged, 1)
            

def get_processed_image_array(start_date, end_date, bbox):
    """
    Downloads, processes and returns analysis ready Sentinel-2 image array
    Arguments:
        start_date: datetime
        end_date: datetime
        bbox: list as [min_lon, min_lat, max_lon, max_lat]
    Returns:
        N-dimensional DataArray
    """

    collection = _get_collection(start_date, end_date, bbox)

    _download_images(collection, bbox)




from datetime import datetime as dt

def _debug():

    start_date = dt(2021, 8, 1, 1)
    end_date = dt(2021, 10, 1, 1)
    bbox = [29.270558, -1.648015, 29.705426, -1.311937]

    print(bbox)

    get_processed_image_array(start_date, end_date, bbox)
