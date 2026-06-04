from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.response import Response
from rest_framework import generics, status
from django.db import models, IntegrityError, transaction
from accounts.models import User
from main.utils.tiktok_handler import create_full_ad_for_tiktok
from .serializers import (
    AIAdCopySerializer, CampaignSerializer, CreateAdSerializer, AICopyRequestSerializer, OrganizationSerializer, TeamMemberInviteSerializer, TeamMemberSerializer, AIInsightSerializer, TempCampaignSerializer
)
from .models import AdAsset, UnifiedCampaign, Organization, OrganizationMember, TeamInvitation, CampaignBudget
from main.utils.object_handlers import (
    create_full_ad_for_platform
)
from accounts.permissions import IsAdminOrOwnerOfOrganization, IsRegularPlatformUser, IsOrganizationMember
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from .ai_services import generate_ad_copy, generate_copy
from .mixins import RequiredOrganizationIDMixin
from finance.models import Subscription, UsageRecord
from finance.utils import increment_campaign_usage
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from accounts.email_utils import send_team_invitation_email, send_account_created_email
import random
from main.utils.helper import get_dashboard_data, get_analytics_data
from main.tasks import sync_ads_task, sync_campaign_to_platforms_task



@extend_schema(
        parameters=[
            OpenApiParameter(
                name="org_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Organization Snowflake ID"
            )
        ]
    )
class OrganizationRetrieveUpdateAPIView(RequiredOrganizationIDMixin, generics.RetrieveUpdateAPIView):
    serializer_class = OrganizationSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get_object(self):
        user = self.request.user
        snoflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snoflake_id, memberships__user=user).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        return organization

class DashboardAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        from main.models import AIInsight
        # Create some dummy AI insights if there are none for testing purposes
        test_campaign = UnifiedCampaign.objects.filter(organization=organization).first()
        if not organization.ai_insights.exists() and test_campaign:
            _ = AIInsight.objects.create(
                organization=organization,
                campaign=test_campaign,
                title="Test Insight 1",
                description="This is a test insight.",
                impact="HIGH"
            )
            _ = AIInsight.objects.create(
                organization=organization,
                campaign=test_campaign,
                title="Test Insight 2",
                description="This is another test insight.",
                impact="MEDIUM"
            )
        data = get_dashboard_data(organization.snowflake_id)
        return Response(data, status=status.HTTP_200_OK)

class CampaignPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
class CampaignListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
    serializer_class = TempCampaignSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    pagination_class = CampaignPagination
    search_fields = ['name', 'objective']
    filterset_fields = ['status']

    def get_queryset(self):
        from django.db.models import Sum, F, FloatField, Subquery, OuterRef, ExpressionWrapper
        from django.db.models.functions import Coalesce
        from analysis.models import AnalysisDaily

        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        # Subquery for total budget to avoid cartesian product with daily_analyses
        budget_subquery = CampaignBudget.objects.filter(
            campaign=OuterRef('pk')
        ).values('campaign').annotate(
            total=Sum('daily_budget_minor')
        ).values('total')

        queryset = UnifiedCampaign.objects.filter(
            organization=organization
        ).annotate(
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
        ).prefetch_related(
            'platform_campaigns__integration'
        ).order_by('-created_at')

        return queryset

class CampaignRetrieveUpdateDestroyAPIView(RequiredOrganizationIDMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    lookup_field = 'id'

    def get_queryset(self):
        org_snowflake_id = self.get_org_id()        
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        queryset = UnifiedCampaign.objects.filter(organization=organization).prefetch_related(
            'platform_campaigns__integration',
            'platform_campaigns__ad_groups__ads__assets',
            'ai_insights',
        )
        return queryset

    def perform_update(self, serializer):
        """Save the campaign and, if it is already live, enqueue a sync task."""
        instance = serializer.save()
        # Only push to platforms when the campaign is already published
        if instance.status not in ('DRAFT',):
            transaction.on_commit(
                lambda: sync_campaign_to_platforms_task.delay(instance.id, 'UPDATE')
            )
    
    def perform_destroy(self, instance):
        # Change permission to allow only owner or admin to delete campaign
        if not instance.organization.memberships.filter(user=self.request.user, role__in=['OWNER', 'ADMIN']).exists():
            raise PermissionDenied("You do not have permission to delete this campaign.")
        organization = instance.organization
        campaign_name = instance.name

        # Collect platform-level IDs *before* the DB row is deleted so the
        # background task can remove the ads from the real platforms.
        platform_campaign_ids = list(
            instance.platform_campaigns
            .filter(platform_campaign_id__isnull=False)
            .values_list('id', flat=True)
        )

        instance.delete()

        # Fire-and-forget: delete the ads from each platform in the background
        if platform_campaign_ids:
            from main.tasks import delete_campaign_from_platforms_task
            transaction.on_commit(
                lambda: delete_campaign_from_platforms_task.delay(platform_campaign_ids)
            )

        from accounts.notifications import notify_org_members
        notify_org_members(
            organization,
            f"Campaign \"{campaign_name}\" has been deleted.",
            setting_key='campaign_performance',
        )


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ],
    request=None,
    responses={200: None},
)
class CampaignToggleStatusAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST /campaigns/<id>/toggle-status/ — toggle between ACTIVE and PAUSED.

    Rules:
    - DRAFT campaigns cannot be toggled (they are not live on any platform).
    - ARCHIVED / ERROR campaigns are rejected as well.
    - On success the unified campaign status is updated immediately and a
      background task propagates the change to every connected platform.
    """
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from main.tasks import toggle_campaign_status_task

        campaign_id = kwargs.get('id')
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        campaign = UnifiedCampaign.objects.filter(
            id=campaign_id, organization=organization
        ).first()
        if not campaign:
            raise ValidationError({'campaign_id': 'Campaign not found.'})

        TOGGLEABLE = {'ACTIVE', 'PAUSED'}
        if campaign.status not in TOGGLEABLE:
            return Response(
                {
                    'error': (
                        f"Cannot toggle a campaign with status '{campaign.status}'. "
                        "Only ACTIVE or PAUSED campaigns can be toggled."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_status = 'PAUSED' if campaign.status == 'ACTIVE' else 'ACTIVE'

        # Update the unified status immediately so the UI reflects the change
        campaign.status = target_status
        campaign.save(update_fields=['status', 'updated_at'])

        # Propagate to platforms in the background
        toggle_campaign_status_task.delay(campaign.id, target_status)

        # Notify org owner/admins of the status change
        from accounts.notifications import notify_org_members
        notify_org_members(
            organization,
            f"Campaign \"{campaign.name}\" status changed to {target_status.lower()}.",
            setting_key='campaign_performance',
        )

        return Response(
            {
                'campaign_id': campaign.id,
                'status': target_status,
                'message': f"Campaign is now {target_status.lower()}. "
                           "Platform changes are being applied in the background.",
            },
            status=status.HTTP_200_OK,
        )


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
class CreateAdAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = CreateAdSerializer

    REQUIRED_FIELDS_FOR_PUBLISH = [
        'platforms', 'campaign_name', 'objective', 'budgets',
        'min_age', 'max_age', 'gender', 'locations', 'keywords',
        'ad_name', 'headline', 'primary_text', 'description',
        'call_to_action', 'destination_url'
    ]

    def _budget_to_minor_units(self, value):
        """Normalize incoming budget (dollars) to minor units (cents)."""
        try:
            return int(round(float(value) * 100))
        except (TypeError, ValueError):
            raise ValidationError({'budget': 'Invalid budget value.'})

    def post(self, request, *args, **kwargs):
        serializer = CreateAdSerializer(data=request.data, context={'request': request})
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        

        campaign_id = data.pop('campaign_id', None)
        is_draft = data.pop('draft', True)
        ad_file = data.pop('ad_file', None)

        if campaign_id:
            campaign = self._update_campaign(campaign_id, organization, data, ad_file)
            response_status = status.HTTP_200_OK
        else:
            campaign = self._create_draft(organization, data, ad_file)
            response_status = status.HTTP_201_CREATED

        if not is_draft:
            self._publish_campaign(campaign, organization)

        campaign.refresh_from_db()
        return Response(
            self._get_campaign_data(campaign, request=request),
            status=response_status,
        )

    def _create_draft(self, organization, data, ad_file=None):
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

    def _update_campaign(self, campaign_id, organization, data, ad_file=None):
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

    def _prepare_for_json(self, data):
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
                except ValidationError as e:
                    pass
    def _get_campaign_data(self, campaign, request=None):
        """Return the same payload shape as the single-campaign retrieve endpoint."""
        serializer = CampaignSerializer(campaign, context={'request': request})
        return serializer.data


    def _publish_campaign(self, campaign, organization):
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
        from accounts.notifications import notify_org_members
        notify_org_members(
            organization,
            f"Campaign \"{campaign.name}\" has been published and is now live.",
            setting_key='campaign_performance',
        )


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
def _increment_ai_usage(organization):
    """Increment the ai_copy_generator UsageRecord for the org's active billing period."""
    subscription = (
        Subscription.objects
        .filter(organization=organization, status__in=['active', 'trialing'])
        .order_by('-created_at')
        .first()
    )
    if not subscription or not subscription.current_period_start:
        return
    record, _ = UsageRecord.objects.get_or_create(
        organization=organization,
        subscription=subscription,
        feature_key='ai_copy_generator',
        period_start=subscription.current_period_start,
        period_end=subscription.current_period_end,
        defaults={'used': 0},
    )
    UsageRecord.objects.filter(pk=record.pk).update(used=models.F('used') + 1)


class AICopyGeneratorAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = AICopyRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        generated_copy = generate_copy(
            product=data['product'],
            audience=data['audience'],
            benefits=data['benefits'],
            tone=data['tone'],
            copy_type=data['copy_type']
        )
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if organization:
            _increment_ai_usage(organization)
        return Response({'generated_copies': generated_copy}, status=status.HTTP_200_OK)


class AIAdCopyGeneratorAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = AIAdCopySerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        data = serializer.validated_data
        generated_copy = generate_ad_copy(
            product_service=data['product_service'],
            target_audience=data['target_audience'],
            key_benefits=data['key_benefits'],
            tone=data['tone']
        )
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if organization:
            _increment_ai_usage(organization)
        return Response({'Ad copy': generated_copy}, status=status.HTTP_200_OK)

class AIInsightPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 20

class AIInsightListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
    serializer_class = AIInsightSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    pagination_class = AIInsightPagination

    def get_queryset(self):
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        queryset = organization.ai_insights.order_by('-created_at')
        return queryset


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
class AnalyticsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        data = get_analytics_data(snowflake_id)
        return Response(data, status=status.HTTP_200_OK)

@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
class CreatePlatformCampaignAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from .utils.tiktok_handler import create_platform_campaign_for_tiktok
        campaign_id = request.data.get('campaign_id')
        campaign = UnifiedCampaign.objects.get(id=campaign_id)
        create_full_ad_for_tiktok(campaign, campaign.organization.integrations.get(platform='TIKTOK'))
        # Implementation for creating platform-specific campaigns
        return Response({'message': 'Platform campaign created successfully'}, status=status.HTTP_201_CREATED)  

@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)

@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
class TeamAPIView(generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = TeamMemberSerializer

    def get(self, request, *args, **kwargs):
        org_snowflake_id = request.query_params.get('org_id')
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        
        data = OrganizationMember.objects.filter(organization=organization).aggregate(
            total_members=models.Count('id'),
            active_members=models.Count('id', filter=models.Q(user__is_active=True)),
            inactive_members=models.Count('id', filter=models.Q(user__is_active=False)),
            pending_invitations=models.Count('id', filter=models.Q(status='PENDING'))
        )

        return Response(data, status=status.HTTP_200_OK)

@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
class TeamMemberListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
    serializer_class = TeamMemberSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get_queryset(self):
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        queryset = OrganizationMember.objects.filter(organization=organization).select_related('user')
        return queryset

@extend_schema(
    parameters=[
        OpenApiParameter(
            name="org_id",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            required=True,
            description="Organization Snowflake ID"
        )
    ]
)
class UpdateDeleteTeamMemberAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TeamMemberSerializer
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]
    lookup_field = 'id'

    def get_queryset(self):
        org_snowflake_id = self.request.query_params.get('org_id')
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        # TODO: Ensure authority to update/delete team members
        queryset = OrganizationMember.objects.filter(organization=organization).select_related('user')
        return queryset
    
    # override update and delete for ownership sothat admin can't make owner or delete owner
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.role == 'OWNER':
            return Response({'error': 'Cannot modify the owner of the organization.'}, status=status.HTTP_403_FORBIDDEN)
        member_user = instance.user
        organization = instance.organization
        old_role = instance.role
        new_role = request.data.get('role', old_role)
        response = super().update(request, *args, **kwargs)
        if member_user and new_role != old_role:
            from accounts.notifications import notify_user
            notify_user(
                member_user,
                f"Your role in {organization.name} has been updated to {new_role}.",
                organization=organization,
                setting_key='team_activity',
            )
        return response

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.role == 'OWNER':
            return Response({'error': 'Cannot delete the owner of the organization.'}, status=status.HTTP_403_FORBIDDEN)
        member_user = instance.user
        organization = instance.organization
        response = super().destroy(request, *args, **kwargs)
        if member_user:
            from accounts.notifications import notify_user
            notify_user(
                member_user,
                f"You have been removed from {organization.name}.",
                setting_key='team_activity',
            )
        return response

class TeamInvitationAPIView(generics.GenericAPIView):
    serializer_class = TeamMemberInviteSerializer
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        org_snowflake_id = request.query_params.get('org_id')
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        
        email = data['email']
        role = data['role']

        user = User.objects.filter(email=email).first()
        if user:
            if OrganizationMember.objects.filter(user=user, organization=organization).exists():
                return Response({'error': 'User is already a member of the organization.'}, status=status.HTTP_400_BAD_REQUEST)
            if user.is_staff or user.is_superuser:
                return Response({'error': 'Cannot invite admin or superuser as organization member.'}, status=status.HTTP_400_BAD_REQUEST)
        invitation = TeamInvitation.objects.create(
            email=email,
            role=role,
            organization=organization,
            invited_by=request.user
        )
        invite_link = f"{settings.FRONTEND_URL}/accept-invite/{invitation.token}/"
        
        try:
            send_team_invitation_email(
                invitee_email=email,
                inviter_name=request.user.full_name or request.user.email,
                organization_name=organization.name,
                invite_link=invite_link
            )
        except Exception as e:
            # Continue even if email fails
            pass

        # In-app notification: if the invitee already has an account, notify them
        from accounts.notifications import notify_user, notify_org_members
        if user:
            notify_user(
                user,
                f"You have been invited to join {organization.name} as {role} by {request.user.full_name or request.user.email}.",
                organization=organization,
                setting_key='team_activity',
            )
        # Notify org owner/admins that an invitation was sent
        notify_org_members(
            organization,
            f"{email} has been invited to join the organization as {role}.",
            setting_key='team_activity',
        )

        return Response({'message': 'Invitation sent successfully'}, status=status.HTTP_200_OK)


class InvitationAcceptAPIView(APIView):
    permission_classes = [IsRegularPlatformUser|AllowAny]

    def post(self, request, *args, **kwargs):
        token = kwargs.get('token')
        from django.core.exceptions import ValidationError
        try:
            invitation = TeamInvitation.objects.filter(token=token, status='PENDING').first()
        except (ValidationError, ValueError):
            return Response({'error': 'Invalid or expired invitation token.'}, status=status.HTTP_400_BAD_REQUEST)
        if not invitation:
            return Response({'error': 'Invalid or expired invitation token.'}, status=status.HTTP_400_BAD_REQUEST)
        if not User.objects.filter(email=invitation.email).exists():
            # Create a temporary user and send them email and password
            temp_password = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=10))
            user = User.objects.create_user(
                email=invitation.email,
                password=temp_password,
                is_active=True
            )
            
            try:
                # Send account creation email with HTML template
                send_account_created_email(
                    user_email=invitation.email,
                    temp_password=temp_password,
                    organization_name=invitation.organization.name
                )
            except Exception as e:
                pass
        else:
            user = User.objects.filter(email=invitation.email).first()

        if OrganizationMember.objects.filter(user=user, organization=invitation.organization).exists():
            return Response({'error': 'You are already a member of this organization.'}, status=status.HTTP_400_BAD_REQUEST)
        
        OrganizationMember.objects.create(
            user=user,
            organization=invitation.organization,
            role=invitation.role,
            status='ACTIVE'
        )
        invitation.status = 'ACCEPTED'
        invitation.save()

        # Notify org owner/admins of the new member, and the inviter specifically
        from accounts.notifications import notify_org_members, notify_user
        notify_org_members(
            invitation.organization,
            f"{user.email} has joined the organization as {invitation.role}.",
            setting_key='team_activity',
        )
        if invitation.invited_by and invitation.invited_by != user:
            notify_user(
                invitation.invited_by,
                f"{user.email} accepted your invitation to join {invitation.organization.name}.",
                organization=invitation.organization,
                setting_key='team_activity',
            )

        return Response({'message': f'You have successfully joined the organization {invitation.organization.name} as a {invitation.role}.'}, status=status.HTTP_200_OK)

class IntegrationStatusAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        
        # show META, GOOGLE, TIKTOK integrations with their status and created at even if they are no objects for that platform
        integrations = []
        platforms = ['META', 'GOOGLE', 'TIKTOK']
        for platform in platforms:
            integration = organization.integrations.filter(platform=platform).first()
            if integration:
                integrations.append({
                    'platform': platform,
                    'status': True,
                    'created_at': integration.created_at
                })
            else:
                integrations.append({
                    'platform': platform,
                    'status': False,
                    'created_at': None
                })

        return Response({'integrations': integrations}, status=status.HTTP_200_OK)

class SyncAdsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        integrations = organization.integrations.filter(is_active=True)
        if not integrations.exists():
            return Response({'error': 'No active platform integrations found for this organization.'}, status=status.HTTP_400_BAD_REQUEST)

        dispatched = 0
        for integration in integrations:
            if integration.platform.upper() == 'GOOGLE':
                continue
            sync_ads_task.delay(integration.id)
            dispatched += 1

        if dispatched == 0:
            return Response({'error': 'No supported active integrations found.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': 'Ad sync initiated successfully'}, status=status.HTTP_200_OK)

class SyncAnalyticsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST {org_id, ?platform, ?start_date, ?end_date} — trigger analytics sync."""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from main.tasks import sync_analytics_task

        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        platform_filter = request.data.get('platform', '').upper()
        start_date = request.data.get('start_date')  # "YYYY-MM-DD"
        end_date = request.data.get('end_date')        # "YYYY-MM-DD"

        integrations = organization.integrations.filter(is_active=True)
        if platform_filter:
            integrations = integrations.filter(platform=platform_filter)

        if not integrations.exists():
            return Response(
                {'error': 'No active integrations found.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        dispatched = 0
        for integration in integrations:
            if integration.platform.upper() == 'GOOGLE':
                continue
            sync_analytics_task.delay(integration.id, start_date, end_date)
            dispatched += 1

        if dispatched == 0:
            return Response(
                {'error': 'No supported integrations found (Google analytics not yet supported).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response({
            'message': f'Analytics sync initiated for {dispatched} integration(s).',
        }, status=status.HTTP_200_OK)


# ════════════════════════════════════════════════════════════
#  META AD MANAGEMENT — TEST ENDPOINTS
# ════════════════════════════════════════════════════════════

class MetaCreateAdTestAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST {org_id, campaign_id, ?ad_asset_id}"""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from main.utils.meta_engine.manage_ad import create_ad_on_meta, MetaAdCreationError

        campaign_id = request.data.get('campaign_id')
        ad_asset_id = request.data.get('ad_asset_id')

        if not campaign_id:
            return Response(
                {'error': 'campaign_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ad_asset = None
        if ad_asset_id:
            ad_asset = AdAsset.objects.filter(id=ad_asset_id).first()

        try:
            local_ad = create_ad_on_meta(
                unified_campaign_id=int(campaign_id),
                ad_asset=ad_asset,
            )
            return Response({
                'message': 'Meta ad created successfully.',
                'ad_id': local_ad.id,
                'platform_ad_id': local_ad.platform_ad_id,
                'ad_name': local_ad.name,
            }, status=status.HTTP_201_CREATED)
        except MetaAdCreationError as exc:
            return Response({
                'error': str(exc),
                'stage': exc.stage,
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MetaUpdateCampaignTestAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST {org_id, campaign_id, ?ad_asset_id}"""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from main.utils.meta_engine.manage_ad import update_campaign_on_meta

        campaign_id = request.data.get('campaign_id')
        ad_asset_id = request.data.get('ad_asset_id')

        if not campaign_id:
            return Response(
                {'error': 'campaign_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ad_asset = None
        if ad_asset_id:
            ad_asset = AdAsset.objects.filter(id=ad_asset_id).first()

        try:
            result = update_campaign_on_meta(
                unified_campaign_id=int(campaign_id),
                ad_asset=ad_asset,
            )
            # result is either an Ad (if fallback to create) or None
            data = {'message': 'Meta campaign updated successfully.'}
            if result:
                data['ad_id'] = result.id
                data['platform_ad_id'] = result.platform_ad_id
            return Response(data, status=status.HTTP_200_OK)
        except Exception as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class MetaDeleteAdTestAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST {org_id, campaign_id, ?delete_level}"""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from main.utils.meta_engine.manage_ad import delete_ad_on_meta

        campaign_id = request.data.get('campaign_id')
        delete_level = request.data.get('delete_level', 'CAMPAIGN').upper()

        if not campaign_id:
            return Response(
                {'error': 'campaign_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if delete_level not in ('CAMPAIGN', 'ADSET', 'AD'):
            return Response(
                {'error': 'delete_level must be CAMPAIGN, ADSET, or AD.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            errors = delete_ad_on_meta(
                unified_campaign_id=int(campaign_id),
                delete_level=delete_level,
            )
            if errors:
                return Response({
                    'message': f'Deletion completed with {len(errors)} error(s).',
                    'errors': errors,
                }, status=status.HTTP_207_MULTI_STATUS)
            return Response(
                {'message': f'Meta {delete_level.lower()} deleted successfully.'},
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            return Response(
                {'error': str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PlatformCreateAdTestAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """
    POST {org_id, platform, campaign_id, ?ad_asset_id}

    Test-only endpoint to trigger real provider-side ad creation for one
    UnifiedCampaign on one platform.
    """
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from main.utils.meta_engine.manage_ad import MetaAdCreationError

        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        platform = str(request.data.get('platform', '')).upper()
        campaign_id = request.data.get('campaign_id')
        ad_asset_id = request.data.get('ad_asset_id')
        update_campaign = str(request.data.get('update_campaign', '')).lower() in ('1', 'true', 'yes', 'on')

        if platform not in ('META', 'TIKTOK', 'GOOGLE'):
            return Response(
                {'error': 'platform must be one of: META, TIKTOK, GOOGLE.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not campaign_id:
            return Response(
                {'error': 'campaign_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        campaign = UnifiedCampaign.objects.filter(
            id=campaign_id,
            organization=organization,
        ).first()
        if not campaign:
            return Response(
                {'error': 'Campaign not found for this organization.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        integration = (
            organization.integrations
            .filter(platform=platform, is_active=True)
            .order_by('-created_at', '-id')
            .first()
        )
        if not integration:
            return Response(
                {'error': f'No active {platform} integration found.'},
                status=status.HTTP_400_BAD_REQUEST,
            )


        ad_asset = None
        if ad_asset_id:
            ad_asset = AdAsset.objects.filter(id=ad_asset_id, organization=organization).first()
            if not ad_asset:
                return Response(
                    {'error': 'ad_asset_id is invalid for this organization.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            if platform == 'META':
                from main.utils.meta_engine.manage_ad import create_ad_on_meta

                local_ad = create_ad_on_meta(
                    unified_campaign_id=int(campaign.id),
                    ad_asset=ad_asset,
                )
                return Response({
                    'message': 'Meta ad creation triggered successfully.',
                    'platform': 'META',
                    'campaign_id': campaign.id,
                    'ad_id': local_ad.id,
                    'platform_ad_id': local_ad.platform_ad_id,
                }, status=status.HTTP_201_CREATED)

            if platform == 'GOOGLE':
                from main.utils.google_engine.manage_ad import create_ad_on_google

                local_ad = create_ad_on_google(
                    unified_campaign_id=int(campaign.id),
                    ad_asset=ad_asset,
                )
                return Response({
                    'message': 'Google ad creation triggered successfully.',
                    'platform': 'GOOGLE',
                    'campaign_id': campaign.id,
                    'ad_id': local_ad.id,
                    'platform_ad_id': local_ad.platform_ad_id,
                }, status=status.HTTP_201_CREATED)

            # TikTok path
            from main.models import PlatformCampaign
            from main.utils.tiktok_handler import create_full_ad_for_tiktok

            platform_campaign = PlatformCampaign.objects.filter(
                unified_campaign=campaign,
                integration=integration,
            ).order_by('-updated_at', '-id').first()

            if not platform_campaign:
                return Response(
                    {
                        'error': (
                            'No local TIKTOK PlatformCampaign found for this unified campaign. '
                            'Publish/create the campaign first so ad group scaffolding exists.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not platform_campaign.ad_groups.exists():
                return Response(
                    {
                        'error': (
                            'No local TIKTOK AdGroup found for this campaign. '
                            'Create local ad group scaffolding first.'
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            force_recreate_campaign = not bool(platform_campaign.platform_campaign_id)

            result = create_full_ad_for_tiktok(
                campaign,
                integration,
                force_recreate_campaign=force_recreate_campaign,
                update_existing_campaign=update_campaign,
                ad_asset=ad_asset,
            )
            platform_campaign.refresh_from_db()
            first_adgroup = platform_campaign.ad_groups.first()

            is_update = bool(update_campaign and platform_campaign.platform_campaign_id)

            return Response({
                'message': (
                    'TikTok campaign/adgroup update triggered successfully.'
                    if is_update
                    else 'TikTok campaign/adgroup creation triggered successfully.'
                ),
                'platform': 'TIKTOK',
                'campaign_id': campaign.id,
                'platform_campaign_id': (result or {}).get('campaign_id') or platform_campaign.platform_campaign_id,
                'platform_adgroup_id': (result or {}).get('adgroup_id') or (first_adgroup.platform_adgroup_id if first_adgroup else None),
                'ad_id': (result or {}).get('ad_id'),
                'platform_ad_id': (result or {}).get('platform_ad_id'),
            }, status=status.HTTP_201_CREATED)

        except ValueError as exc:
            return Response(
                {
                    'error': str(exc),
                    'platform': platform,
                    'campaign_id': campaign.id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except MetaAdCreationError as exc:
            return Response(
                {
                    'error': str(exc),
                    'stage': exc.stage,
                    'platform': platform,
                    'campaign_id': campaign.id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as exc:
            return Response(
                {
                    'error': str(exc),
                    'platform': platform,
                    'campaign_id': campaign.id,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

