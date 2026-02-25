from django.db import models

class AdminNotificationSettings(models.Model):
    admin = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='admin_notification_settings', blank=True, null=True)
    new_user_signup = models.BooleanField(default=True)
    failed_payment = models.BooleanField(default=True)
    system_errors = models.BooleanField(default=True)
    security_alerts = models.BooleanField(default=True)
