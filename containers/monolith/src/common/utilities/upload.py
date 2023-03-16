import os

from common.aws import s3 as s3_utils
from common.constants import DATA_CDN_BASE_URL, S3_DATA_BUCKET


def get_file_cdn_url(file_name):
    return f'{DATA_CDN_BASE_URL}/{file_name}'


def get_tiles_cdn_url(s3_dir):
    return f'{DATA_CDN_BASE_URL}/{s3_dir}' + '/{z}/{x}/{y}.png'


def save_task_file_to_s3(file_path, task_uid, bucket=S3_DATA_BUCKET, subdir=None):
    """
    Save a a task file to S3. This includes TIFs and matplotlib plots.
    """
    
    file_name = file_path.split('/')[-1]

    if subdir is None:
        object_key = f'tasks/{task_uid}/{file_name}'
    else:
        object_key = f'tasks/{task_uid}/{subdir}/{file_name}'

    print(f'uploading {file_path} to s3://{bucket}/{object_key}')

    s3_utils.put_item(file_path, bucket, object_key)

    return object_key



def save_task_tiles_to_s3(tiles_dir, task_uid, bucket=S3_DATA_BUCKET, subdir=None):
    """
    Saves a map tiles directory to S3 for use as a slippy map.
    """

    dir_name = tiles_dir.split('/')[-1]

    if subdir is None:
        object_base = f'tasks/{task_uid}/{dir_name}'
    else:
        object_base = f'tasks/{task_uid}/{subdir}/{dir_name}'
    
    print(f'uploading {tiles_dir} to s3://{bucket}/{object_base}')

    for root, dirs, files in os.walk(tiles_dir):
        for file in files:
            file_path = os.path.join(root, file)
            sub_path = file_path.replace(tiles_dir, '')
            object_key = f'{object_base}{sub_path}'
            s3_utils.put_item(file_path, bucket, object_key)

    return object_base

