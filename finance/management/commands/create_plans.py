import json
import os
from django.core.management.base import BaseCommand
from finance.models import Plan, PlanFeature


class Command(BaseCommand):
    help = 'Create subscription plans with their features'

    def handle(self, *args, **options):
        # Plan configurations
        plans_config = [
            {
                'name': 'starter',
                'price': 79.00,
                'description': 'Launch quickly. Spend smarter. AI-powered ads without the complexity.'
            },
            {
                'name': 'growth',
                'price': 199.00,
                'description': 'Scale campaigns with data-driven insights and collaboration tools.'
            },
            {
                'name': 'scale',
                'price': 499.00,
                'description': 'Automate everything. Outsmart competitors. Grow profitably with AI.'
            }
        ]

        # Load features from JSON file
        json_path = os.path.join(os.path.dirname(__file__), '../../../subscription plans.json')
        
        try:
            with open(json_path, 'r') as f:
                features_list = json.load(f)
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'Could not find subscription plans.json at {json_path}'))
            return

        # Create plans
        for idx, plan_config in enumerate(plans_config):
            plan, created = Plan.objects.update_or_create(
                name=plan_config['name'],
                defaults={
                    'price': plan_config['price'],
                    'currency': 'USD',
                    'interval': 'month',
                    'description': plan_config['description'],
                    'is_active': True,
                    'is_custom': False
                }
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f'✓ Created plan: {plan.name}'))
            else:
                self.stdout.write(self.style.WARNING(f'✓ Updated plan: {plan.name}'))

            # Clear existing features for this plan
            PlanFeature.objects.filter(plan=plan).delete()

            # Add features from JSON
            if idx < len(features_list):
                features = features_list[idx]
                for feature_idx, feature_text in enumerate(features, start=1):
                    PlanFeature.objects.create(
                        plan=plan,
                        key=f'feature_{feature_idx}',
                        value=feature_text
                    )
                
                self.stdout.write(
                    self.style.SUCCESS(f'  → Added {len(features)} features')
                )

        self.stdout.write(self.style.SUCCESS('\n✓ All plans created successfully!'))
