from django.db import models
from apps.main.models import Platform, Organization

class AnalysisDaily(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='daily_analyses')
    unified_campaign = models.ForeignKey('main.UnifiedCampaign', on_delete=models.CASCADE, related_name='daily_analyses')
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
    cpm = models.FloatField(default=0)  # Cost Per Mille (per 1000 impressions)
    conversions = models.IntegerField(default=0)  # Total conversions
    cpa = models.FloatField(default=0)  # Cost Per Acquisition
    roas = models.FloatField()  # Return on Ad Spend
    device_breakdown = models.JSONField(blank=True, null=True)  # e.g., {"mobile": {...}, "desktop": {...}}
    budget_type = models.CharField(max_length=20, blank=True, null=True)
    budget_amount = models.FloatField(blank=True, null=True)
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



class ScheduledReport(models.Model):
    """A recurring report an organization wants generated automatically.

    TODO: nothing generates these on a schedule yet. Add a Celery beat task that
    walks enabled rows, calls ``generate_report_task`` and advances ``next_run_at``.
    """
    class Frequency(models.TextChoices):
        WEEKLY = 'weekly', 'Weekly'
        MONTHLY = 'monthly', 'Monthly'

    organization = models.ForeignKey('main.Organization', on_delete=models.CASCADE, related_name='scheduled_reports')
    title = models.CharField(max_length=255)
    frequency = models.CharField(max_length=20, choices=Frequency.choices, default=Frequency.WEEKLY)
    # Human-readable description shown in the UI, e.g. "Every Monday at 9:00 AM".
    schedule = models.CharField(max_length=255)
    included_metrics = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.title} ({self.organization_id})"
