from datetime import datetime as dt
from datetime import timedelta as td
from matplotlib import pyplot as plt
import os
import rasterio
from shapely.geometry import shape
import sys

from common import exceptions
from common.constants import DAYS_BUFFER, NODATA_INT8
from common.utilities import api
from common.utilities.download import get_collection, get_processed_imagery
from common.utilities.indices import save_ndvi
from common.utilities.imagery import create_byte_rgb_vrt, create_rgb_map_tiles, save_tif_to_s3, save_photo_to_s3, save_tiles_dir_to_s3
from common.utilities.prediction import save_forest_classification, save_forest_change



def _plot_and_save(data, image_path, task_uid, step):
    plt.imshow(data, cmap="RdYlGn")
    plt.savefig(image_path)
    plt.clf()
    save_photo_to_s3(task_uid, image_path, step)


def handle():

    print(sys.argv)
    #task_uid = sys.argv[1]
    #task_type = sys.argv[2]

    task_uid = "c65c1f3a-ff8d-4c80-be9f-04355de64fa4"
    task_type = "forest_change"

    print("task_uid:", task_uid)
    print("task_type:", task_type)

    api.update_task_status(task_uid, task_type, "running")

    if task_type == "forest_change":

        # prepare directories

        os.makedirs('/tmp/before', exist_ok=True)
        os.makedirs('/tmp/after', exist_ok=True)
        os.makedirs('/tmp/results', exist_ok=True)


        # prepare parameters

        params = api.get_forest_change_task_params(task_uid)

        start_date_end = dt.strptime(params['start_date'], '%Y-%m-%d')
        start_date_begin = start_date_end - td(days=DAYS_BUFFER)

        end_date_end = dt.strptime(params['end_date'], '%Y-%m-%d')
        end_date_begin = end_date_end - td(days=DAYS_BUFFER)

        geojson = params['region']['geojson']
        if geojson['type'] == 'FeatureCollection':
            region = shape(geojson['features'][0]['geometry'])
        elif geojson['type'] == 'Polygon':
            region = shape(geojson)
        else:
            raise ValueError("invalid geojson type") # TODO: figure out proper logging!

        bbox = region.bounds

        print("bbox:", bbox)


        # get collections

        try:
            start_collection = get_collection(start_date_begin, start_date_end, bbox, "before", max_cloud_cover=20)
        except exceptions.EmptyCollectionException:
            print("before collection is empty")
            api.update_task_status(task_uid, task_type, "failed")
            return

        try:
            after_collection = get_collection(end_date_begin, end_date_end, bbox, "after", max_cloud_cover=24)
        except exceptions.EmptyCollectionException:
            print("after collection is empty")
            api.update_task_status(task_uid, task_type, "failed")
            return 

        
        # get imagery and create map tiles

        before_dict = get_processed_imagery(start_collection, bbox, "before")
        before_rgb_vrt_path = create_byte_rgb_vrt(before_dict, "before")
        before_tiles_dir = create_rgb_map_tiles(before_rgb_vrt_path, "before")

        after_dict = get_processed_imagery(after_collection, bbox, "after")
        after_rgb_vrt_path = create_byte_rgb_vrt(after_dict, "after")
        after_tiles_dir = create_rgb_map_tiles(after_rgb_vrt_path, "after")


        # upload images and tiles

        save_tiles_dir_to_s3(task_uid, before_tiles_dir, 'before')
        save_tiles_dir_to_s3(task_uid, after_tiles_dir, 'after')

        for band in before_dict:
            save_tif_to_s3(task_uid, before_dict[band], "before")
            save_tif_to_s3(task_uid, after_dict[band], "after")

        # save NDVI

        before_ndvi_path = save_ndvi(before_dict['B04'], before_dict['B08'], "before")
        after_ndvi_path = save_ndvi(after_dict['B04'], after_dict['B08'], "after")

        save_tif_to_s3(task_uid, before_ndvi_path, "before")
        save_tif_to_s3(task_uid, after_ndvi_path, "after")

        before_dict["NDVI"] = before_ndvi_path
        after_dict["NDVI"] = after_ndvi_path

        # "classify" imagery

        before_pred_path = save_forest_classification(before_dict, "before")
        with rasterio.open(before_pred_path) as forest_src:
            before_forest = forest_src.read(1, masked=True)

        _plot_and_save(before_forest, '/tmp/before/forest.png', task_uid, "before")

    
        after_pred_path = save_forest_classification(after_dict, "after")
        with rasterio.open(after_pred_path) as forest_src:
            after_forest = forest_src.read(1, masked=True)

        _plot_and_save(after_forest, '/tmp/after/forest.png', task_uid, "after")


        change_path = save_forest_change(before_pred_path, after_pred_path)
        with rasterio.open(change_path) as change_src:
            change = change_src.read(1, masked=True)

        _plot_and_save(change, '/tmp/results/change.png', task_uid, "results")

        # update results

        api.update_forest_change_task_results(task_uid, 100, 80, 520)


    elif task_type == "burn_areas":
        pass

    elif task_type == "lulc_change":
        pass

    else:
        raise ValueError()


    # update status

    api.update_task_status(task_uid, task_type, "complete")



if __name__ == "__main__":
    handle()

