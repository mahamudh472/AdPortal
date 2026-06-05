from django.db import transaction, models
from django.db.models import Sum, F, FloatField, Subquery, OuterRef, ExpressionWrapper
from django.db.models.functions import Coalesce
from rest_framework.exceptions import ValidationError, PermissionDenied
from apps.main.models import UnifiedCampaign, Organization, CampaignBudget
from apps.analysis.models import AnalysisDaily
from apps.main.tasks import (
    sync_campaign_to_platforms_task, 
    delete_campaign_from_platforms_task,
    toggle_campaign_status_task,
    sync_ads_task,
    sync_analytics_task
)
from apps.accounts.notifications import notify_org_members

class CampaignService:
    def annotate_queryset_with_metrics(self, queryset):
        """Annotate a UnifiedCampaign queryset with performance metrics."""
        # Subquery for total budget to avoid cartesian product with daily_analyses
        budget_subquery = CampaignBudget.objects.filter(
            campaign=OuterRef('pk')
        ).values('campaign').annotate(
            total=Sum('daily_budget_minor')
        ).values('total')

        return queryset.annotate(
            _total_budget=Coalesce(Subquery(budget_subquery), 0),
            _total_spent=Coalesce(
                Sum('daily_analyses__spend'), 0.0, output_field=FloatField()
            ),
            _impressions=Coalesce(Sum('daily_analyses__impressions'), 0),
            _clicks=Coalesce(Sum('daily_analyses__clicks'), 0),
            _conversions=Coalesce(Sum('daily_analyses__conversions'), 0),
            _weighted_roas=Coalesce(
                Sum(ExpressionWrapper(
                    F('daily_analyses__roas') * F('daily_analyses__spend'),
                    output_field=FloatField()
                )),
                0.0, output_field=FloatField()
            ),
        )

    def get_campaign_list_queryset(self, organization):
        queryset = UnifiedCampaign.objects.filter(organization=organization)
        queryset = self.annotate_queryset_with_metrics(queryset)
        return queryset.prefetch_related(
            'platform_campaigns__integration'
        ).order_by('-created_at')

    def get_campaign_detail_queryset(self, organization):
        queryset = UnifiedCampaign.objects.filter(organization=organization)
        queryset = self.annotate_queryset_with_metrics(queryset)
        return queryset.prefetch_related(
            'platform_campaigns__integration',
            'platform_campaigns__ad_groups__ads__assets',
            'ai_insights',
        )

    def update_campaign_instance(self, instance):
        """Logic for after a campaign is updated via serializer."""
        # Only push to platforms when the campaign is already published
        if instance.status not in ('DRAFT',):
            transaction.on_commit(
                lambda: sync_campaign_to_platforms_task.delay(instance.id, 'UPDATE')
            )

    def delete_campaign(self, instance, user):
        # Change permission to allow only owner or admin to delete campaign
        if not instance.organization.memberships.filter(user=user, role__in=['OWNER', 'ADMIN']).exists():
            raise PermissionDenied("You do not have permission to delete this campaign.")
        
        organization = instance.organization
        campaign_name = instance.name

        # Collect platform-level IDs *before* the DB row is deleted
        platform_campaign_ids = list(
            instance.platform_campaigns
            .filter(platform_campaign_id__isnull=False)
            .values_list('id', flat=True)
        )

        instance.delete()

        # Fire-and-forget: delete the ads from each platform in the background
        if platform_campaign_ids:
            transaction.on_commit(
                lambda: delete_campaign_from_platforms_task.delay(platform_campaign_ids)
            )

        notify_org_members(
            organization,
            f"Campaign \"{campaign_name}\" has been deleted.",
            setting_key='campaign_performance',
        )

    def toggle_campaign_status(self, campaign_id, organization):
        campaign = UnifiedCampaign.objects.filter(
            id=campaign_id, organization=organization
        ).first()
        if not campaign:
            raise ValidationError({'campaign_id': 'Campaign not found.'})

        TOGGLEABLE = {'ACTIVE', 'PAUSED'}
        if campaign.status not in TOGGLEABLE:
            raise ValidationError(
                {
                    'error': (
                        f"Cannot toggle a campaign with status '{campaign.status}'. "
                        "Only ACTIVE or PAUSED campaigns can be toggled."
                    )
                }
            )

        target_status = 'PAUSED' if campaign.status == 'ACTIVE' else 'ACTIVE'

        # Update the unified status immediately
        campaign.status = target_status
        campaign.save(update_fields=['status', 'updated_at'])

        # Propagate to platforms in the background
        toggle_campaign_status_task.delay(campaign.id, target_status)

        # Notify org owner/admins of the status change
        notify_org_members(
            organization,
            f"Campaign \"{campaign.name}\" status changed to {target_status.lower()}.",
            setting_key='campaign_performance',
        )

        return {
            'campaign_id': campaign.id,
            'status': target_status,
            'message': f"Campaign is now {target_status.lower()}. "
                       "Platform changes are being applied in the background.",
        }

    def sync_ads(self, organization):
        integrations = organization.integrations.filter(is_active=True)
        if not integrations.exists():
            raise ValidationError({'error': 'No active platform integrations found for this organization.'})

        dispatched = 0
        for integration in integrations:
            if integration.platform.upper() == 'GOOGLE':
                continue
            sync_ads_task.delay(integration.id)
            dispatched += 1

        if dispatched == 0:
            raise ValidationError({'error': 'No supported active integrations found.'})

        return {'message': 'Ad sync initiated successfully'}

    def sync_analytics(self, organization, platform_filter, start_date, end_date):
        integrations = organization.integrations.filter(is_active=True)
        if platform_filter:
            integrations = integrations.filter(platform=platform_filter.upper())

        if not integrations.exists():
            raise ValidationError({'error': 'No active integrations found.'})

        dispatched = 0
        for integration in integrations:
            if integration.platform.upper() == 'GOOGLE':
                continue
            sync_analytics_task.delay(integration.id, start_date, end_date)
            dispatched += 1

        if dispatched == 0:
            raise ValidationError({'error': 'No supported integrations found (Google analytics not yet supported).'})

        return {'message': f'Analytics sync initiated for {dispatched} integration(s).'}
