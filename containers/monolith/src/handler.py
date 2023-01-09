from datetime import datetime as dt
from datetime import timedelta as td
from shapely.geometry import shape
import sys

from common import exceptions
from common.constants import DAYS_BUFFER
from common.utilities import api
from common.utilities.indices import save_ndvi
from common.utilities.imagery import save_composite_images, get_collection, save_tif_to_s3



def _debug():

    task_uid = "c65c1f3a-ff8d-4c80-be9f-04355de64fa4" 
    task_type = "forest_change"

    api.update_task_status(task_uid, task_type, "running")

    params = api.get_forest_change_task_params(task_uid)

    start_date_end = dt.strptime(params['start_date'], '%Y-%m-%d')
    start_date_begin = start_date_end - td(days=DAYS_BUFFER)

    geojson = params['region']['geojson']
    if geojson['type'] == 'FeatureCollection':
        region = shape(geojson['features'][0]['geometry'])
    elif geojson['type'] == 'Polygon':
        region = shape(geojson)
    else:
        raise ValueError("invalid geojson type") # TODO: figure out proper logging!

    bbox = region.bounds

    before_collection = get_collection(start_date_begin, start_date_end, bbox, "before", max_cloud_cover=4)
    before_dict = save_composite_images(before_collection, bbox, "before")

    before_ndvi_path = save_ndvi(before_dict['B04'], before_dict['B08'])
    print("before_ndvi_path:", before_ndvi_path)
    save_tif_to_s3(task_uid, before_ndvi_path, "before")


def _ndvi():

    task_uid = "c65c1f3a-ff8d-4c80-be9f-04355de64fa4" 

    red = "/tmp/before/B04_composite.tif"
    nir = "/tmp/before/B08_composite.tif"

    ndvi_path = save_ndvi(red, nir, "before")
    print(ndvi_path)

    save_tif_to_s3(task_uid, ndvi_path, "before")



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

