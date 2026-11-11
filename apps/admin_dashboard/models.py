from django.db import models
from apps.main.utils.safe_files import admin_report_upload_to


class AdminReport(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'

    VALID_METRICS = [
        'revenue_overview',
        'revenue_by_plan',
        'user_growth',
        'feature_usage',
        'monthly_revenue',
        'mrr_growth',
        'total_transactions',
        'failed_payments',
    ]

    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    file = models.FileField(upload_to=admin_report_upload_to, blank=True, null=True)
    file_size = models.PositiveIntegerField(blank=True, null=True)  # Store file size in bytes
    report_type = models.CharField(max_length=50)  # weekly, monthly, quarterly, custom
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    included_metrics = models.JSONField(default=list, blank=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    download_count = models.PositiveIntegerField(default=0)  # Track how many times the report has been downloaded
    generated_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='generated_admin_reports')

    def __str__(self):
        return self.name


class AdminNotificationSettings(models.Model):
    admin = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='admin_notification_settings', blank=True, null=True)
    new_user_signup = models.BooleanField(default=True)
    failed_payment = models.BooleanField(default=True)
    system_errors = models.BooleanField(default=True)
    security_alerts = models.BooleanField(default=True)
