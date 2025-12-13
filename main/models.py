from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

class Platform(models.TextChoices):
    META = 'META', 'Meta (Facebook/Instagram)'
    GOOGLE = 'GOOGLE', 'Google Ads'
    TIKTOK = 'TIKTOK', 'TikTok Ads'

class UnifiedObjective(models.TextChoices):
    TRAFFIC = 'TRAFFIC', 'Traffic/Clicks'
    SALES = 'SALES', 'Conversions/Sales'
    AWARENESS = 'AWARENESS', 'Brand Awareness'

class UnifiedStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    PAUSED = 'PAUSED', 'Paused'
    ARCHIVED = 'ARCHIVED', 'Archived/Deleted'
    ERROR = 'ERROR', 'Error/Rejected'

class AdIntegration(models.Model):
    """
    Stores the connection between your user and the external platform.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='integrations')
    platform = models.CharField(max_length=20, choices=Platform.choices)
    
    # The external Ad Account ID (e.g., act_12345678 or 758264...)
    ad_account_id = models.CharField(max_length=100)
    
    # Auth Tokens
    access_token = models.TextField()
    refresh_token = models.TextField(null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata (e.g., Name of the ad account, currency)
    account_name = models.CharField(max_length=255, null=True, blank=True)
    currency = models.CharField(max_length=10, default='USD')
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'platform', 'ad_account_id')

    def __str__(self):
        return f"{self.user.username} - {self.platform} ({self.ad_account_id})"
    
class Campaign(models.Model):
    integration = models.ForeignKey(AdIntegration, on_delete=models.CASCADE, related_name='campaigns')
    
    # Internal Name (What your user sees)
    name = models.CharField(max_length=255)
    
    # External ID (The ID returned by Facebook/TikTok)
    platform_campaign_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    
    # Unified Fields
    objective = models.CharField(max_length=20, choices=UnifiedObjective.choices)
    status = models.CharField(max_length=20, choices=UnifiedStatus.choices, default=UnifiedStatus.PAUSED)
    
    # Budget (Decimal for money)
    daily_budget = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Store raw API response or extra platform specific data here
    # Example: Google might need 'bidding_strategy_type' which TikTok doesn't have.
    # Store that logic in JSON.
    extra_data = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.get_platform_display()} - {self.name}"

    @property
    def platform(self):
        return self.integration.platform
    
class AdGroup(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='ad_groups')
    
    name = models.CharField(max_length=255)
    platform_adgroup_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=UnifiedStatus.choices, default=UnifiedStatus.PAUSED)
    
    # TARGETING (The complex part)
    # We use JSONField because targeting is too different across platforms to make specific columns.
    # Structure: {'age_min': 18, 'geo_locations': ['US'], 'interests': [...]}
    targeting_config = models.JSONField(default=dict)
    
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name
    
class AdAsset(models.Model):
    """
    Stores the actual files (Images/Videos) uploaded by the user to YOUR server
    before they are sent to Facebook/TikTok.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    file = models.FileField(upload_to='ad_assets/')
    file_type = models.CharField(max_length=10, choices=[('IMAGE', 'Image'), ('VIDEO', 'Video')])
    
    # Hash is useful to check if file already exists on Facebook
    file_hash = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Ad(models.Model):
    ad_group = models.ForeignKey(AdGroup, on_delete=models.CASCADE, related_name='ads')
    
    name = models.CharField(max_length=255)
    platform_ad_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=UnifiedStatus.choices, default=UnifiedStatus.PAUSED)
    
    # The Creative Details
    headline = models.CharField(max_length=255, null=True, blank=True)
    body_text = models.TextField(null=True, blank=True)
    destination_url = models.URLField()
    
    # Link to the local asset
    asset = models.ForeignKey(AdAsset, on_delete=models.SET_NULL, null=True)
    
    # Store the ID returned by the platform's asset upload (e.g., the Image Hash or Video ID)
    platform_asset_id = models.CharField(max_length=255, null=True, blank=True)
    
    preview_link = models.URLField(null=True, blank=True)

    def __str__(self):
        return self.name
    
    