from django.utils import choices
from main.models import BudgetType, UnifiedCampaign
from rest_framework import serializers
import json
from rest_framework.validators import UniqueValidator


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnifiedCampaign
        fields = '__all__'

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






