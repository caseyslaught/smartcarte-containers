from datetime import datetime as dt
from datetime import timedelta as td
import json
import os
import random
import sentry_sdk
from shapely.geometry import shape

from common.exceptions import EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException
from common.constants import DAYS_BUFFER, MAX_CLOUD_COVER
from common.utilities.api import get_demo_classification_task, update_demo_classification_task, update_task_status
from common.utilities.download import get_collection, get_processed_composite
from common.utilities.imagery import create_map_tiles, create_rgb_byte_tif_from_composite
from common.utilities.projections import reproject_shape
from common.utilities.upload import get_file_cdn_url, get_tiles_cdn_url, save_task_file_to_s3, save_task_tiles_to_s3
from common.utilities.visualization import plot_tif


CLOUD_DETECTION_MODEL_PATH = "./common/models/cloud_detection_model_resnet18_dice_20230324.pth"

MAX_TILES = 8
MIN_TILES = 5
TILE_ZOOM = 14

sentry_sdk.init(
    dsn=f"https://c2321cc79562459cb4cfd3d33ac91d3d@o4504860083224576.ingest.sentry.io/{os.environ['SENTRY_MONOLITH_PROJECT_ID']}",
    traces_sample_rate=0.2
)

TASK_UID = os.environ['TASK_UID'].strip()
TASK_TYPE = os.environ['TASK_TYPE'].strip()


def handle():

    base_dir = f"/tmp/{TASK_UID}"

    print("TASK_UID:", TASK_UID)
    print("TASK_TYPE:", TASK_TYPE)
    
    update_task_status(TASK_UID, TASK_TYPE, "running", "Fetching imagery")

    if TASK_TYPE == "demo_classification":

        ### prepare parameters ###

        params = get_demo_classification_task(TASK_UID)

        date_end = dt.strptime(params['date'], '%Y-%m-%d')
        date_start = date_end - td(days=DAYS_BUFFER)

        geojson = params['region_geojson']
        if geojson['type'] == 'FeatureCollection':
            region = shape(geojson['features'][0]['geometry'])
        elif geojson['type'] == 'Feature':
            region = shape(geojson['geometry'])
        elif geojson['type'] == 'Polygon':
            region = shape(geojson)
        else:
            raise Exception("invalid geojson type")

        bbox = region.bounds
        print("bbox:", bbox)


        ### intro logging ###

        region_ea = reproject_shape(region, "EPSG:4326", "EPSG:3857")
        region_area_km2 = round(region_ea.area / 1000000, 2)
        intro_message = f'task_uid: {TASK_UID}, area: {region_area_km2} km2, dates: {date_start} to {date_end}'
        sentry_sdk.capture_message(intro_message, "info")
        
        
        ### get collections ###         

        # incrementally increase cloud_cover until we get a complete collection
        cloud_cover = 10
        while True:
            try:
                collection_path = f'{base_dir}/s2_collection.json'
                collection = get_collection(
                    date_start, 
                    date_end, 
                    bbox, 
                    collection_path, 
                    max_cloud_cover=cloud_cover, 
                    max_tile_count=MAX_TILES,
                    min_tile_count=MIN_TILES,
                )
            except (EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException) as e:
                print(e)
                if cloud_cover >= MAX_CLOUD_COVER:
                    update_task_status(TASK_UID, TASK_TYPE, "failed", "Task failed", "There are not enough valid images for the selected date and region. This usually occurs when there is excessive cloud cover. Please try again with a different date or region.")
                    return
                else:
                    cloud_cover += 20
            else:
                break

        ### prepare imagery ###

        update_task_status(TASK_UID, TASK_TYPE, "running", "Processing imagery")

        try:
            composite_path = get_processed_composite(collection, bbox, base_dir, CLOUD_DETECTION_MODEL_PATH)
        except NotEnoughItemsException as e:
            print(e)
            update_task_status(TASK_UID, TASK_TYPE, "failed", "Task failed", "There are not enough valid images for the selected date and region. This usually occurs when there is excessive cloud cover. Please try again with a different date or region.")
            return

        rgb_path = f'{base_dir}/rgb_byte.tif'
        create_rgb_byte_tif_from_composite(composite_path, rgb_path, is_cog=True, use_alpha=False)

        rgba_path = f'{base_dir}/rgba_byte.tif'
        create_rgb_byte_tif_from_composite(composite_path, rgba_path, is_cog=True, use_alpha=True)
        
        tiles_dir = f'{base_dir}/rgb_byte_tiles'
        create_map_tiles(rgba_path, tiles_dir, max_zoom=TILE_ZOOM)

        rgb_plot = f'{base_dir}/rgb.png'
        plot_tif(rgb_path, rgb_plot, bands=[1, 2, 3], cmap=None)


        ### upload assets to S3 ###

        update_task_status(TASK_UID, TASK_TYPE, "running", "Uploading assets")

        save_task_file_to_s3(rgb_plot, TASK_UID) # for debugging purposes
        rgb_object_key = save_task_file_to_s3(rgb_path, TASK_UID)
        composite_object_key = save_task_file_to_s3(composite_path, TASK_UID)
        tiles_s3_dir = save_task_tiles_to_s3(tiles_dir, TASK_UID)


        ### model predictions ###

        classes = ["agriculture", "bare_ground", "built", "burned", "semi_natural_vegetation", "trees", "water"]
        statistics = {
            lulc_class: {
                "area_ha": random.randint(0, 100),
                "percent_total": random.randint(0, 100),
                "percent_masked": random.randint(0, 100)
            }
            for lulc_class in classes
        }

        ### upload results assets to S3 ###

        ### update task in database ###

        imagery_tif_href = get_file_cdn_url(composite_object_key)
        imagery_tiles_href = get_tiles_cdn_url(tiles_s3_dir)
        rgb_tif_href = get_file_cdn_url(rgb_object_key)

        print(imagery_tif_href)
        print(imagery_tiles_href)
        print(rgb_tif_href)

        update_demo_classification_task(
            task_uid=TASK_UID,
            statistics_json=json.dumps(statistics),
            imagery_tif_href=imagery_tif_href,
            imagery_tiles_href=imagery_tiles_href,
            # landcover_tif_href=get_file_cdn_url(landcover_object_key),
            # landcover_tiles_href=get_tiles_cdn_url(landcover_tiles_s3_dir),
            rgb_tif_href=rgb_tif_href,
        )

    else:
        raise ValueError()

    ### update status ###

    update_task_status(TASK_UID, TASK_TYPE, "complete", "Task complete")
    print("complete")


if __name__ == "__main__":
    try:
        handle()
    except Exception as e:
        print(e)
        update_task_status(TASK_UID, TASK_TYPE, "failed", "Task failed", "An unexpected error occurred. Please try again later.")
        sentry_sdk.capture_exception(e)


