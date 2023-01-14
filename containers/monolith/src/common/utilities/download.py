import os
from osgeo import gdal
from pystac import ItemCollection
from pystac_client import Client
import rasterio
import rasterio.merge
from shapely.geometry import box, shape, Point

from common import exceptions
from common.constants import NODATA_BYTE, NODATA_UINT16, S2_BANDS
from common.utilities.imagery import create_blank_tif, create_composite, create_stack, merge_image_with_blank
from common.utilities.masking import save_cloud_masked_images
from common.utilities.projections import get_collection_bbox_coverage, reproject_shape




def get_collection(start_date, end_date, bbox, step, max_cloud_cover=20):
    """
    Gets a STAC collection
    Arguments:
        start_date: datetime
        end_date: datetime
        bbox: list as [min_lon, min_lat, max_lon, max_lat]
        step: directory name in /tmp where data is saved
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

    print(f"{step}: {search.matched()} items found")

    # limit number of images per Sentinel grid square
    limit = 8
    items, items_count = [], {}
    for item in list(search.items()):
        square = item.properties['sentinel:grid_square']
        count = items_count.get(square, 0)
        if count < limit:
            items.append(item)
            items_count[square] = count + 1

    print(f'{step}: {len(items)} filtered items')

    collection = ItemCollection(items=items)

    if len(items) == 0:
        raise exceptions.EmptyCollectionException()

    if get_collection_bbox_coverage(collection, bbox) < 100:
        raise exceptions.IncompleteCoverageException()

    collection.save_object(f'/tmp/{step}/s2_collection.json')
    return collection


def get_processed_imagery(collection, bbox, step):
    """
    Downloads, processes and saves analysis ready Sentinel-2 images.
    Arguments:
        start_date: datetime
        end_date: datetime
        bbox: list as [min_lon, min_lat, max_lon, max_lat]
        step: directory in /tmp where images are saved
    Returns:
        Dictionary of band to composite path mappings.
    """

    original_scenes_dict = _download_original_imagery(collection, bbox, step)

    masked_scenes_dict = {}
    for scene in original_scenes_dict:
        masked_scenes_dict[scene] = save_cloud_masked_images(original_scenes_dict[scene])

    composite_dict = {}
    for band in S2_BANDS:
        if band == "SCL": continue 

        stack_path = create_stack(band, step)
        composite_path = create_composite(band, stack_path, step)
        composite_dict[band] = composite_path

    return composite_dict


### helper functions

def _download_original_imagery(collection, bbox, dir_name):

    bbox_poly_ll = box(*bbox)
    bbox_poly_ea = reproject_shape(bbox_poly_ll, "EPSG:4326", "EPSG:3857")

    create_blank_tif(bbox_poly_ea, dir_name)

    scenes_dict = {}
    for item in list(collection):
        print(f'\t{item.id}')
        scenes_dict[item.id] = {}

        band_hrefs = [item.assets[band].href for band in S2_BANDS]
        
        # reproject bbox into projection of S2 item 
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

            scenes_dict[item.id][band_name] = band_path

            if os.path.exists(band_path):
                continue

            with rasterio.open(s3_href) as s3_src:

                # create window and only read data from the window, rather than entire file
                window = rasterio.windows.from_bounds(
                    bbox_sw_utm.x, bbox_sw_utm.y, 
                    bbox_ne_utm.x, bbox_ne_utm.y, 
                    transform=s3_src.transform
                )

                s3_data = s3_src.read(1, window=window)
                height, width = s3_data.shape[0], s3_data.shape[1]

                new_transform = rasterio.transform.from_bounds(
                    overlap_sw_utm.x, overlap_sw_utm.y, 
                    overlap_ne_utm.x, overlap_ne_utm.y, 
                    width, height
                )

                kwargs = {
                    "driver": "GTiff",
                    "height": height,
                    "width": width,
                    "count": 1,
                    "dtype": s3_data.dtype,
                    "crs": s3_src.crs,
                    "transform": new_transform
                }

                kwargs["nodata"] = NODATA_BYTE if band_name == "SCL" else NODATA_UINT16

                with rasterio.open(band_path, "w", **kwargs) as new_src:
                    new_src.write(s3_data, 1)

                gdal.Warp(band_path, band_path, dstSRS="EPSG:3857", xRes=10, yRes=10, outputBounds=overlap_poly_ea.bounds)
                
                merge_image_with_blank(band_path, band_name, bbox_poly_ea, dir_name)


    return scenes_dict
            



