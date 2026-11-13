"""Backfill or refresh analytics for one organization / integration.

Examples:
    python manage.py sync_analytics --org 123456789012345
    python manage.py sync_analytics --integration 7 --since 2025-01-01
    python manage.py sync_analytics --all --days 395
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.main.models import AdIntegration, Organization, PlatformCampaign


class Command(BaseCommand):
    help = 'Fetch analytics from every active ad platform integration.'

    def add_arguments(self, parser):
        parser.add_argument('--org', help='Organization snowflake id.')
        parser.add_argument('--integration', type=int, help='AdIntegration primary key.')
        parser.add_argument('--all', action='store_true', help='Sync every active integration.')
        parser.add_argument('--since', help='Start date (YYYY-MM-DD). Defaults to the rolling window.')
        parser.add_argument('--until', help='End date (YYYY-MM-DD). Defaults to today.')
        parser.add_argument('--days', type=int, help='Backfill the last N days.')

    def handle(self, *args, **options):
        from apps.analysis.ingest import default_window
        from apps.main.utils.meta_engine.analysis import generate_meta_campaign_analysis
        from apps.main.utils.google_engine.analysis import generate_google_campaign_analysis
        from apps.main.utils.tiktok_engine.analysis import generate_tiktok_campaign_analysis

        start = end = None
        if options.get('since') or options.get('until'):
            try:
                start = datetime.strptime(options['since'], '%Y-%m-%d').date() if options.get('since') else None
                end = datetime.strptime(options['until'], '%Y-%m-%d').date() if options.get('until') else None
            except ValueError as exc:
                raise CommandError(f'Invalid date: {exc}')
        elif options.get('days'):
            from datetime import timedelta
            from django.utils import timezone
            end = timezone.now().date()
            start = end - timedelta(days=options['days'] - 1)
        else:
            start, end = default_window()

        integrations = AdIntegration.objects.filter(is_active=True)
        if options.get('integration'):
            integrations = integrations.filter(id=options['integration'])
        elif options.get('org'):
            organization = Organization.objects.filter(snowflake_id=options['org']).first()
            if not organization:
                raise CommandError(f'Organization {options["org"]} not found.')
            integrations = integrations.filter(organization=organization)
        elif not options.get('all'):
            raise CommandError('Pass --org, --integration or --all.')

        integrations = integrations.select_related('organization').order_by('id')
        if not integrations.exists():
            raise CommandError('No matching active integrations.')

        failures = 0
        for integration in integrations:
            self.stdout.write(
                f'Syncing {integration.platform} integration {integration.id} '
                f'({integration.organization_id}) {start} -> {end}'
            )
            try:
                if integration.platform == 'META':
                    campaign_ids = list(
                        PlatformCampaign.objects.filter(
                            integration=integration, platform_campaign_id__isnull=False
                        ).values_list('platform_campaign_id', flat=True)
                    )
                    generate_meta_campaign_analysis(integration, campaign_ids, start, end)
                elif integration.platform == 'GOOGLE':
                    generate_google_campaign_analysis(integration, start, end)
                elif integration.platform == 'TIKTOK':
                    generate_tiktok_campaign_analysis(integration, start, end)
                else:
                    self.stderr.write(f'  unsupported platform {integration.platform}')
                self.stdout.write(self.style.SUCCESS('  done'))
            except Exception as exc:  # noqa: BLE001 - keep going for other integrations
                failures += 1
                self.stderr.write(self.style.ERROR(f'  failed: {exc}'))

        if failures:
            raise CommandError(f'{failures} integration(s) failed.')
