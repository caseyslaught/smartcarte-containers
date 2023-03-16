import requests

from common.constants import API_BASE_URL


def get_demo_classification_task(task_uid):

    url = f'{API_BASE_URL}/tasks/get_demo_classification_task/{task_uid}'
    res = requests.get(url)

    if res.status_code == 200:
        return res.json()
    else:
        raise Exception(res.text)
    

def update_demo_classification_task(task_uid, **kwargs):

    url = f'{API_BASE_URL}/tasks/update_demo_classification_task/'

    data = {
        "task_uid": task_uid,
        "statistics_json": kwargs.get('statistics_json'),
        "imagery_tif_href": kwargs.get('imagery_tif_href'),
        "imagery_tiles_href": kwargs.get('imagery_tiles_href'),
        "landcover_tif_href": kwargs.get('landcover_tif_href'),
        "landcover_tiles_href": kwargs.get('landcover_tiles_href'),
    }

    res = requests.post(url, data)
    
    if res.status_code != 200:
        raise Exception(res.text)


def update_task_status(task_uid, task_type, status, message=None, long_message=None):

    url = f'{API_BASE_URL}/tasks/update_task_status/'

    res = requests.post(url, {
        "task_uid": task_uid,
        "task_type": task_type,
        "status": status,
        "message": message,
        "long_message": long_message
    })

    if res.status_code != 200:
        raise Exception(res.text)

