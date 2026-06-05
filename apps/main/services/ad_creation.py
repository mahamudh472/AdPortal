from django.db import transaction, IntegrityError
from rest_framework.exceptions import ValidationError
from apps.main.models import (
    UnifiedCampaign, AdAsset, CampaignBudget, AdIntegration
)
from apps.main.utils.object_handlers import create_full_ad_for_platform
from apps.main.tasks import sync_campaign_to_platforms_task
from apps.finance.utils import increment_campaign_usage
import logging

logger = logging.getLogger(__name__)

class AdCreationService:
    REQUIRED_FIELDS_FOR_PUBLISH = [
        'platforms', 'campaign_name', 'objective', 'budgets',
        'min_age', 'max_age', 'gender', 'locations', 'keywords',
        'ad_name', 'headline', 'primary_text', 'description',
        'call_to_action', 'destination_url'
    ]

    def validate_platform_integrations(self, organization, platforms):
        """Verify that the organization has active integrations for all requested platforms."""
        if not platforms:
            return
            
        for platform in platforms:
            if not AdIntegration.objects.filter(
                platform=platform, 
                organization=organization, 
                is_active=True
            ).exists():
                raise ValidationError(
                    f"No active Ad Integration found for platform '{platform}'. "
                    "Please set up an ad account integration first."
                )

    @staticmethod
    def _budget_to_minor_units(value):
        """Normalize incoming budget (dollars) to minor units (cents)."""
        try:
            return int(round(float(value) * 100))
        except (TypeError, ValueError):
            raise ValidationError({'budget': 'Invalid budget value.'})

    @staticmethod
    def _prepare_for_json(data):
        """Convert validated data to JSON-serializable format."""
        result = {}
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                result[key] = [
                    {k: v.isoformat() if hasattr(v, 'isoformat') else v for k, v in item.items()}
                    for item in value
                ]
            elif hasattr(value, 'isoformat'):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result

    def create_draft(self, organization, data, ad_file=None):
        campaign_name = data.pop('campaign_name', None)
        if not campaign_name:
            raise ValidationError({'campaign_name': 'Campaign name is required to create a new ad'})

        objective = data.pop('objective', '')
        draft_data = self._prepare_for_json(data)

        if ad_file:
            asset = AdAsset.objects.create(
                organization=organization,
                file=ad_file,
                file_type='VIDEO' if ad_file.content_type.startswith('video/') else 'IMAGE',
            )
            draft_data['ad_asset_id'] = asset.id

        try:
            campaign = UnifiedCampaign.objects.create(
                organization=organization,
                name=campaign_name,
                objective=objective,
                status='DRAFT',
                draft_data=draft_data,
            )
        except IntegrityError:
            raise ValidationError({'campaign_name': 'A campaign with this name already exists in your organization.'})
        return campaign

    def update_campaign(self, campaign_id, organization, data, ad_file=None):
        campaign = UnifiedCampaign.objects.filter(
            id=campaign_id, organization=organization
        ).first()
        if not campaign:
            raise ValidationError({'campaign_id': 'Campaign not found'})

        should_sync_platforms = campaign.status != 'DRAFT'

        # Update campaign-level fields
        if 'campaign_name' in data:
            campaign.name = data.pop('campaign_name')
        if 'objective' in data:
            new_objective = data.pop('objective')
            if campaign.status != 'DRAFT' and campaign.objective != new_objective:
                raise ValidationError({'objective': 'Objective cannot be changed once the campaign is published.'})
            campaign.objective = new_objective

        if campaign.status == 'DRAFT':
            # For drafts, keep merging into draft_data
            draft_data = campaign.draft_data or {}
            draft_data.update(self._prepare_for_json(data))

            if ad_file:
                asset = AdAsset.objects.create(
                    organization=organization,
                    file=ad_file,
                    file_type='VIDEO' if ad_file.content_type.startswith('video/') else 'IMAGE',
                )
                draft_data['ad_asset_id'] = asset.id

            campaign.draft_data = draft_data
        else:
            # For published campaigns, update real models directly
            self._update_published_campaign(campaign, organization, data, ad_file)

        try:
            campaign.save()
        except IntegrityError:
            raise ValidationError({'campaign_name': 'A campaign with this name already exists in your organization.'})
        
        # Create platform campaigns for any new platforms being added
        self._create_missing_platform_campaigns(campaign, data, ad_file)

        if should_sync_platforms:
            # Queue sync task AFTER transaction commits to avoid race condition
            transaction.on_commit(
                lambda: sync_campaign_to_platforms_task.delay(campaign.id, 'UPDATE')
            )
        
        return campaign

    def _update_published_campaign(self, campaign, organization, data, ad_file=None):
        """Update related models directly for already-published campaigns."""
        # Update budgets
        if 'budgets' in data:
            for budget in data.pop('budgets'):
                CampaignBudget.objects.update_or_create(
                    campaign=campaign,
                    platform=budget['platform'],
                    defaults={
                        'budget_type': budget['budget_type'],
                        'daily_budget_minor': self._budget_to_minor_units(budget['budget']),
                        'start_date': budget['start_date'],
                        'end_date': budget['end_date'],
                        'run_continuously': budget['run_continuously'],
                    }
                )

        # Update targeting on existing ad groups
        targeting_fields = ['min_age', 'max_age', 'gender', 'locations', 'keywords']
        targeting_update = {k: data.pop(k) for k in targeting_fields if k in data}
        if targeting_update:
            for pc in campaign.platform_campaigns.all():
                for ag in pc.ad_groups.all():
                    ag.targeting_config.update(targeting_update)
                    ag.save()

        # Update ad creative on existing ads
        creative_fields = ['headline', 'primary_text', 'description', 'call_to_action', 'destination_url', 'ad_name']
        creative_update = {k: data.pop(k) for k in creative_fields if k in data}
        if creative_update or ad_file:
            ad_asset = None
            if ad_file:
                ad_asset = AdAsset.objects.create(
                    organization=organization,
                    file=ad_file,
                    file_type='VIDEO' if ad_file.content_type.startswith('video/') else 'IMAGE',
                )

            for pc in campaign.platform_campaigns.all():
                for ag in pc.ad_groups.all():
                    for ad in ag.ads.all():
                        if 'ad_name' in creative_update:
                            ad.name = creative_update['ad_name']
                        if 'headline' in creative_update:
                            ad.headline = creative_update['headline']
                        if 'primary_text' in creative_update:
                            ad.primary_text = creative_update['primary_text']
                        if 'description' in creative_update:
                            ad.description = creative_update['description']
                        if 'call_to_action' in creative_update:
                            ad.call_to_action = creative_update['call_to_action']
                        if 'destination_url' in creative_update:
                            ad.destination_url = creative_update['destination_url']
                        if ad_asset:
                            ad.assets.add(ad_asset)
                        ad.save()

    def _create_missing_platform_campaigns(self, campaign, data, ad_file=None):
        """Create platform campaigns for any new platforms being added to the campaign."""
        # Only process if platforms are provided
        platforms = data.get('platforms', [])
        if not platforms:
            return

        # Get existing platforms for this campaign
        existing_platforms = set(
            campaign.platform_campaigns.values_list('integration__platform', flat=True)
        )

        # Get all draft_data (either from data or campaign.draft_data for draft campaigns)
        draft_data = campaign.draft_data or {}
        
        # Build full data dict for platform creation
        full_data = {
            'name': campaign.name,
            **draft_data,
        }

        # Create platform campaigns for new platforms only
        for platform in platforms:
            if platform not in existing_platforms:
                try:
                    create_full_ad_for_platform(campaign, full_data, platform, ad_asset=None)
                except ValidationError:
                    pass

    def publish_campaign(self, campaign, organization):
        """Validate all required fields and create platform objects."""
        if campaign.status != 'DRAFT':
            raise ValidationError({'status': 'Only draft campaigns can be published.'})

        draft_data = campaign.draft_data or {}

        all_data = {
            'campaign_name': campaign.name,
            'objective': campaign.objective,
            **draft_data,
        }

        missing = [f for f in self.REQUIRED_FIELDS_FOR_PUBLISH if not all_data.get(f)]
        if missing:
            raise ValidationError({
                'missing_fields': f"Required to publish: {', '.join(missing)}"
            })

        # Create budgets
        for budget in draft_data.get('budgets', []):
            CampaignBudget.objects.update_or_create(
                campaign=campaign,
                platform=budget['platform'],
                defaults={
                    'budget_type': budget['budget_type'],
                    'daily_budget_minor': self._budget_to_minor_units(budget['budget']),
                    'start_date': budget['start_date'],
                    'end_date': budget['end_date'],
                    'run_continuously': budget['run_continuously'],
                }
            )

        # Resolve pre-uploaded ad asset
        ad_asset = None
        ad_asset_id = draft_data.get('ad_asset_id')
        if ad_asset_id:
            ad_asset = AdAsset.objects.filter(id=ad_asset_id).first()

        # Build data dict for platform object creation
        full_data = {
            'name': campaign.name,
            **draft_data,
        }

        for platform in draft_data['platforms']:
            create_full_ad_for_platform(campaign, full_data, platform, ad_asset=ad_asset)

        campaign.status = 'ACTIVE'
        campaign.draft_data = {}
        campaign.save()
        increment_campaign_usage(organization)
        
        # Queue sync task AFTER transaction commits to avoid race condition
        transaction.on_commit(
            lambda: sync_campaign_to_platforms_task.delay(campaign.id, 'CREATE')
        )

        # Notify org owner/admins that the campaign is now live
        from apps.accounts.notifications import notify_org_members
        notify_org_members(
            organization,
            f"Campaign \"{campaign.name}\" has been published and is now live.",
            setting_key='campaign_performance',
        )
