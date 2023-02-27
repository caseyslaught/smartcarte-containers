from datetime import datetime as dt
from datetime import timedelta as td
import os
from shapely.geometry import shape

from common.exceptions import EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException
from common.constants import DAYS_BUFFER, MAX_CLOUD_COVER
from common.utilities.api import get_forest_change_task_params, update_task_status, update_forest_change_task
from common.utilities.download import get_collection, get_processed_composite
from common.utilities.imagery import create_map_tiles, create_rgb_byte_tif_from_composite
from common.utilities.prediction import predict_forest, predict_forest_change
from common.utilities.upload import get_tiles_cdn_url, save_task_file_to_s3, save_task_tiles_to_s3
from common.utilities.visualization import plot_tif


CLOUD_DETECTION_MODEL_PATH = "./common/models/best_resnet18_dice_cloud_detection.pth"


def handle():

    task_uid = os.environ['TASK_UID']
    task_type = os.environ['TASK_TYPE']
    tile_max_zoom = 14

    base_dir = f"/tmp/{task_uid}"

    print("task_uid:", task_uid)
    print("task_type:", task_type)

    update_task_status(task_uid, task_type, "running")

    if task_type == "forest_change":

        ### prepare directories ###

        os.makedirs(f'{base_dir}/before', exist_ok=True)
        os.makedirs(f'{base_dir}/after', exist_ok=True)
        os.makedirs(f'{base_dir}/results', exist_ok=True)

        ### prepare parameters ###

        params = get_forest_change_task_params(task_uid)

        before_date_end = dt.strptime(params['start_date'], '%Y-%m-%d')
        before_date_begin = before_date_end - td(days=DAYS_BUFFER)

        after_date_end = dt.strptime(params['end_date'], '%Y-%m-%d')
        after_date_begin = after_date_end - td(days=DAYS_BUFFER)

        geojson = params['region']['geojson']
        if geojson['type'] == 'FeatureCollection':
            region = shape(geojson['features'][0]['geometry'])
        elif geojson['type'] == 'Polygon':
            region = shape(geojson)
        else:
            raise ValueError("invalid geojson type") # TODO: figure out proper logging!

        bbox = region.bounds
        print("bbox:", bbox)


        ### get collections ###         

        # loop through cloud cover until we get a complete collection
        before_cloud_cover = 5
        while True:

            try:
                before_collection = get_collection(
                    before_date_begin,  before_date_end, 
                    bbox, f'{base_dir}/before/s2_collection.json', 
                    max_cloud_cover=before_cloud_cover)
            except (EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException) as e:
                print(e)
                if before_cloud_cover >= MAX_CLOUD_COVER:
                    update_task_status(task_uid, task_type, "failed", "Not enough cloud-free imagery around start date.")
                    return
                else:
                    before_cloud_cover += 10
            else:
                break

        after_cloud_cover = 5
        while True:
            try:
                after_collection = get_collection(
                    after_date_begin, after_date_end, 
                    bbox, f'{base_dir}/after/s2_collection.json', 
                    max_cloud_cover=after_cloud_cover)
            except (EmptyCollectionException, IncompleteCoverageException, NotEnoughItemsException) as e:
                print(e)
                if after_cloud_cover >= MAX_CLOUD_COVER:
                    update_task_status(task_uid, task_type, "failed", "Not enough cloud-free imagery around end date.")
                    return
                else:
                    after_cloud_cover += 10
            else:
                break


        ### prepare imagery ###

        before_dir = f'{base_dir}/before'
        after_dir = f'{base_dir}/after'
        results_dir = f'{base_dir}/results'

        # before

        before_composite_path = get_processed_composite(before_collection, bbox, before_dir, CLOUD_DETECTION_MODEL_PATH)

        before_rgb_path = f'{before_dir}/rgb_byte.tif'
        create_rgb_byte_tif_from_composite(before_composite_path, before_rgb_path, is_cog=True)
        
        before_tiles_dir = f'{before_dir}/rgb_byte_tiles'
        create_map_tiles(before_rgb_path, before_tiles_dir, max_zoom=tile_max_zoom)

        # after

        after_composite_path = get_processed_composite(after_collection, bbox, after_dir, CLOUD_DETECTION_MODEL_PATH)

        after_rgb_path = f'{after_dir}/rgb_byte.tif'
        create_rgb_byte_tif_from_composite(after_composite_path, after_rgb_path, is_cog=True)
        
        after_tiles_dir = f'{after_dir}/rgb_byte_tiles'
        create_map_tiles(after_rgb_path, after_tiles_dir, max_zoom=tile_max_zoom)


        ### upload assets to S3 ###

        save_task_file_to_s3(before_rgb_path, "before", task_uid)
        save_task_file_to_s3(after_rgb_path, "after", task_uid)

        save_task_file_to_s3(before_composite_path, "before", task_uid)
        save_task_file_to_s3(after_composite_path, "after", task_uid)

        before_tiles_s3_dir = save_task_tiles_to_s3(before_tiles_dir, "before", task_uid)
        after_tiles_s3_dir = save_task_tiles_to_s3(after_tiles_dir, "after", task_uid)


        ### model predictions ###

        before_prediction_path = f'{before_dir}/forest.tif'
        predict_forest(before_composite_path, before_prediction_path)

        after_prediction_path = f'{after_dir}/forest.tif'
        predict_forest(after_composite_path, after_prediction_path)

        change_path = f'{results_dir}/change.tif'
        predict_forest_change(before_prediction_path, after_prediction_path, change_path)

        change_tiles_dir = f'{results_dir}/change_tiles'
        create_map_tiles(change_path, change_tiles_dir)
      

        ### produce visualizations ###

        before_rgb_plot = f'{before_dir}/rgb.png'
        plot_tif(before_rgb_path, before_rgb_plot, bands=[1, 2, 3], cmap=None)

        after_rgb_plot = f'{after_dir}/rgb.png'
        plot_tif(after_rgb_path, after_rgb_plot, bands=[1, 2, 3], cmap=None)

        before_prediction_plot = f'{before_dir}/forest.png'
        plot_tif(before_prediction_path, before_prediction_plot, bands=1, cmap='RdYlGn')

        after_prediction_plot = f'{after_dir}/forest.png'
        plot_tif(after_prediction_path, after_prediction_plot, bands=1, cmap='RdYlGn')

        change_plot = f'{results_dir}/change.png'
        plot_tif(change_path, change_plot, bands=1, cmap='RdYlGn')


        ### upload results assets to S3 ###

        save_task_file_to_s3(before_rgb_plot, "before", task_uid)
        save_task_file_to_s3(after_rgb_plot, "after", task_uid)

        save_task_file_to_s3(before_prediction_plot, "before", task_uid)
        save_task_file_to_s3(after_prediction_plot, "after", task_uid)

        save_task_file_to_s3(change_plot, "results", task_uid)
        save_task_file_to_s3(change_path, "results", task_uid)
        change_tiles_s3_dir = save_task_tiles_to_s3(change_tiles_dir, "results", task_uid)


        ### update task in database ###

        update_forest_change_task(
            task_uid,
            gain_area=100,
            loss_area=80,
            total_area=520,
            before_rgb_tiles_href=get_tiles_cdn_url(before_tiles_s3_dir),
            after_rgb_tiles_href=get_tiles_cdn_url(after_tiles_s3_dir),
            change_tiles_href=get_tiles_cdn_url(change_tiles_s3_dir),
        )


    elif task_type == "burn_areas":
        pass

    elif task_type == "lulc_change":
        pass

    else:
        raise ValueError()


    # update status

    update_task_status(task_uid, task_type, "complete")
    print("complete")


if __name__ == "__main__":
    handle()
