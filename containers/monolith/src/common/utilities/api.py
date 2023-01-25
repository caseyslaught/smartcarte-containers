from multiprocessing.sharedctypes import Value
import requests


API_BASE_URL = 'https://api.smartcarte.earth'


def get_forest_change_task_params(task_uid):

    url = f'{API_BASE_URL}/tasks/get_forest_change_task_params'
    
    res = requests.get(url, {'task_uid': task_uid})

    if res.status_code == 200:
        return res.json()
    else:
        print(res.content)
        raise ValueError()


def update_task_status(task_uid, task_type, status, message=None):

    url = f'{API_BASE_URL}/tasks/update_task_status/'

    res = requests.post(url, {
        "task_uid": task_uid,
        "task_type": task_type,
        "status": status,
        "message": message
    })

    if res.status_code != 200:
        raise ValueError(res.text)



def update_forest_change_task(task_uid, **kwargs):

    data = {
        "task_uid": task_uid,
        "gain_area": kwargs.get('gain_area'),
        "loss_area": kwargs.get('loss_area'),
        "total_area": kwargs.get('total_area'),
        "before_rgb_tiles_href": kwargs.get('before_rgb_tiles_href'),
        "after_rgb_tiles_href": kwargs.get('after_rgb_tiles_href'),
        "change_tiles_href": kwargs.get('change_tiles_href')
    }

    url = f'{API_BASE_URL}/tasks/update_forest_change_task/'
    res = requests.post(url, data)
    
    if res.status_code != 200:
        raise ValueError(res.text)



