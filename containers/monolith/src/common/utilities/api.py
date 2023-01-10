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
        raise ValueError(res.text)



def update_forest_change_task_results(task_uid, gain_area, loss_area, total_area):

    url = f'{API_BASE_URL}/tasks/update_forest_change_task_results/'

    res = requests.post(url, {
        "task_uid": task_uid,
        "gain_area": gain_area,
        "loss_area": loss_area,
        "total_area": total_area
    })

    if res.status_code != 200:
        raise ValueError(res.text)
