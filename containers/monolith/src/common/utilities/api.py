import requests


API_BASE_URL = 'https://api.smartcarte.earth'


def get_forest_change_task_params(task_uid):

    url = f'{API_BASE_URL}/tasks/get_forest_change_task_params'
    
    res = requests.get(url, {'task_uid': task_uid})

    if res.status_code == 200:
        return res.json()
    else:
        raise ValueError()

