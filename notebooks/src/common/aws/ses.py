import boto3


def send_email(from_address, from_name, to_addresses, subject, body):
    client = boto3.client('ses')
    client.send_email(
        Source=f'{from_name} <{from_address}>',
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
