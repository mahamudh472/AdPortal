from django.contrib import admin
from .models import UnifiedCampaign, AdIntegration, Platform, UnifiedObjective, UnifiedStatus, AdGroup

@admin.register(AdIntegration)
class AdIntegrationAdmin(admin.ModelAdmin):
    list_display = ('user', 'platform', 'ad_account_id', 'account_name', 'currency', 'is_active', 'created_at')
    search_fields = ('user__username', 'ad_account_id', 'account_name')
    list_filter = ('platform', 'is_active')

@admin.register(UnifiedCampaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'objective', 'status', 'created_at', 'updated_at')
    search_fields = ('name', 'platform_campaign_id')
    list_filter = ('objective', 'status')

# @admin.register(AdGroup)
# class AdGroupAdmin(admin.ModelAdmin):
#     list_display = ('name', 'campaign', 'platform_adgroup_id')
#     search_fields = ('name', 'platform_adgroup_id', 'campaign__name')
#     list_filter = ('campaign',)
#     date_hierarchy = 'campaign__created_at'


