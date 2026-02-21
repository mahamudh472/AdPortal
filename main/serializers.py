from accounts.serializers import SimpleUserSerializer
from main.models import BudgetType, Organization, OrganizationMember, UnifiedCampaign, UnifiedObjective, AdIntegration, AIInsight, Ad
from rest_framework import serializers
from django.db import models
import json
from finance.models import Payment
from analysis.models import AnalysisDaily
from main.utils.helper import get_performance_matrics

class PlatformAdSerializer(serializers.ModelSerializer):
    matrics = serializers.SerializerMethodField()
    class Meta:
        model = Ad
        fields = ['id', 'name', 'status', 'matrics']
    def get_matrics(self, obj):
        analysis = AnalysisDaily.objects.filter(adgroup_id=obj.ad_group_id)
        analysis = get_performance_matrics(analysis)
        return analysis

class TempCampaignSerializer(serializers.ModelSerializer):
    platforms = serializers.SerializerMethodField()
    total_budget = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    impressions = serializers.SerializerMethodField()
    clicks = serializers.SerializerMethodField()
    conversions = serializers.SerializerMethodField()
    ctr = serializers.SerializerMethodField()
    roas = serializers.SerializerMethodField()
    class Meta:
        model = UnifiedCampaign
        fields = '__all__'

    def get_platforms(self, obj):
        return [pc.integration.platform for pc in obj.platform_campaigns.all()]

    def get_total_budget(self, obj):
        raw = getattr(obj, '_total_budget', 0) or 0
        return round(raw / 100, 2)

    def get_total_spent(self, obj):
        return round(getattr(obj, '_total_spent', 0) or 0, 2)

    def get_impressions(self, obj):
        return getattr(obj, '_impressions', 0) or 0

    def get_clicks(self, obj):
        return getattr(obj, '_clicks', 0) or 0

    def get_conversions(self, obj):
        return getattr(obj, '_conversions', 0) or 0

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

    class Meta:
        model = UnifiedCampaign
        fields = ['id', 'name', 'objective', 'platforms', 'matrics', 'ads', 'audience_targeting', 'status', 'created_at', 'ai_insights', 'total_budget', 'total_spent', 'remaining_budget']

    def get_platforms(self, obj):
        return [pc.integration.platform for pc in obj.platform_campaigns.all()]

    def get_matrics(self, obj):
        analysis = AnalysisDaily.objects.filter(unified_campaign=obj)
        analysis = get_performance_matrics(analysis)
        return analysis

    def get_ads(self, obj):
        ads = []
        for pc in obj.platform_campaigns.all():
            for ad_group in pc.ad_groups.all():
                ads.extend(ad_group.ads.all())
        return PlatformAdSerializer(ads, many=True).data       

    def get_audience_targeting(self, obj):
        # TODO: Need to add the proper targeting fields in the model and return them here
        return {
            'min_age': 18,
            'max_age': 65,
            'gender': 'all',
            'locations': [],
            'keywords': '',
        }
    
    def get_ai_insights(self, obj):
        insights = obj.ai_insights.order_by('-created_at')[:5]
        return AIInsightSerializer(insights, many=True).data
    
    def get_total_budget(self, obj):
        from main.models import CampaignBudget
        total = CampaignBudget.objects.filter(campaign=obj).aggregate(
            total=models.Sum('daily_budget_minor')
        )['total']
        return round((total or 0) / 100, 2)

    def get_total_spent(self, obj):
        spent = AnalysisDaily.objects.filter(unified_campaign=obj).aggregate(
            total=models.Sum('spend')
        )['total']
        return round(spent, 2) if spent else 0

    def get_remaining_budget(self, obj):
        total_budget = self.get_total_budget(obj)
        total_spent = self.get_total_spent(obj)
        return round(total_budget - total_spent, 2)


class BudgetItemSerializer(serializers.Serializer):
    platform=serializers.CharField()
    budget_type = serializers.CharField(max_length=20)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
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
    spend = serializers.SerializerMethodField()
    performance = serializers.SerializerMethodField()
    class Meta:
        model = UnifiedCampaign
        fields = ['id', 'name', 'status', 'platforms', 'created_at', 'spend', 'performance']
    def get_platforms(self, obj):
        return [pc.integration.platform for pc in obj.platform_campaigns.all()]
    def get_spend(self, obj):
        return 0
    def get_performance(self, obj):
        return {
            'impressions': 0,
            'clicks': 0,
            'conversions': 0,
            'ctr': 0,
            'roas': 0
        }

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
            content_type = value.content_type
            allowed = self.ALLOWED_IMAGE_TYPES + self.ALLOWED_VIDEO_TYPES
            if content_type not in allowed:
                raise serializers.ValidationError(
                    f"File type '{content_type}' is not supported. "
                    f"Allowed image types: {', '.join(self.ALLOWED_IMAGE_TYPES)}. "
                    f"Allowed video types: {', '.join(self.ALLOWED_VIDEO_TYPES)}."
                )
        return value

    headline = serializers.CharField(required=False)
    primary_text = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
    call_to_action = serializers.CharField(required=False)
    destination_url = serializers.URLField(required=False)

    draft = serializers.BooleanField(default=True)

    # TODO: Need to add the add proper validation

    def to_internal_value(self, data):
        # Use dict() instead of data.copy() to avoid QueryDict.__deepcopy__
        # which fails on file uploads (cannot pickle BufferedRandom)
        data = dict(data.lists()) if hasattr(data, 'lists') else data.copy()
        # Fields that must remain as lists even with a single value
        list_fields = {'platforms', 'locations', 'budgets'}
        # Flatten single-value lists from QueryDict, except list fields
        data = {
            k: v if k in list_fields else (v[0] if isinstance(v, list) and len(v) == 1 else v)
            for k, v in data.items()
        }

        # Parse JSON-encoded strings for list fields (multipart/form-data)
        for field_name in list_fields:
            value = data.get(field_name)
            if isinstance(value, list) and len(value) == 1 and isinstance(value[0], str):
                try:
                    parsed = json.loads(value[0])
                    if isinstance(parsed, list):
                        data[field_name] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(value, str):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        data[field_name] = parsed
                except (json.JSONDecodeError, TypeError):
                    pass

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
        membership = self.context['request'].user.organizationmember_set.first()
        if not membership:
            raise serializers.ValidationError("You are not a member of any organization.")
        organization = membership.organization
        for platform in value:
            if not AdIntegration.objects.filter(platform=platform, organization=organization).exists():
                raise serializers.ValidationError(f"No Ad Integration found for platform '{platform}'. Please set up an ad account integration first.")
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
    tone = serializers.ChoiceField(choices=['Professional', 'Casual', 'Friendly'])
    copy_type = serializers.ChoiceField(choices=['Headlines', 'Primary Text', 'Descriptions', 'CTAs'])

class AIAdCopySerializer(serializers.Serializer):
    product_service = serializers.CharField(max_length=200)
    target_audience = serializers.CharField(max_length=200)
    key_benefits = serializers.CharField()
    tone = serializers.CharField(max_length=50)

class BillingHistorySerializer(serializers.ModelSerializer):
    invoice_url = serializers.SerializerMethodField()
    class Meta:
        model = Payment
        fields =['amount', 'status', 'paid_at', 'invoice_url']
    
    def get_invoice_url(self, obj):
        # TODO: Replace with actual logic to generate invoice URL
        return f"https://billing.example.com/invoices/{obj.id}"

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['snowflake_id', 'name', 'website', 'industry', 'company_size']

class TeamMemberSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    status = serializers.ChoiceField(choices=[('PENDING', 'Pending'), ('ACTIVE', 'Active'), ('REJECTED', 'Rejected')], default='PENDING', read_only=True)
    class Meta:
        model = OrganizationMember
        fields = ['id', 'user', 'role', 'status']

class TeamMemberInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=[('ADMIN', 'Admin'), ('MEMBER', 'Member')])

class AIInsightSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIInsight
        fields = ['id', 'title', 'description', 'created_at', 'impect']
