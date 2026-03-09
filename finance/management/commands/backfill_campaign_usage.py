"""
One-time backfill: count every ACTIVE or PAUSED UnifiedCampaign per
organization and set (not increment) the campaign_limit UsageRecord so
that the current billing period reflects the real number of live campaigns.

Usage:
    python manage.py backfill_campaign_usage
    python manage.py backfill_campaign_usage --dry-run
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from main.models import Organization, UnifiedCampaign
from finance.models import Subscription, UsageRecord


class Command(BaseCommand):
    help = "Backfill campaign_limit UsageRecord for all orgs based on existing ACTIVE/PAUSED campaigns."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be written without saving anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        orgs = (
            Organization.objects.filter(
                unifiedcampaign__status__in=["ACTIVE", "PAUSED"]
            )
            .annotate(live_count=Count("unifiedcampaign"))
            .distinct()
        )

        if not orgs.exists():
            self.stdout.write("No organizations with live campaigns found.")
            return

        updated = 0
        skipped = 0

        for org in orgs:
            subscription = (
                Subscription.objects
                .filter(organization=org, status__in=["active", "trialing"])
                .order_by("-created_at")
                .first()
            )

            if not subscription or not subscription.current_period_start:
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP  {org.name!r} — no active subscription / period dates."
                    )
                )
                skipped += 1
                continue

            live_count = UnifiedCampaign.objects.filter(
                organization=org,
                status__in=["ACTIVE", "PAUSED"],
            ).count()

            self.stdout.write(
                f"  {'DRY ' if dry_run else ''}SET  {org.name!r} → "
                f"campaign_limit used={live_count} "
                f"(period {subscription.current_period_start:%Y-%m-%d} → "
                f"{subscription.current_period_end:%Y-%m-%d})"
            )

            if not dry_run:
                record, created = UsageRecord.objects.get_or_create(
                    organization=org,
                    subscription=subscription,
                    feature_key="campaign_limit",
                    period_start=subscription.current_period_start,
                    period_end=subscription.current_period_end,
                    defaults={"used": live_count},
                )
                if not created:
                    record.used = live_count
                    record.save(update_fields=["used"])

            updated += 1

        summary = f"\nDone — {updated} org(s) updated, {skipped} skipped."
        self.stdout.write(self.style.SUCCESS(summary) if not dry_run else summary)
