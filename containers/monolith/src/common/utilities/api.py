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


def update_task_status(task_uid, task_type, status):

    url = f'{API_BASE_URL}/tasks/update_task_status/'

    res = requests.post(url, {
        "task_uid": task_uid,
        "task_type": task_type,
        "status": status
    })

    if res.status_code != 200:
        print(res.status_code)
        raise ValueError()


