import json
import os
from django.core.management.base import BaseCommand
from apps.finance.models import Plan, PlanFeature


# Prices and descriptions are not stored in the JSON (client-provided feature
# text) so they live here alongside the plan name used as the lookup key.
PLAN_META = {
    "starter": {
        "price": 79.00,
        "description": "Launch quickly. Spend smarter. AI-powered ads without the complexity.",
    },
    "growth": {
        "price": 199.00,
        "description": "Scale campaigns with data-driven insights and collaboration tools.",
    },
    "scale": {
        "price": 499.00,
        "description": "Automate everything. Outsmart competitors. Grow profitably with AI.",
    },
}

# Feature keys that drive usage tracking / limit enforcement.
# These are the keys we check against UsageRecord.feature_key.
TRACKABLE_KEYS = {
    "campaign_limit",       # how many campaigns can be created per billing period
    "team_member_limit",    # max active team members in an organisation
    "ai_copy_generator",    # boolean – whether AI copy gen is accessible
    "ai_insights_level",    # standard | full
    "ai_budget_optimization",  # suggestions | daily | full
    "ai_creative_fatigue",  # boolean
    "ai_optimization_engine",  # false | full
    "analytics_level",      # standard | custom
    "report_level",         # basic | detailed | full
    "audience_expansion",   # boolean
    "agency_workspace",     # boolean
}


def _normalise_value(raw) -> str:
    """Convert any JSON value (bool, int, None, str) to a uniform string."""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if raw is None:
        return ""
    return str(raw)


class Command(BaseCommand):
    help = "Create / update subscription plans and their named features"

    def handle(self, *args, **options):
        json_path = os.path.join(
            os.path.dirname(__file__), "../../../subscription plans.json"
        )

        try:
            with open(json_path, "r") as f:
                plans_data = json.load(f)
        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(f"Could not find subscription plans.json at {json_path}")
            )
            return

        for plan_entry in plans_data:
            plan_name = plan_entry["plan"]
            meta = PLAN_META.get(plan_name)

            if meta is None:
                self.stdout.write(
                    self.style.WARNING(f"No metadata for plan '{plan_name}' – skipping")
                )
                continue

            plan, created = Plan.objects.update_or_create(
                name=plan_name,
                defaults={
                    "price": meta["price"],
                    "currency": "USD",
                    "interval": "month",
                    "description": meta["description"],
                    "is_active": True,
                    "is_custom": False,
                },
            )

            action = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"✓ {action} plan: {plan.name}"))

            # Rebuild features from scratch so stale keys are removed.
            PlanFeature.objects.filter(plan=plan).delete()

            features = plan_entry.get("features", [])
            for feature in features:
                key = feature["key"]
                value = _normalise_value(feature.get("value"))
                display = feature.get("display")  # may be None for tracking-only rows

                PlanFeature.objects.create(
                    plan=plan,
                    key=key,
                    value=value,
                    display=display,
                )

            trackable = [f["key"] for f in features if f["key"] in TRACKABLE_KEYS]
            self.stdout.write(
                f"  → {len(features)} features stored "
                f"({len(trackable)} trackable: {', '.join(trackable)})"
            )

        self.stdout.write(self.style.SUCCESS("\n✓ All plans created/updated successfully!"))
