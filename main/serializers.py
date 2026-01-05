from main.models import Campaign
from rest_framework import serializers

class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = '__all__'