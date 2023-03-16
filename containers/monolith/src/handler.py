from datetime import datetime as dt
from datetime import timedelta as td
import json
import os
import random
from shapely.geometry import shape

from common.exceptions import EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException
from common.constants import DAYS_BUFFER, MAX_CLOUD_COVER
from common.utilities.api import get_demo_classification_task, update_demo_classification_task, update_task_status
from common.utilities.download import get_collection, get_processed_composite
from common.utilities.imagery import create_map_tiles, create_rgb_byte_tif_from_composite
from common.utilities.upload import get_file_cdn_url, get_tiles_cdn_url, save_task_file_to_s3, save_task_tiles_to_s3
from common.utilities.visualization import plot_tif


CLOUD_DETECTION_MODEL_PATH = "./common/models/cloud_detection_model_resnet18_dice_20230301.pth"


def handle():

    task_uid = os.environ['TASK_UID'].strip()
    task_type = os.environ['TASK_TYPE'].strip()

    base_dir = f"/tmp/{task_uid}"

    print("task_uid:", task_uid)
    print("task_type:", task_type)
    
    update_task_status(task_uid, task_type, "running", "Fetching imagery")

    if task_type == "demo_classification":

        ### prepare parameters ###

        params = get_demo_classification_task(task_uid)

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
            raise ValueError("invalid geojson type") # TODO: figure out proper logging!

        bbox = region.bounds
        print("bbox:", bbox)


        ### get collections ###         

        # incrementally increase cloud_cover until we get a complete collection
        cloud_cover = 5
        while True:

            try:
                collection_path = f'{base_dir}/before/s2_collection.json'
                collection = get_collection(
                    date_start, 
                    date_end, 
                    bbox, 
                    collection_path, 
                    max_cloud_cover=cloud_cover, 
                    max_tile_count=4, 
                    min_tile_count=3
                )
            except (EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException) as e:
                print(e)
                if cloud_cover >= MAX_CLOUD_COVER:
                    update_task_status(task_uid, task_type, "failed", "Task failed", "There are not enough valid images for the selected date and region. This usually occurs when there is excessive cloud cover. Please try again with a different date or region.")
                    return
                else:
                    cloud_cover += 20
            else:
                break

        ### prepare imagery ###

        update_task_status(task_uid, task_type, "running", "Processing imagery")

        composite_path = get_processed_composite(collection, bbox, base_dir, CLOUD_DETECTION_MODEL_PATH)

        rgb_path = f'{base_dir}/rgb_byte.tif'
        create_rgb_byte_tif_from_composite(composite_path, rgb_path, is_cog=True)
        
        tiles_dir = f'{base_dir}/rgb_byte_tiles'
        create_map_tiles(rgb_path, tiles_dir, max_zoom=14)

        rgb_plot = f'{base_dir}/rgb.png'
        plot_tif(rgb_path, rgb_plot, bands=[1, 2, 3], cmap=None)


        ### upload assets to S3 ###

        update_task_status(task_uid, task_type, "running", "Uploading assets")

        save_task_file_to_s3(rgb_plot, task_uid) # for debugging purposes
        rgb_object_key = save_task_file_to_s3(rgb_path, task_uid)
        composite_object_key = save_task_file_to_s3(composite_path, task_uid)
        tiles_s3_dir = save_task_tiles_to_s3(tiles_dir, task_uid)


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
            task_uid=task_uid,
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

    update_task_status(task_uid, task_type, "complete", "Task complete")
    print("complete")


if __name__ == "__main__":
    handle()
