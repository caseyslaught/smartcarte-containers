from datetime import datetime as dt
from shapely.geometry import shape

from src.common.utilities import api
from src.common.utilities.imagery import get_processed_image_array, _get_collection


def handle(event, context):
    print("### EVENT???")
    print(event)
    print("### CONTEXT")
    print(context)


    task_uid = ""
    # TODO: set task.status = "in progress"
    # TODO: use API to update everything, don't use sqlalchemy

    task_type = "forest_change"

    if task_type == "forest_change":

        task_dict = api.get_forest_change_task_params(task_uid)

        start_date = dt.strptime(task_dict['start_date'], '%Y-%m-%d')
        end_date = dt.strptime(task_dict['end_date'], '%Y-%m-%d')
        region = shape(task_dict['region']['geojson']['features'][0]['geometry']) # TODO: check this

        get_processed_image_array(start_date, end_date, region.bounds)


        # TODO: get composite image from start and end date
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

    



def _debug():

    start_date = dt(2021, 8, 1, 1)
    end_date = dt(2021, 10, 1, 1)
    bbox = [29.270558, -1.648015, 29.705426, -1.311937]

    print(bbox)

    get_processed_image_array(start_date, end_date, bbox)



def _debug2():

    task_uid = "2774dd61-50b3-46b6-bb52-9c30ec6863bd" 

    task_dict = api.get_forest_change_task_params(task_uid)

    start_date = dt.strptime(task_dict['start_date'], '%Y-%m-%d')
    end_date = dt.strptime(task_dict['end_date'], '%Y-%m-%d')

    region = shape(task_dict['region']['geojson']['features'][0]['geometry'])
    print(region.bounds)

    _get_collection(start_date, end_date, region.bounds)

    