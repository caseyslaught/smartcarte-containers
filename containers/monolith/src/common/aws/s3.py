import boto3

from common.aws import get_boto_client


def get_files(prefix, suffix, bucket_name):

    s3_client = get_boto_client('s3')

    response = s3_client.list_objects(
        Bucket=bucket_name,
        EncodingType='url',
        Prefix=prefix
    )

    is_truncated = response['IsTruncated']
    next_marker = response.get('NextMarker') # TODO: pagination, if is_truncated, use next_marker
    contents = response.get('Contents', None)
    if contents is not None:
        objects = [c['Key'] for c in contents if c['Key'].endswith(suffix)]
        return objects
    else:
        return []


def get_presigned_url(object_key, bucket, expiration_secs):

    client = get_boto_client('s3')

    url = client.generate_presigned_url('get_object', Params={'Bucket': bucket, 'Key': object_key},
                                        ExpiresIn=expiration_secs)
    return url


def put_s3_item(body, bucket, object_key):

    client = get_boto_client('s3')
    client.put_object(Body=body, Bucket=bucket, Key=object_key)


def put_item(file_path, bucket, object_key):
    s3 = boto3.resource('s3')
    s3.meta.client.upload_file(file_path, bucket, object_key)


