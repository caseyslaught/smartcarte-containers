
from common.aws.ses import send_email 


def send_success_email(task_uid, date_start, date_end, region_area_km2, recipient_email):

    from_address = "noreply@smartcarte.earth"
    from_name = "Smart Carte"
    to_addresses = [recipient_email]
    subject = "Your task is complete!"
    body = f"""
    Click the following link to access your results:
    https://smartcarte.earth/demo/{task_uid}

    Date range: {date_start.strftime('%Y-%m-%d')} to {date_end.strftime('%Y-%m-%d')}
    Region: {region_area_km2} km2

    You can create a new task here:
    https://smartcarte.earth/demo
    """

    send_email(from_address, from_name, to_addresses, subject, body)
