import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task
def purge_abandoned_checkouts():
    """Delete 'incomplete' subscriptions that never reached Stripe confirmation (older than 2 days)."""
    from apps.finance.models import Subscription

    deleted, _ = Subscription.objects.filter(
        status="incomplete",
        stripe_subscription_id__isnull=True,
        created_at__lt=timezone.now() - timedelta(days=2),
    ).delete()
    logger.info("Purged %s abandoned checkout subscriptions", deleted)
