"""Housekeeping tasks (audit SEC-22 / PERF-13): keep auth tables from growing forever."""
import logging
from datetime import timedelta

from celery import shared_task
from django.core.management import call_command
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def purge_expired_auth_data():
    """Delete expired/used OTPs, expired JWT bookkeeping rows and old read notifications."""
    from apps.accounts.models import OTP, Notification

    now = timezone.now()
    otp_deleted, _ = OTP.objects.filter(expires_at__lt=now - timedelta(days=1)).delete()
    notif_deleted, _ = Notification.objects.filter(read=True, created_at__lt=now - timedelta(days=90)).delete()
    try:
        call_command('flushexpiredtokens')
    except Exception:
        logger.exception("flushexpiredtokens failed")
    logger.info("Purged %s OTPs and %s old notifications", otp_deleted, notif_deleted)


@shared_task(bind=True, max_retries=3)
def send_otp_email_task(self, user_email, user_name, otp_code, expiry_minutes=10):
    """Send the OTP e-mail outside the HTTP request (SMTP can take seconds or fail)."""
    from apps.accounts.email_utils import send_otp_email
    try:
        send_otp_email(
            user_email=user_email, user_name=user_name,
            otp_code=otp_code, expiry_minutes=expiry_minutes,
        )
    except Exception as exc:
        logger.warning("OTP e-mail to a user failed (attempt %s): %s", self.request.retries + 1, type(exc).__name__)
        if self.request.is_eager:
            return
        raise self.retry(exc=exc, countdown=30 * (self.request.retries + 1))
