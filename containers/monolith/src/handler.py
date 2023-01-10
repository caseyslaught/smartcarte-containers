from datetime import datetime as dt
from datetime import timedelta as td
import rasterio
from shapely.geometry import shape
import sys

from common import exceptions
from common.constants import DAYS_BUFFER, NODATA_INT8
from common.utilities import api
from common.utilities.indices import save_ndvi
from common.utilities.imagery import save_composite_images, get_collection, save_tif_to_s3
from common.utilities.prediction import save_forest_classification, save_forest_change


def _debug():

    task_uid = "c65c1f3a-ff8d-4c80-be9f-04355de64fa4" 
    task_type = "forest_change"

    api.update_task_status(task_uid, task_type, "running")

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

    before_collection = get_collection(start_date_begin, start_date_end, bbox, "before", max_cloud_cover=4)
    after_collection = get_collection(end_date_begin, end_date_end, bbox, "after", max_cloud_cover=24)

    before_dict = save_composite_images(before_collection, bbox, "before")
    after_dict = save_composite_images(after_collection, bbox, "after")

    before_ndvi_path = save_ndvi(before_dict['B04'], before_dict['B08'], "before")
    after_ndvi_path = save_ndvi(after_dict['B04'], after_dict['B08'], "after")
    save_tif_to_s3(task_uid, before_ndvi_path, "before")
    save_tif_to_s3(task_uid, after_ndvi_path, "after")




from matplotlib import pyplot as plt
import numpy as np

def _forest():

    task_uid = "c65c1f3a-ff8d-4c80-be9f-04355de64fa4" 

    before_dict = {
        "B02": "/tmp/before/B02_composite.tif",
        "B03": "/tmp/before/B03_composite.tif",
        "B04": "/tmp/before/B04_composite.tif",
        "B08": "/tmp/before/B08_composite.tif",
        "NDVI": "/tmp/before/ndvi.tif",
    }

    after_dict = {
        "B02": "/tmp/after/B02_composite.tif",
        "B03": "/tmp/after/B03_composite.tif",
        "B04": "/tmp/after/B04_composite.tif",
        "B08": "/tmp/after/B08_composite.tif",
        "NDVI": "/tmp/after/ndvi.tif",
    }

    before_ndvi_path = save_ndvi(before_dict['B04'], before_dict['B08'], "before")
    after_ndvi_path = save_ndvi(after_dict['B04'], after_dict['B08'], "after")
    # save_tif_to_s3(task_uid, before_ndvi_path, "before")
    # save_tif_to_s3(task_uid, after_ndvi_path, "after")

    before_pred_path = save_forest_classification(before_dict, "before")
    with rasterio.open(before_pred_path) as before_forest_src:
        before_forest = before_forest_src.read(1, masked=True)

    after_pred_path = save_forest_classification(after_dict, "after")
    with rasterio.open(after_pred_path) as after_forest_src:
        after_forest = after_forest_src.read(1, masked=True)
    
    plt.imshow(before_forest, cmap="RdYlGn")
    plt.savefig('/tmp/before_forest.png')
    plt.clf()

    plt.imshow(after_forest, cmap="RdYlGn")
    plt.savefig('/tmp/after_forest.png')   
    plt.clf()

    change_path = save_forest_change(before_pred_path, after_pred_path)
    with rasterio.open(change_path) as change_src:
        change = change_src.read(1, masked=True)

    plt.imshow(change, cmap="RdYlGn")
    plt.savefig('/tmp/change.png')   
    plt.clf()



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
            start_collection = get_collection(start_date_begin, start_date_end, bbox, "before", max_cloud_cover=30)
        except exceptions.EmptyCollectionException:
            print("before collection is empty")
            return

        try:
            after_collection = get_collection(end_date_begin, end_date_end, bbox, "after", max_cloud_cover=30)
        except exceptions.EmptyCollectionException:
            print("after collection is empty")
            return 

        
        # prepare imagery

        try:
            before_dict = save_composite_images(start_collection, bbox, "before")
        except exceptions.IncompleteCoverageException:
            print('before composite does not completely cover study area')
            return

        try:
            after_dict = save_composite_images(after_collection, bbox, "after")
        except exceptions.IncompleteCoverageException:
            print('after composite does not completely cover study area')
            return

        # upload composites

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

        # classify imagery

        before_pred_path = save_forest_classification(before_dict, "before")
        with rasterio.open(before_pred_path) as forest_src:
            before_forest = forest_src.read(1, masked=True)

        after_pred_path = save_forest_classification(after_dict, "after")
        with rasterio.open(after_pred_path) as forest_src:
            after_forest = forest_src.read(1, masked=True)

        gain = (after_forest - before_forest) > 0
        loss = (after_forest - before_forest) < 0

        # TODO: run start and end images through forest classifier
        # TODO: take difference between two 
        # TODO: calculate statistics and update some database linked to task
        # TODO: save composite images, forest classifications, and result to S3
        # TODO: update task.status = "complete"
        # TODO: update task...links to S3 stuff


    elif task_type == "burn_areas":
        pass

    elif task_type == "lulc_change":
        pass



if __name__ == "__main__":
    handle()

