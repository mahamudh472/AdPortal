from django.db import models
from apps.main.models import Platform, Organization
from apps.main.utils.safe_files import report_upload_to

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
    # Revenue (conversion value) in ``currency``; ``roas`` is conversion_value / spend.
    conversion_value = models.FloatField(default=0)
    reach = models.IntegerField(blank=True, null=True)
    frequency = models.FloatField(blank=True, null=True)
    video_views = models.IntegerField(blank=True, null=True)
    currency = models.CharField(max_length=3, blank=True, default='')
    synced_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        unique_together = ('platform', 'account_id', 'campaign_id', 'adgroup_id', 'date')
        indexes = [
            # Dominant access patterns: org-scoped date ranges and per-campaign rollups
            models.Index(fields=['organization', 'date'], name='analysis_org_date_idx'),
            models.Index(fields=['unified_campaign', 'date'], name='analysis_camp_date_idx'),
        ]

    def __str__(self):
        return f"Analysis for {self.campaign_name} {self.date} on {self.platform}"


class AnalysisBreakdownDaily(models.Model):
    """One row per (campaign, day, dimension, key), e.g. dimension='device', key='mobile'.

    A single generic table keeps every breakdown (publisher platform, placement, device,
    hour of day, age, gender, country) queryable without a table or column per breakdown.
    """
    class Dimension(models.TextChoices):
        PUBLISHER_PLATFORM = 'publisher_platform', 'Publisher platform'
        PLACEMENT = 'placement', 'Placement'
        DEVICE = 'device', 'Device'
        HOUR = 'hour', 'Hour of day'
        AGE = 'age', 'Age'
        GENDER = 'gender', 'Gender'
        COUNTRY = 'country', 'Country'

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='breakdown_analyses')
    unified_campaign = models.ForeignKey('main.UnifiedCampaign', on_delete=models.CASCADE, related_name='breakdown_analyses')
    platform = models.CharField(max_length=100, choices=Platform.choices)
    account_id = models.CharField(max_length=100)
    campaign_id = models.CharField(max_length=100)
    date = models.DateField()
    dimension = models.CharField(max_length=30, choices=Dimension.choices)
    key = models.CharField(max_length=100)
    impressions = models.IntegerField(default=0)
    clicks = models.IntegerField(default=0)
    spend = models.FloatField(default=0)
    conversions = models.FloatField(default=0)
    conversion_value = models.FloatField(default=0)
    currency = models.CharField(max_length=3, blank=True, default='')

    class Meta:
        unique_together = ('platform', 'account_id', 'campaign_id', 'date', 'dimension', 'key')
        indexes = [
            models.Index(fields=['organization', 'dimension', 'date'], name='breakdown_org_dim_date_idx'),
            models.Index(fields=['unified_campaign', 'dimension'], name='breakdown_camp_dim_idx'),
        ]

    def __str__(self):
        return f"{self.dimension}={self.key} {self.date} {self.platform}"


class Report(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    name = models.CharField(max_length=255)
    organization = models.ForeignKey('main.Organization', on_delete=models.CASCADE, related_name='reports')
    created_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to=report_upload_to, blank=True, null=True)
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
