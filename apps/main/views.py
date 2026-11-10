from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.response import Response
from rest_framework import generics, status
from apps.main.utils.tiktok_handler import create_full_ad_for_tiktok
from .services import AdCreationService, CampaignService, DashboardService, AIService, TeamService
from .serializers import (
    AIAdCopySerializer, AIInsightDetailSerializer, AudienceReachRequestSerializer, AIOptimizationSettingsSerializer, CampaignSerializer, CreateAdSerializer, AICopyRequestSerializer, OrganizationSerializer, TeamMemberInviteSerializer, TeamMemberSerializer, AIInsightSerializer, TempCampaignSerializer
)
from .models import AdAsset, UnifiedCampaign, Organization, CampaignBudget
from apps.accounts.permissions import IsAdminOrOwnerOfOrganization, IsRegularPlatformUser, IsOrganizationMember
from rest_framework.filters import SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from .mixins import RequiredOrganizationIDMixin
from .utils.user_pages import get_campaign_list_extras
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView



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
        
        time_range = request.query_params.get('time_range', 'last_30_days')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        data = DashboardService().get_dashboard_data(
            organization,
            time_range=time_range,
            start_date=start_date,
            end_date=end_date
        )
        return Response(data, status=status.HTTP_200_OK)

class CampaignPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

class CampaignListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
    serializer_class = TempCampaignSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    filter_backends = [SearchFilter, DjangoFilterBackend]
    pagination_class = CampaignPagination
    search_fields = ['name', 'objective']
    filterset_fields = ['status']

    def get_queryset(self):
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        return CampaignService().get_campaign_list_queryset(organization)

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        # Trend + sparkline data for the campaigns on this page only (single query).
        ids = [c.id for c in (page if page is not None else queryset)]
        self._campaign_extras = get_campaign_list_extras(ids)
        return page

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['campaign_extras'] = getattr(self, '_campaign_extras', {})
        return context

class CampaignRetrieveUpdateDestroyAPIView(RequiredOrganizationIDMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = CampaignSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    lookup_field = 'id'

    def get_queryset(self):
        org_snowflake_id = self.get_org_id()        
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        return CampaignService().get_campaign_detail_queryset(organization)

    def perform_update(self, serializer):
        instance = serializer.save()
        CampaignService().update_campaign_instance(instance)
    
    def perform_destroy(self, instance):
        CampaignService().delete_campaign(instance, self.request.user)


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
        campaign_id = kwargs.get('id')
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        result = CampaignService().toggle_campaign_status(campaign_id, organization)
        return Response(result, status=status.HTTP_200_OK)


class CreateAdAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = CreateAdSerializer

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

        service = AdCreationService()
        if campaign_id:
            campaign = service.update_campaign(campaign_id, organization, data, ad_file)
            response_status = status.HTTP_200_OK
        else:
            campaign = service.create_draft(organization, data, ad_file)
            response_status = status.HTTP_201_CREATED

        if not is_draft:
            service.publish_campaign(campaign, organization)

        campaign.refresh_from_db()
        return Response(
            self._get_campaign_data(campaign, request=request),
            status=response_status,
        )

    def _get_campaign_data(self, campaign, request=None):
        """Return the same payload shape as the single-campaign retrieve endpoint."""
        serializer = CampaignSerializer(campaign, context={'request': request})
        return serializer.data


class AICopyGeneratorAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = AICopyRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        
        generated_copy = AIService().generate_copy(
            organization=organization,
            product=data['product'],
            audience=data['audience'],
            benefits=data['benefits'],
            tone=data['tone'],
            copy_type=data['copy_type']
        )
        return Response({'generated_copies': generated_copy}, status=status.HTTP_200_OK)


class AIAdCopyGeneratorAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = AIAdCopySerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
        data = serializer.validated_data
        
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        
        generated_copy = AIService().generate_ad_copy(
            organization=organization,
            product_service=data['product_service'],
            target_audience=data['target_audience'],
            key_benefits=data['key_benefits'],
            tone=data['tone']
        )
        return Response({'Ad copy': generated_copy}, status=status.HTTP_200_OK)

class AIInsightPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 20

class AIInsightListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
    serializer_class = AIInsightDetailSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    pagination_class = AIInsightPagination

    def get_organization(self):
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        return organization

    def get_queryset(self):
        return AIService().get_ai_insights_queryset(self.get_organization()).select_related('campaign')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update(getattr(self, '_insight_context', {}))
        return context

    def paginate_queryset(self, queryset):
        page = super().paginate_queryset(queryset)
        self._insight_context = AIService().get_insight_serializer_context(
            self.get_organization(), page if page is not None else queryset
        )
        return page

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        organization = self.get_organization()
        service = AIService()
        optimization_settings = service.get_optimization_settings(organization)
        response.data['last_optimization'] = optimization_settings.last_optimization_at
        response.data['summary'] = service.get_optimization_summary(organization)
        response.data['potential_impact'] = service.get_potential_impact(organization)
        return response


class AIOptimizationSettingsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """GET/PATCH /main/ai-optimization/settings/ — AI Control Center preferences."""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = AIOptimizationSettingsSerializer

    def _organization(self):
        organization = Organization.objects.filter(snowflake_id=self.get_org_id()).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        return organization

    def get(self, request, *args, **kwargs):
        instance = AIService().get_optimization_settings(self._organization())
        return Response(self.get_serializer(instance).data)

    def patch(self, request, *args, **kwargs):
        organization = self._organization()
        if not organization.memberships.filter(user=request.user, role__in=['OWNER', 'ADMIN']).exists():
            raise PermissionDenied("You do not have permission to change AI optimization settings.")
        instance = AIService().get_optimization_settings(organization)
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class AIOptimizationHistoryAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """GET /main/ai-optimization/history/ — recent optimization activity."""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        organization = Organization.objects.filter(snowflake_id=self.get_org_id()).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        results = AIService().get_optimization_history(organization)
        return Response({'count': len(results), 'results': results})


class AIOptimizationRunAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST /main/ai-optimization/run/ — the "Optimize Now" button."""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = AIOptimizationSettingsSerializer

    def post(self, request, *args, **kwargs):
        organization = Organization.objects.filter(snowflake_id=self.get_org_id()).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        instance = AIService().run_optimization(organization)
        return Response({
            'message': 'AI Optimization check complete! Recommendations updated.',
            **self.get_serializer(instance).data,
        })


class AnalyticsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        chart_range = request.query_params.get('range', '6M')
        data = DashboardService().get_analytics_data(snowflake_id, chart_range=chart_range)
        return Response(data, status=status.HTTP_200_OK)

class AudienceReachEstimateAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST /main/audience-reach-estimate/ — "Estimated reach" card on the audience step."""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = AudienceReachRequestSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # TODO: replace this heuristic with the platforms' reach-estimate APIs
        # (Meta delivery_estimate, TikTok reach_frequency, Google keyword planner).
        base_min, base_max = 630, 960
        if data['gender'] != 'all':
            base_min -= 50
            base_max -= 80
        if len(data['keywords']) > 10:
            base_min += 150
            base_max += 290
        # Narrower age band -> smaller audience.
        span = max(1, data['max_age'] - data['min_age'])
        scale = min(1.0, max(0.2, span / 47))
        base_min, base_max = int(base_min * scale), int(base_max * scale)

        return Response({
            'min_reach': base_min * 1000,
            'max_reach': base_max * 1000,
            'min_label': f"{base_min}K",
            'max_label': f"{base_max}K",
            'progress': min(90, max(40, base_min / 10)),
            'is_estimate': True,
        })


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

class TeamAPIView(generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]
    serializer_class = TeamMemberSerializer

    def get(self, request, *args, **kwargs):
        org_snowflake_id = request.query_params.get('org_id')
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        
        data = TeamService().get_team_stats(organization)
        return Response(data, status=status.HTTP_200_OK)

class TeamMemberListAPIView(RequiredOrganizationIDMixin, generics.ListAPIView):
    serializer_class = TeamMemberSerializer
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get_queryset(self):
        org_snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        return TeamService().get_team_members_queryset(organization)

class UpdateDeleteTeamMemberAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TeamMemberSerializer
    permission_classes = [IsRegularPlatformUser, IsAdminOrOwnerOfOrganization]
    lookup_field = 'id'

    def get_queryset(self):
        org_snowflake_id = self.request.query_params.get('org_id')
        organization = Organization.objects.filter(snowflake_id=org_snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        return TeamService().get_team_members_queryset(organization)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        new_role = request.data.get('role', instance.role)
        return TeamService().update_team_member(instance, new_role, self.request.user)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        return TeamService().delete_team_member(instance)

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
        
        TeamService().invite_team_member(
            organization=organization,
            email=data['email'],
            role=data['role'],
            invited_by=request.user
        )

        return Response({'message': 'Invitation sent successfully'}, status=status.HTTP_200_OK)


class InvitationAcceptAPIView(APIView):
    permission_classes = [IsRegularPlatformUser|AllowAny]

    def post(self, request, *args, **kwargs):
        token = kwargs.get('token')
        organization, role = TeamService().accept_invitation(token)
        return Response({'message': f'You have successfully joined the organization {organization.name} as a {role}.'}, status=status.HTTP_200_OK)

class IntegrationStatusAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def get(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        
        integrations = DashboardService().get_integration_status(organization)
        return Response({'integrations': integrations}, status=status.HTTP_200_OK)

class SyncAdsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})
        
        result = CampaignService().sync_ads(organization)
        return Response(result, status=status.HTTP_200_OK)

class SyncAnalyticsAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST {org_id, ?platform, ?start_date, ?end_date} — trigger analytics sync."""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        platform_filter = request.data.get('platform', '')
        start_date = request.data.get('start_date')  # "YYYY-MM-DD"
        end_date = request.data.get('end_date')        # "YYYY-MM-DD"

        result = CampaignService().sync_analytics(organization, platform_filter, start_date, end_date)
        return Response(result, status=status.HTTP_200_OK)


# ════════════════════════════════════════════════════════════
#  META AD MANAGEMENT — TEST ENDPOINTS
# ════════════════════════════════════════════════════════════

class MetaCreateAdTestAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    """POST {org_id, campaign_id, ?ad_asset_id}"""
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        from apps.main.utils.meta_engine.manage_ad import create_ad_on_meta, MetaAdCreationError

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
        from apps.main.utils.meta_engine.manage_ad import update_campaign_on_meta

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
        from apps.main.utils.meta_engine.manage_ad import delete_ad_on_meta

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
        from apps.main.utils.meta_engine.manage_ad import MetaAdCreationError

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
                from apps.main.utils.meta_engine.manage_ad import create_ad_on_meta

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
                from apps.main.utils.google_engine.manage_ad import create_ad_on_google

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
            from apps.main.models import PlatformCampaign
            from apps.main.utils.tiktok_handler import create_full_ad_for_tiktok

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


class ApplyBudgetRecommendationAPIView(RequiredOrganizationIDMixin, generics.GenericAPIView):
    permission_classes = [IsRegularPlatformUser, IsOrganizationMember]

    def post(self, request, *args, **kwargs):
        snowflake_id = self.get_org_id()
        organization = Organization.objects.filter(snowflake_id=snowflake_id).first()
        if not organization:
            raise ValidationError({'org_id': 'Invalid organization id'})

        user = request.user
        if not organization.memberships.filter(user=user, role__in=['OWNER', 'ADMIN']).exists():
            raise PermissionDenied("You do not have permission to modify campaign budgets.")

        campaign_id = request.data.get('campaign_id')
        increase_amount = float(request.data.get('increase_amount', 50.0))

        campaign = None
        if campaign_id:
            campaign = UnifiedCampaign.objects.filter(id=campaign_id, organization=organization).first()
        if not campaign:
            campaign = UnifiedCampaign.objects.filter(organization=organization).first()

        campaign_name = campaign.name if campaign else "Campaign"

        # Update campaign budget if exists
        # TODO: dispatch celery task to sync updated budget to Meta/Google/TikTok Marketing APIs
        new_daily_budget = None
        if campaign:
            budget = CampaignBudget.objects.filter(campaign=campaign).first()
            if budget:
                budget.daily_budget_minor += int(increase_amount * 100)
                budget.save()
                new_daily_budget = round(budget.daily_budget_minor / 100, 2)

        return Response({
            'status': 'success',
            'message': f"Budget recommendation applied successfully for '{campaign_name}'!",
            'campaign_id': campaign.id if campaign else campaign_id,
            'campaign_name': campaign_name,
            'increase_amount': increase_amount,
            'new_daily_budget': new_daily_budget,
        }, status=status.HTTP_200_OK)

