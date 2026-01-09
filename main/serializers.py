from main.models import UnifiedCampaign
from rest_framework import serializers

class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnifiedCampaign
        fields = '__all__'