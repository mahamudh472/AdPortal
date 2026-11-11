from django.core.management.base import BaseCommand

from apps.main.models import AdIntegration


class Command(BaseCommand):
    help = "Encrypt any plaintext OAuth tokens and fill the access-token blind index."

    def handle(self, *args, **options):
        count = 0
        for integration in AdIntegration.objects.all().iterator():
            integration.save(update_fields=['access_token', 'refresh_token', 'access_token_hash'])
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Re-saved {count} integrations (tokens are now encrypted)."))
