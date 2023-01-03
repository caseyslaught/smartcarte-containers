
from src.common.utilities.imagery import _debug


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
        
        roi = "" # not sure what this should be...
        start_date = "2020-01-01"
        end_date = "2022-01-01"

        _debug()

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

    