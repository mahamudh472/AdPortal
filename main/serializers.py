from django.utils import choices
from main.models import BudgetType, UnifiedCampaign, AdIntegration
from rest_framework import serializers
import json
from rest_framework.validators import UniqueValidator
from finance.models import Payment

class CampaignSerializer(serializers.ModelSerializer):
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

    # TODO : Implement the methods to calculate the metrics
    def get_platforms(self, obj):
        return [pc.integration.platform for pc in obj.platform_campaigns.all()]
    def get_total_budget(self, obj):
        return 0
    def get_total_spent(self, obj):
        return 0
    def get_impressions(self, obj):
        return 0
    def get_clicks(self, obj):
        return 0
    def get_conversions(self, obj):
        return 0
    def get_ctr(self, obj):
        return 0
    def get_roas(self, obj):
        return 0

class BudgetItemSerializer(serializers.Serializer):
    platform=serializers.CharField()
    budget_type = serializers.CharField(max_length=20)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    budget = serializers.IntegerField()
    run_continuously = serializers.BooleanField()

class CreateAdSerializer(serializers.Serializer):
    platforms = serializers.ListField(
        child=serializers.CharField(max_length=20)
    )
    campaign_name = serializers.CharField(max_length=100, source='name', validators=[UniqueValidator(queryset=UnifiedCampaign.objects.all())])
    objective = serializers.CharField(max_length=20)

    # budget
    budgets = BudgetItemSerializer(many=True)

    # Target audience 
    min_age = serializers.IntegerField()
    max_age = serializers.IntegerField()
    gender = serializers.CharField()
    locations = serializers.ListField(
        child=serializers.CharField(),
        min_length=1
    )
    keywords = serializers.CharField()

    ad_name = serializers.CharField(max_length=100)
    ad_file = serializers.FileField(required=False)

    headline = serializers.CharField()
    primary_text = serializers.CharField()
    description = serializers.CharField()
    call_to_action = serializers.CharField()
    destination_url = serializers.URLField()

    draft = serializers.BooleanField(default=True)

    # TODO: Need to add the add proper validation

    def to_internal_value(self, data):
        data = data.copy()

        platforms = data.get("platforms")

        if isinstance(platforms, str):
            try:
                data["platforms"] = json.loads(platforms)
            except json.JSONDecodeError:
                raise serializers.ValidationError({
                    "platforms": "Invalid JSON array"
                })

        return super().to_internal_value(data)
    def validate_platforms(self, value):
        allowed_platforms = ['META', 'GOOGLE', 'TIKTOK']
        for platform in value:
            if platform not in allowed_platforms:
                raise serializers.ValidationError(f"Platform '{platform}' is not supported.")
        organization = self.context['request'].user.organizationmember_set.first().organization
        for platform in value:
            if not AdIntegration.objects.filter(platform=platform, organization=organization).exists():
                raise serializers.ValidationError(f"No Ad Integration found for platform '{platform}'. Please set up an ad account integration first.")
        return value

class AICopyRequestSerializer(serializers.Serializer):
    product = serializers.CharField(max_length=200)
    audience = serializers.CharField(max_length=200)
    benefits = serializers.CharField()
    tone = serializers.ChoiceField(choices=['Professional', 'Casual', 'Friendly'])
    copy_type = serializers.ChoiceField(choices=['Headlines', 'Primary Text', 'Descriptions', 'CTAs'])


class BillingHistorySerializer(serializers.ModelSerializer):
    invoice_url = serializers.SerializerMethodField()
    class Meta:
        model = Payment
        fields =['amount', 'status', 'paid_at', 'invoice_url']
    
    def get_invoice_url(self, obj):
        # TODO: Replace with actual logic to generate invoice URL
        return f"https://billing.example.com/invoices/{obj.id}"

