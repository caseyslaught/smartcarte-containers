import boto3

from common.aws import get_boto_client


def send_email(from_address, to_addresses, subject, body):
    client = get_boto_client('ses')
    client.send_email(
        Source=from_address,
        Destination={
            'ToAddresses': to_addresses
        },
        Message={
            'Subject': {
                'Data': subject,
                'Charset': 'UTF-8'
            },
            'Body': {
                'Text': {
                    'Data': body,
                    'Charset': 'UTF-8'
                }
            }
        }
    )

