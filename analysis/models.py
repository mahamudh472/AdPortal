from django.db import models
from main.models import Platform, Organization

class AnalysisDaily(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='daily_analyses')
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


class Report(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    name = models.CharField(max_length=255)
    organization = models.ForeignKey('main.Organization', on_delete=models.CASCADE, related_name='reports')
    created_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to='reports/', blank=True, null=True)
    report_type = models.CharField(max_length=50)  # e.g., 'weekly', 'monthly', 'custom'
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    included_platforms = models.JSONField(default=list, blank=True)  # e.g., ['META', 'TIKTOK', 'GOOGLE']
    included_metrics = models.JSONField(default=list, blank=True)    # e.g., ['spend', 'impressions', 'clicks', 'ctr', 'cpc', 'roas']
    start_date = models.DateField(blank=True, null=True)  # For custom date range reports
    end_date = models.DateField(blank=True, null=True)    # For custom date range reports

    def __str__(self):
        return self.name

