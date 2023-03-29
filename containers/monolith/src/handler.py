from datetime import datetime as dt
from datetime import timedelta as td
import json
import os
import sentry_sdk
from shapely.geometry import shape
import time

from common.exceptions import EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException
from common.constants import DAYS_BUFFER, MAX_CLOUD_COVER
from common.utilities.api import get_demo_classification_task, update_demo_classification_task, update_task_status
from common.utilities.download import get_collection, get_processed_composite
from common.utilities.email import send_success_email
from common.utilities.imagery import create_map_tiles, create_rgb_byte_tif_from_composite, create_rgb_byte_tif_from_landcover
from common.utilities.prediction import apply_landcover_classification, calculate_landcover_statistics
from common.utilities.projections import reproject_shape
from common.utilities.upload import get_file_cdn_url, get_tiles_cdn_url, save_task_file_to_s3, save_task_tiles_to_s3
from common.utilities.visualization import plot_tif


CLOUD_DETECTION_MODEL_PATH = "./common/models/cloud_detection_model_resnet18_dice_20230327.pth"
LANDCOVER_CLASSIFICATION_MODEL_PATH = "./common/models/landcover_classification_model_resnet18_dice_20230328.pth"

MAX_TILES = 3
MIN_TILES = 2
TILE_ZOOM = 14

sentry_sdk.init(
    dsn=f"https://c2321cc79562459cb4cfd3d33ac91d3d@o4504860083224576.ingest.sentry.io/{os.environ['SENTRY_MONOLITH_PROJECT_ID']}",
    traces_sample_rate=1.0,
    _experiments={
        "profiles_sample_rate": 1.0,
    }
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

        recipient_email = params['email']

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
        intro_message = f'intro - task_uid: {TASK_UID}\ndates: {date_start} to {date_end}\narea: {region_area_km2} km2'
        sentry_sdk.capture_message(intro_message, "info")
        print(intro_message)

        
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


        ### model predictions ###
        
        landcover_path = f'{base_dir}/landcover.tif'
        apply_landcover_classification(composite_path, landcover_path, LANDCOVER_CLASSIFICATION_MODEL_PATH)

        statistics = calculate_landcover_statistics(landcover_path)

        landcover_rgb_path = f'{base_dir}/landcover_rgb_byte.tif'
        create_rgb_byte_tif_from_landcover(landcover_path, landcover_rgb_path, is_cog=True, use_alpha=False)

        landcover_rgba_path = f'{base_dir}/landcover_rgba_byte.tif'
        create_rgb_byte_tif_from_landcover(landcover_path, landcover_rgba_path, is_cog=True, use_alpha=True)

        landcover_tiles_dir = f'{base_dir}/landcover_rgb_byte_tiles'
        create_map_tiles(landcover_rgba_path, landcover_tiles_dir, max_zoom=TILE_ZOOM)

        landcover_rgb_plot = f'{base_dir}/landcover.png'
        plot_tif(landcover_rgb_path, landcover_rgb_plot, bands=[1, 2, 3], cmap=None)
        

        ### upload assets to S3 ###

        update_task_status(TASK_UID, TASK_TYPE, "running", "Uploading assets")

        # imagery
        save_task_file_to_s3(rgb_plot, TASK_UID) # for debugging purposes
        rgb_object_key = save_task_file_to_s3(rgb_path, TASK_UID)
        composite_object_key = save_task_file_to_s3(composite_path, TASK_UID)
        tiles_s3_dir = save_task_tiles_to_s3(tiles_dir, TASK_UID)

        # landcover
        save_task_file_to_s3(landcover_rgb_plot, TASK_UID)
        landcover_rgb_object_key = save_task_file_to_s3(landcover_rgb_path, TASK_UID)
        landcover_tiles_s3_dir = save_task_tiles_to_s3(landcover_tiles_dir, TASK_UID)


        ### update task in database ###

        rgb_tif_href = get_file_cdn_url(rgb_object_key)
        imagery_tif_href = get_file_cdn_url(composite_object_key)
        imagery_tiles_href = get_tiles_cdn_url(tiles_s3_dir)

        landcover_tiles_href = get_tiles_cdn_url(landcover_tiles_s3_dir)
        landcover_rgb_tif_href = get_file_cdn_url(landcover_rgb_object_key)
        
        print(rgb_tif_href)
        print(imagery_tif_href)
        print(imagery_tiles_href)
        print(landcover_tiles_href)
        print(landcover_rgb_tif_href)


        update_demo_classification_task(
            task_uid=TASK_UID,
            statistics_json=json.dumps(statistics),
            imagery_tif_href=imagery_tif_href,
            imagery_tiles_href=imagery_tiles_href,
            landcover_tif_href=landcover_rgb_tif_href,
            landcover_tiles_href=landcover_tiles_href,
            rgb_tif_href=rgb_tif_href,
        )

        ### send email ###

        send_success_email(TASK_UID, date_start, date_end, region_area_km2, recipient_email)

    else:
        raise Exception("invalid task type")

    ### update status ###

    update_task_status(TASK_UID, TASK_TYPE, "complete", "Task complete")
    print("complete")


if __name__ == "__main__":

    sentry_sdk.set_tag("task_uid", TASK_UID)

    try:
        start_time = time.time()
        handle()
    except Exception as e:
        print(e)
        update_task_status(TASK_UID, TASK_TYPE, "failed", "Task failed", "An unexpected error occurred. Please try again later.")
        sentry_sdk.capture_exception(e)
    else:
        end_time = time.time()
        elapsed_time = end_time - start_time
        complete_message = f'complete - task_uid: {TASK_UID}\nelapsed time: {elapsed_time:.2f} seconds'
        sentry_sdk.capture_message(complete_message, "info")
        print(complete_message)
