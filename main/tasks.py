from celery import shared_task
from main.utils.meta_engine.sync_ad import sync_meta_integration
from main.models import AdIntegration


@shared_task(bind=True, max_retries=3)
def sync_ads_task(self, platform_integration_id):
    """Background task to sync ads for a given platform integration."""
    try:
        platform_integration = AdIntegration.objects.get(id=platform_integration_id)
    except AdIntegration.DoesNotExist:
        return  # If the integration doesn't exist, we can skip syncing
    try:
        if platform_integration.platform.upper() == 'META':
            sync_meta_integration(platform_integration)
        # other platforms can be added here in the future
        else:
            raise ValueError(f"Unsupported platform: {platform_integration.platform}")
    except Exception as exc:
        self.retry(exc=exc, countdown=60)  # Retry after 60 seconds if there's an error
