from django.db import models
from main.models import Platform

class AnalysisDaily(models.Model):
    platform = models.CharField(max_length=100, choices=Platform.choices)
    account_id = models.CharField(max_length=100)
    campaign_id = models.CharField(max_length=100, blank=True, null=True)
    campaign_name = models.CharField(max_length=255, blank=True, null=True)
    adgroup_id = models.CharField(max_length=100, blank=True, null=True)
    date = models.DateField()
    impressions = models.IntegerField()
    clicks = models.IntegerField()
    spend = models.FloatField()
    ctr = models.FloatField()  # Click-Through Rate
    cpc = models.FloatField()  # Cost Per Click
    roas = models.FloatField()  # Return on Ad Spend
    device_breakdown = models.JSONField(blank=True, null=True)  # e.g., {"mobile": {...}, "desktop": {...}}
    class Meta:
        unique_together = ('platform', 'account_id', 'campaign_id', 'adgroup_id', 'date')

    def __str__(self):
        return f"Analysis for {self.campaign_name} {self.date} on {self.platform}"
    