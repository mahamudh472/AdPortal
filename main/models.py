import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from snowflake import SnowflakeGenerator

generator = SnowflakeGenerator(1)

class Platform(models.TextChoices):
    META = 'META', 'Meta (Facebook/Instagram)'
    GOOGLE = 'GOOGLE', 'Google Ads'
    TIKTOK = 'TIKTOK', 'TikTok Ads'

class UnifiedObjective(models.TextChoices):
    AWARENESS = 'AWARENESS'
    TRAFFIC = 'TRAFFIC'
    ENGAGEMENT = 'ENGAGEMENT'
    LEAD = 'LEAD'
    SALES = 'SALES'
    APP_INSTALL = 'APP_INSTALL'
    VIDEO_VIEW = 'VIDEO_VIEW'

class UnifiedStatus(models.TextChoices):
    DRAFT = 'DRAFT'
    ACTIVE = 'ACTIVE'
    PAUSED = 'PAUSED'
    SYNCING = 'SYNCING'
    ERROR = 'ERROR'
    ARCHIVED = 'ARCHIVED'

class BudgetType(models.TextChoices):
    ONETIME = 'ONETIME'
    DAILY = 'DAILY'

class OrganizationRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    ADMIN = "ADMIN", "Admin"
    MEMBER = "MEMBER", "Member"

class Organization(models.Model):
    INDUSTRY_CHOICES = [
        ('ecommerce', 'E-Commerce'),
        ('saas', 'SaaS'),
        ('agency', 'Agency'),
        ('education', 'Education'),
        ('finance', 'Finance'),
        ('other', 'Other'),
    ]
    COMPANY_SIZE_CHOICES = [
        ('1-10', '1-10'),
        ('11-50', '11-50'),
        ('51-200', '51-200'),
        ('201-500', '201-500'),
        ('500+', '500+'),

    ]
    snowflake_id = models.CharField(
        unique=True,
        null=True,
        editable=False,
        db_index=True,
        max_length=20
    )
    name = models.CharField(max_length=255, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    industry = models.CharField(max_length=100, blank=True, null=True, choices=INDUSTRY_CHOICES)
    company_size = models.CharField(max_length=100, blank=True, null=True, choices=COMPANY_SIZE_CHOICES)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_organizations")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.snowflake_id:
            self.snowflake_id = next(generator)
        super().save(*args, **kwargs)

class OrganizationMember(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=OrganizationRole.choices)

    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True, related_name="sent_org_invites")
    status = models.CharField(max_length=20, choices=[('PENDING', 'Pending'), ('ACTIVE', 'Active'), ('REJECTED', 'Rejected')], default='PENDING')
    class Meta:
        unique_together = ('user', 'organization')

class TeamInvitation(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=OrganizationRole.choices)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, blank=True, null=True, related_name="sent_team_invitations")
    status = models.CharField(max_length=20, choices=[('PENDING', 'Pending'), ('ACCEPTED', 'Accepted'), ('REJECTED', 'Rejected')], default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        expiration_period = timezone.timedelta(days=7)
        return timezone.now() > self.created_at + expiration_period

class AdIntegration(models.Model):
    """
    Stores the connection between your user and the external platform.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='integrations')
    platform = models.CharField(max_length=20, choices=Platform.choices)
    
    # The external Ad Account ID (e.g., act_12345678 or 758264...)
    ad_account_id = models.CharField(max_length=100, null=True, blank=True)
    
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
        unique_together = ('organization', 'platform', 'ad_account_id')

    def __str__(self):
        return f"{self.organization.name} - {self.platform} ({self.ad_account_id})"


class UnifiedCampaign(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)

    name = models.CharField(max_length=255)

    objective = models.CharField(
        max_length=20,
        choices=UnifiedObjective.choices
    )

    status = models.CharField(
        max_length=20,
        choices=UnifiedStatus.choices,
        default=UnifiedStatus.PAUSED
    )

    currency = models.CharField(max_length=3, default="USD")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
    
    class Meta:
        unique_together = ('organization', 'name')


class CampaignBudget(models.Model):
    campaign = models.ForeignKey(UnifiedCampaign, on_delete=models.CASCADE)
    platform = models.CharField(max_length=20, choices=Platform)

    budget_type = models.CharField(max_length=20, choices=BudgetType, default=BudgetType.DAILY)

    daily_budget_minor = models.BigIntegerField(
        help_text="Stored in minor units (e.g. cents)"
    )

    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    run_continuously = models.BooleanField(default=False)


class PlatformCampaign(models.Model):
    unified_campaign = models.ForeignKey(
        UnifiedCampaign,
        on_delete=models.CASCADE,
        related_name='platform_campaigns'
    )

    integration = models.ForeignKey(
        AdIntegration,
        on_delete=models.CASCADE,
        related_name='platform_campaigns'
    )

    platform_campaign_id = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=UnifiedStatus.choices,
        default=UnifiedStatus.PAUSED
    )

    # Platform-specific config
    extra_data = models.JSONField(default=dict, blank=True)

    capabilities = models.JSONField(
        default=dict,
        help_text="Cached platform feature support"
    )
 

    last_synced_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (
            'unified_campaign',
            'integration',
        )

    def __str__(self):
        return f"{self.unified_campaign.name} [{self.integration.platform}]"


class AdGroup(models.Model):
    """
    Represents a platform-level ad container:
    - Meta: Ad Set
    - Google: Ad Group
    - TikTok: Ad Group

    This model is ALWAYS tied to a PlatformCampaign,
    never directly to a UnifiedCampaign.
    """

    platform_campaign = models.ForeignKey(
        PlatformCampaign,
        on_delete=models.CASCADE,
        related_name="ad_groups"
    )

    # Internal name (shown in your UI)
    name = models.CharField(max_length=255)

    # External ID returned by the platform
    platform_adgroup_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True
    )

    status = models.CharField(
        max_length=20,
        choices=UnifiedStatus.choices,
        default=UnifiedStatus.PAUSED
    )

    # Budget at ad-group level (optional per platform)
    daily_budget = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Optional override of campaign budget")
    )

    # Platform-specific targeting configuration
    # Examples:
    # Meta: interests, geo_locations, age_min/max
    # Google: keywords, placements
    # TikTok: demographics, behaviors
    targeting_config = models.JSONField(default=dict)
    normalized_targeting = models.JSONField(
        default=dict,
        help_text="Platform-agnostic targeting snapshot"
    )


    # Platform-specific bidding / optimization config
    # Example:
    # {
    #   "bid_strategy": "LOWEST_COST",
    #   "optimization_goal": "CONVERSIONS"
    # }
    bidding_config = models.JSONField(
        default=dict,
        blank=True
    )

    start_time = models.DateTimeField(
        default=timezone.now
    )

    end_time = models.DateTimeField(
        null=True,
        blank=True
    )

    # Sync & error tracking
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True
    )

    error_message = models.TextField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        unique_together = (
            "platform_campaign",
            "platform_adgroup_id",
        )
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.platform_campaign.integration.platform})"

    @property
    def platform(self):
        return self.platform_campaign.integration.platform

class AdAsset(models.Model):
    """
    Stores the actual files (Images/Videos) uploaded by the user to YOUR server
    before they are sent to Facebook/TikTok.
    """
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    file = models.FileField(upload_to='ad_assets/')
    file_type = models.CharField(max_length=10, choices=[('IMAGE', 'Image'), ('VIDEO', 'Video')])

    status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', 'Draft'),
            ('UPLOADED', 'Uploaded'),
            ('IN_USE', 'In Use'),
            ('ARCHIVED', 'Archived'),
        ],
        default='DRAFT'
    )

    is_locked = models.BooleanField(default=False)
    
    # Hash is useful to check if file already exists on Facebook
    file_hash = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('organization', 'file_hash')

class PlatformAsset(models.Model):
    asset = models.ForeignKey(AdAsset, on_delete=models.CASCADE)
    integration = models.ForeignKey(AdIntegration, on_delete=models.CASCADE)
    platform_asset_id = models.CharField(max_length=255)


class Ad(models.Model):
    ad_group = models.ForeignKey(AdGroup, on_delete=models.CASCADE, related_name='ads')
    
    name = models.CharField(max_length=255)
    platform_ad_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=UnifiedStatus.choices, default=UnifiedStatus.PAUSED)
    
    # The Creative Details
    headline = models.CharField(max_length=255, null=True, blank=True)
    primary_text = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    destination_url = models.URLField()

    call_to_action = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    
    # Link to the local asset
    assets = models.ManyToManyField(
        AdAsset,
        related_name="used_in_ads"
    )

    preview_link = models.URLField(null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        unique_together = ("ad_group", "platform_ad_id")
    
class AIInsight(models.Model):    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="ai_insights")
    campaign = models.ForeignKey(UnifiedCampaign, on_delete=models.CASCADE, related_name="ai_insights")
    title = models.CharField(max_length=255)
    description = models.TextField()
    impect = models.CharField(max_length=20, choices=[('HIGH', 'High'), ('MEDIUM', 'Medium'), ('LOW', 'Low')], default='MEDIUM')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'created_at']),
            models.Index(fields=['campaign', 'created_at']),
        ]
