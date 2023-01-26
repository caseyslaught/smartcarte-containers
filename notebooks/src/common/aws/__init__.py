import boto3
import os


def get_boto_client(service):

    params = {
        'aws_access_key_id': os.environ['SC_AWS_KEY'],
        'aws_secret_access_key': os.environ['SC_AWS_SECRET'],
        'region_name': 'eu-central-1'
    }

    return boto3.client(service, **params)