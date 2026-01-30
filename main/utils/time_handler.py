from datetime import datetime
import pytz
from django.utils import timezone


def user_time_to_utc(user_dt: datetime, user_tz_str: str) -> datetime:
    """
    Convert user-provided datetime to UTC (aware).
    """
    user_tz = pytz.timezone(user_tz_str)

    # If naive, localize it
    if timezone.is_naive(user_dt):
        user_dt = user_tz.localize(user_dt)

    # Convert to UTC
    return user_dt.astimezone(pytz.UTC)

def utc_to_user_time(utc_dt: datetime, user_tz_str: str) -> datetime:
    """
    Convert UTC datetime to user's timezone.
    """
    user_tz = pytz.timezone(user_tz_str)

    if timezone.is_naive(utc_dt):
        utc_dt = timezone.make_aware(utc_dt, timezone=pytz.UTC)

    return utc_dt.astimezone(user_tz)
