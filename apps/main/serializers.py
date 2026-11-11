from apps.accounts.serializers import SimpleUserSerializer
from apps.main.models import (
    BudgetType,
    Organization,
    OrganizationMember,
    UnifiedCampaign,
    UnifiedObjective,
    AIInsight,
    Ad,
    AdAsset,
    PlatformSyncEvent,
    AIOptimizationSettings,
)
from rest_framework import serializers
from datetime import timedelta
from django.db import models
from apps.finance.models import Payment
from apps.analysis.models import AnalysisDaily
from apps.main.utils.helper import get_performance_matrics, preprocess_multipart_data
from .services import AdCreationService

class PlatformAdAssetSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = AdAsset
        fields = ['id', 'file_url', 'file_type', 'status']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file:
            return request.build_absolute_uri(obj.file.url) if request else obj.file.url
        return None


class PlatformAdSerializer(serializers.ModelSerializer):
    matrics = serializers.SerializerMethodField()
    assets = serializers.SerializerMethodField()

    class Meta:
        model = Ad
        fields = [
            'id', 'name', 'status',
            'headline', 'primary_text', 'description',
            'destination_url', 'call_to_action', 'preview_link',
            'assets', 'matrics',
        ]

    def get_matrics(self, obj):
        # AnalysisDaily stores the *provider's* ad-group / campaign ids (strings), not local PKs.
        ad_group = obj.ad_group
        platform_campaign = ad_group.platform_campaign
        if not ad_group.platform_adgroup_id:
            return get_performance_matrics(AnalysisDaily.objects.none())
        analysis = AnalysisDaily.objects.filter(
            organization_id=platform_campaign.unified_campaign.organization_id,
            platform=platform_campaign.integration.platform,
            campaign_id=platform_campaign.platform_campaign_id,
            adgroup_id=ad_group.platform_adgroup_id,
        )
        return get_performance_matrics(analysis)

    def get_assets(self, obj):
        return PlatformAdAssetSerializer(
            obj.assets.all(), many=True, context=self.context
        ).data

class TempCampaignSerializer(serializers.ModelSerializer):
    platforms = serializers.SerializerMethodField()
    total_budget = serializers.SerializerMethodField()
    total_spent = serializers.FloatField(source='_total_spent', read_only=True)
    impressions = serializers.IntegerField(source='_impressions', read_only=True)
    clicks = serializers.IntegerField(source='_clicks', read_only=True)
    conversions = serializers.IntegerField(source='_conversions', read_only=True)
    ctr = serializers.SerializerMethodField()
    roas = serializers.SerializerMethodField()
    ctr_trend = serializers.SerializerMethodField()
    conversions_trend = serializers.SerializerMethodField()
    roas_trend = serializers.SerializerMethodField()
    sparkline_data = serializers.SerializerMethodField()

    class Meta:
        model = UnifiedCampaign
        fields = '__all__'

    def _extras(self, obj):
        # Populated per page by CampaignListAPIView.paginate_queryset (one query per page).
        return (self.context.get('campaign_extras') or {}).get(obj.id, {})

    def get_ctr_trend(self, obj):
        return self._extras(obj).get('ctr_trend')

    def get_conversions_trend(self, obj):
        return self._extras(obj).get('conversions_trend')

    def get_roas_trend(self, obj):
        return self._extras(obj).get('roas_trend')

    def get_sparkline_data(self, obj):
        return self._extras(obj).get('sparkline_data') or []

    def get_platforms(self, obj):
        if obj.status == 'DRAFT':
            return (obj.draft_data or {}).get('platforms') or []
        return [pc.integration.platform for pc in obj.platform_campaigns.all()]

    def get_total_budget(self, obj):
        raw = getattr(obj, '_total_budget', 0) or 0
        return round(raw / 100, 2)

    def get_ctr(self, obj):
        impressions = getattr(obj, '_impressions', 0) or 0
        clicks = getattr(obj, '_clicks', 0) or 0
        return round((clicks / impressions * 100), 2) if impressions > 0 else 0

    def get_roas(self, obj):
        spend = getattr(obj, '_total_spent', 0) or 0
        weighted_roas = getattr(obj, '_weighted_roas', 0) or 0
        return round((weighted_roas / spend), 2) if spend > 0 else 0

class CampaignSerializer(serializers.ModelSerializer):
    platforms = serializers.SerializerMethodField()
    matrics = serializers.SerializerMethodField()
    ads = serializers.SerializerMethodField()
    audience_targeting = serializers.SerializerMethodField()
    ai_insights = serializers.SerializerMethodField()
    total_budget = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    remaining_budget = serializers.SerializerMethodField()
    budgets = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    platform_sync_statuses = serializers.SerializerMethodField()
    placements = serializers.SerializerMethodField()

    class Meta:
        model = UnifiedCampaign
        fields = [
            'id', 'name', 'objective', 'platforms', 'matrics', 'ads', 
            'audience_targeting', 'status', 'created_at', 'ai_insights', 
            'total_budget', 'total_spent', 'remaining_budget', 'budgets', 'file_url',
            'platform_sync_statuses', 'placements'
        ]
        # Status transitions go through /campaigns/<id>/toggle-status/ only.
        read_only_fields = ['status', 'created_at']

    def get_placements(self, obj):
        from apps.main.utils.user_pages import get_campaign_placements
        return get_campaign_placements(obj)

    def validate_objective(self, value):
        if self.instance and self.instance.status != 'DRAFT' and self.instance.objective != value:
            raise serializers.ValidationError("Objective cannot be changed once the campaign is published.")
        return value

    def get_platforms(self, obj):
        if obj.status == 'DRAFT':
            return (obj.draft_data or {}).get('platforms') or []
        return [pc.integration.platform for pc in obj.platform_campaigns.all()]

    def get_matrics(self, obj):
        if hasattr(obj, '_impressions'):
            # Return metrics using annotated fields if available
            impressions = getattr(obj, '_impressions', 0) or 0
            clicks = getattr(obj, '_clicks', 0) or 0
            conversions = getattr(obj, '_conversions', 0) or 0
            spend = getattr(obj, '_total_spent', 0) or 0
            weighted_roas_sum = getattr(obj, '_weighted_roas', 0) or 0

            return {
                'impressions': impressions,
                'clicks': clicks,
                'ctr': (clicks / impressions * 100) if impressions > 0 else 0,
                'conversions': conversions,
                'roas': (weighted_roas_sum / spend) if spend > 0 else 0,
                'cpc': (spend / clicks) if clicks > 0 else 0,
                'cpm': (spend / (impressions / 1000)) if impressions > 0 else 0,
                'cpa': (spend / conversions) if conversions > 0 else 0,
            }
        analysis = AnalysisDaily.objects.filter(unified_campaign=obj)
        analysis = get_performance_matrics(analysis)
        return analysis

    def get_ads(self, obj):
        if obj.status == 'DRAFT':
            draft = obj.draft_data or {}
            creative_fields = [
                'ad_name', 'headline', 'primary_text', 'description',
                'call_to_action', 'destination_url',
            ]
            ad_data = {k: draft.get(k) for k in creative_fields}
            # Only return if at least one creative field is populated
            if any(ad_data.values()):
                return [ad_data]
            return []

        ads = []
        for pc in obj.platform_campaigns.all():
            for ad_group in pc.ad_groups.all():
                ads.extend(ad_group.ads.all())
        return PlatformAdSerializer(ads, many=True, context=self.context).data

    def get_audience_targeting(self, obj):
        defaults = {
            'min_age': 18,
            'max_age': 65,
            'gender': 'all',
            'locations': [],
            'keywords': '',
        }
        targeting_fields = list(defaults.keys())

        if obj.status == 'DRAFT':
            draft = obj.draft_data or {}
            return {k: draft.get(k, defaults[k]) for k in targeting_fields}

        # For live campaigns, pull from the first ad group's targeting_config
        for pc in obj.platform_campaigns.all():
            for ag in pc.ad_groups.all():
                config = ag.targeting_config or {}
                if any(k in config for k in targeting_fields):
                    return {k: config.get(k, defaults[k]) for k in targeting_fields}

        return defaults
    
    def get_budgets(self, obj):
        if obj.status == 'DRAFT':
            return (obj.draft_data or {}).get('budgets') or []
        from apps.main.models import CampaignBudget
        budgets = CampaignBudget.objects.filter(campaign=obj)
        return [
            {
                'platform': b.platform,
                'budget_type': b.budget_type,
                'budget': round(b.daily_budget_minor / 100, 2),
                'start_date': b.start_date.isoformat() if b.start_date else None,
                'end_date': b.end_date.isoformat() if b.end_date else None,
                'run_continuously': b.run_continuously,
            }
            for b in budgets
        ]

    def get_ai_insights(self, obj):
        insights = obj.ai_insights.order_by('-created_at')[:5]
        return AIInsightSerializer(insights, many=True).data
    
    def get_total_budget(self, obj):
        raw = getattr(obj, '_total_budget', None)
        if raw is not None:
            return round(raw / 100, 2)
        from apps.main.models import CampaignBudget
        total = CampaignBudget.objects.filter(campaign=obj).aggregate(
            total=models.Sum('daily_budget_minor')
        )['total']
        return round((total or 0) / 100, 2)

    def get_total_spent(self, obj):
        spent = getattr(obj, '_total_spent', None)
        if spent is not None:
            return round(spent, 2)
        spent = AnalysisDaily.objects.filter(unified_campaign=obj).aggregate(
            total=models.Sum('spend')
        )['total']
        return round(spent, 2) if spent else 0

    def get_remaining_budget(self, obj):
        total_budget = self.get_total_budget(obj)
        total_spent = self.get_total_spent(obj)
        return round(total_budget - total_spent, 2)

    def get_file_url(self, obj):
        from apps.main.models import AdAsset
        request = self.context.get('request')

        def build_url(file_field):
            if request:
                return request.build_absolute_uri(file_field.url)
            return file_field.url

        # DRAFT campaigns store the asset id in draft_data
        if obj.status == 'DRAFT':
            asset_id = (obj.draft_data or {}).get('ad_asset_id')
            if not asset_id:
                return None
            asset = AdAsset.objects.filter(id=asset_id).first()
            if asset and asset.file:
                return build_url(asset.file)
            return None

        # Published campaigns: traverse the live structure
        pc = obj.platform_campaigns.first()
        if not pc:
            return None
        ag = pc.ad_groups.first()
        if not ag:
            return None
        ad = ag.ads.first()
        if not ad:
            return None
        asset = ad.assets.first()
        if not asset or not asset.file:
            return None
        return build_url(asset.file)

    def get_platform_sync_statuses(self, obj):
        latest_by_platform = {}
        events = PlatformSyncEvent.objects.filter(campaign=obj).order_by('-created_at')
        for event in events:
            if event.platform in latest_by_platform:
                continue
            latest_by_platform[event.platform] = {
                'operation': event.operation,
                'status': event.status,
                'message': event.message,
                'error_message': event.error_message,
                'updated_at': event.updated_at,
            }
        return latest_by_platform

class BudgetItemSerializer(serializers.Serializer):
    platform=serializers.CharField()
    budget_type = serializers.CharField(max_length=20)
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    budget = serializers.IntegerField()
    run_continuously = serializers.BooleanField()

    def validate_platform(self, value):
        allowed = ['META', 'GOOGLE', 'TIKTOK']
        if value not in allowed:
            raise serializers.ValidationError(f"Platform '{value}' is not supported. Allowed: {', '.join(allowed)}")
        return value

    def validate_budget_type(self, value):
        allowed = [c.value for c in BudgetType]
        if value not in allowed:
            raise serializers.ValidationError(f"Budget type '{value}' is not valid. Allowed: {', '.join(allowed)}")
        return value

    def validate_budget(self, value):
        if value <= 0:
            raise serializers.ValidationError("Budget must be a positive number.")
        return value

    def validate(self, data):
        if not data.get('run_continuously') and data.get('start_date') and data.get('end_date'):
            if data['end_date'] < data['start_date']:
                raise serializers.ValidationError({'end_date': 'End date cannot be before start date.'})
        return data


class SimpleCampaignSerializer(serializers.ModelSerializer):
    platforms = serializers.SerializerMethodField()
    class Meta:
        model = UnifiedCampaign
        fields = ['id', 'name', 'status', 'platforms', 'created_at']

    def get_platforms(self, obj):
        if obj.status == 'DRAFT':
            return (obj.draft_data or {}).get('platforms') or []
        return [pc.integration.platform for pc in obj.platform_campaigns.all()]


class CreateAdSerializer(serializers.Serializer):
    campaign_id = serializers.IntegerField(required=False)

    platforms = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False
    )
    campaign_name = serializers.CharField(max_length=100, required=False)
    objective = serializers.CharField(max_length=20, required=False)

    # budget
    budgets = BudgetItemSerializer(many=True, required=False)

    # Target audience 
    min_age = serializers.IntegerField(required=False)
    max_age = serializers.IntegerField(required=False)
    gender = serializers.CharField(required=False)
    locations = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    keywords = serializers.CharField(required=False)

    ad_name = serializers.CharField(max_length=100, required=False)
    ad_file = serializers.FileField(required=False)

    ALLOWED_IMAGE_TYPES = [
        'image/jpeg', 'image/png', 'image/gif', 'image/bmp',
        'image/webp', 'image/tiff', 'image/svg+xml', 'image/x-icon',
        'image/heif', 'image/heic', 'image/avif',
    ]
    ALLOWED_VIDEO_TYPES = [
        'video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/x-ms-wmv',
        'video/x-matroska', 'video/webm', 'video/mpeg', 'video/ogg',
        'video/3gpp', 'video/3gpp2', 'video/x-flv', 'video/mp2t',
    ]

    def validate_ad_file(self, value):
        if value:
            from django.core.exceptions import ValidationError as DjangoValidationError
            from apps.main.utils.safe_files import detect_media_type
            try:
                kind, mime = detect_media_type(value)
            except DjangoValidationError as exc:
                raise serializers.ValidationError(exc.messages)
            # Never trust the client-declared type: overwrite it with what we detected.
            value.content_type = mime
        return value

    headline = serializers.CharField(required=False)
    primary_text = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
    call_to_action = serializers.CharField(required=False)
    destination_url = serializers.URLField(required=False)

    draft = serializers.BooleanField(default=True)

    # TODO: Need to add the add proper validation

    def to_internal_value(self, data):
        data = preprocess_multipart_data(data)
        return super().to_internal_value(data)

    def validate_objective(self, value):
        if not value:
            return value
        allowed = [c.value for c in UnifiedObjective]
        if value not in allowed:
            raise serializers.ValidationError(f"Objective '{value}' is not valid. Allowed: {', '.join(allowed)}")
        return value

    def validate_min_age(self, value):
        if value is not None and (value < 13 or value > 65):
            raise serializers.ValidationError("Minimum age must be between 13 and 65.")
        return value

    def validate_max_age(self, value):
        if value is not None and (value < 13 or value > 65):
            raise serializers.ValidationError("Maximum age must be between 13 and 65.")
        return value

    def validate_platforms(self, value):
        if not value:
            return value
        allowed_platforms = ['META', 'GOOGLE', 'TIKTOK']
        for platform in value:
            if platform not in allowed_platforms:
                raise serializers.ValidationError(f"Platform '{platform}' is not supported.")
        
        request = self.context.get('request')
        if not request:
            return value
            
        org_id = request.query_params.get('org_id')
        if not org_id:
            membership = request.user.organizationmember_set.first()
        else:
            membership = request.user.organizationmember_set.filter(organization__snowflake_id=org_id).first()

        if not membership:
            raise serializers.ValidationError("You are not a member of the specified organization.")
            
        AdCreationService().validate_platform_integrations(membership.organization, value)
        return value

    def validate(self, data):
        min_age = data.get('min_age')
        max_age = data.get('max_age')
        if min_age is not None and max_age is not None and min_age > max_age:
            raise serializers.ValidationError({'max_age': 'Maximum age must be greater than or equal to minimum age.'})
        return data

class AICopyRequestSerializer(serializers.Serializer):
    product = serializers.CharField(max_length=200)
    audience = serializers.CharField(max_length=200)
    benefits = serializers.CharField()
    tone = serializers.ChoiceField(
        choices=['Professional', 'Persuasive', 'Friendly', 'Urgent', 'Casual', 'Creative']
    )
    copy_type = serializers.ChoiceField(choices=['Headlines', 'Primary Text', 'Descriptions', 'CTAs'])

class AIAdCopySerializer(serializers.Serializer):
    product_service = serializers.CharField(max_length=200)
    target_audience = serializers.CharField(max_length=200)
    key_benefits = serializers.CharField()
    tone = serializers.CharField(max_length=50)

class BillingHistorySerializer(serializers.ModelSerializer):
    """Row of the Subscription & Billing → Billing History table."""
    date = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    period = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    has_invoice = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ['id', 'date', 'description', 'period', 'amount', 'currency', 'status', 'paid_at', 'has_invoice']

    def get_date(self, obj):
        return obj.paid_at or obj.created_at

    def _interval(self, obj):
        plan = obj.subscription.plan if obj.subscription and obj.subscription.plan else None
        return plan.interval if plan else 'month'

    def get_description(self, obj):
        plan = obj.subscription.plan if obj.subscription and obj.subscription.plan else None
        name = plan.get_name_display() if plan else 'Subscription'
        label = 'Yearly' if self._interval(obj) == 'year' else 'Monthly'
        return f"{name} Plan - {label} Subscription"

    def get_period(self, obj):
        start = obj.paid_at or obj.created_at
        if not start:
            return None
        end = start + (timedelta(days=365) if self._interval(obj) == 'year' else timedelta(days=30))
        return {'start': start, 'end': end}

    def get_status(self, obj):
        return obj.get_status_display()

    def get_has_invoice(self, obj):
        return bool(obj.stripe_invoice_id)

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['snowflake_id', 'name', 'website', 'industry', 'company_size', 'created_at', 'status']
        # Suspension is a platform-admin action (see /admin/organizations/).
        read_only_fields = ['snowflake_id', 'created_at', 'status']

class TeamMemberSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    status = serializers.ChoiceField(choices=[('PENDING', 'Pending'), ('ACTIVE', 'Active'), ('REJECTED', 'Rejected')], default='PENDING', read_only=True)
    joined_at = serializers.DateTimeField(source='user.joined_at', read_only=True, default=None)
    last_active_at = serializers.DateTimeField(source='user.last_login', read_only=True, default=None)

    class Meta:
        model = OrganizationMember
        fields = ['id', 'user', 'role', 'status', 'joined_at', 'last_active_at']

class TeamMemberInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[('ADMIN', 'Admin'), ('MEMBER', 'Member')])

class AIInsightSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIInsight
        fields = ['id', 'title', 'description', 'created_at', 'impact']


class AIInsightDetailSerializer(AIInsightSerializer):
    """Insight row for the AI Tools → Optimization list."""
    metrics = serializers.SerializerMethodField()
    campaigns_count = serializers.SerializerMethodField()
    campaign_name = serializers.CharField(source='campaign.name', read_only=True)
    action_text = serializers.SerializerMethodField()
    action_type = serializers.SerializerMethodField()

    class Meta(AIInsightSerializer.Meta):
        fields = AIInsightSerializer.Meta.fields + [
            'campaign', 'campaign_name', 'metrics', 'campaigns_count', 'action_text', 'action_type',
        ]

    # TODO: the insight model does not store a structured recommendation yet, so the
    # action is derived from the impact level. Replace with the action the AI engine
    # actually recommends once ``run_optimization_analysis`` persists it.
    _ACTIONS = {
        'HIGH': ('Apply Suggestion', 'apply'),
        'MEDIUM': ('Fix with AI', 'fix'),
        'LOW': ('Generate Suggestions', 'generate'),
    }

    def get_action_text(self, obj):
        return self._ACTIONS.get(obj.impact, ('No Action Needed', 'none'))[0]

    def get_action_type(self, obj):
        return self._ACTIONS.get(obj.impact, ('No Action Needed', 'none'))[1]

    def get_campaigns_count(self, obj):
        counts = self.context.get('campaigns_per_title') or {}
        return counts.get(obj.title, 1)

    def get_metrics(self, obj):
        """Current CTR / CPC of the campaign the insight was raised for (last 30 days)."""
        metrics_by_campaign = self.context.get('campaign_metrics') or {}
        m = metrics_by_campaign.get(obj.campaign_id)
        if not m:
            return []
        return [
            {'label': 'CTR', 'value': f"{m['ctr']:.2f}%"},
            {'label': 'CPC', 'value': f"${m['cpc']:.2f}"},
        ]


class AIOptimizationSettingsSerializer(serializers.ModelSerializer):
    last_optimization = serializers.DateTimeField(source='last_optimization_at', read_only=True)

    class Meta:
        model = AIOptimizationSettings
        fields = ['auto_optimization', 'optimization_mode', 'optimization_frequency', 'last_optimization']


class AudienceReachRequestSerializer(serializers.Serializer):
    min_age = serializers.IntegerField(required=False, min_value=13, max_value=65, default=18)
    max_age = serializers.IntegerField(required=False, min_value=13, max_value=65, default=65)
    gender = serializers.ChoiceField(choices=['all', 'male', 'female'], required=False, default='all')
    locations = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    keywords = serializers.CharField(required=False, allow_blank=True, default='')
