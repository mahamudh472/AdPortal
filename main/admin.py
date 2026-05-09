from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import (
    Organization, OrganizationMember,
    UnifiedCampaign, AdIntegration, 
    PlatformCampaign, UnifiedObjective, UnifiedStatus, 
    AdGroup, Ad, AdAsset, IntegrationSyncState,
    CampaignBudget, AIInsight, PlatformSyncEvent
)

@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    list_display = ('owner', 'name', 'created_at')

@admin.register(OrganizationMember)
class OrganizationMemberAdmin(ModelAdmin):
    pass

@admin.register(AdIntegration)
class AdIntegrationAdmin(ModelAdmin):
    list_display = ('organization', 'platform', 'ad_account_id', 'account_name', 'currency', 'is_active', 'created_at')
    search_fields = ('organization__name', 'ad_account_id', 'account_name')
    list_filter = ('platform', 'is_active')

@admin.register(UnifiedCampaign)
class CampaignAdmin(ModelAdmin):
    list_display = ('name', 'objective', 'status', 'created_at', 'updated_at')
    search_fields = ('name', 'platform_campaign_id')
    list_filter = ('objective', 'status')

@admin.register(PlatformCampaign)
class PlatformCampaignAdmin(ModelAdmin):
    pass

@admin.register(AdGroup)
class AdGroupAdmin(ModelAdmin):
    pass

@admin.register(Ad)
class AdAdmin(ModelAdmin):
    pass

@admin.register(AdAsset)
class AdAssetAdmin(ModelAdmin):
    pass

@admin.register(IntegrationSyncState)
class IntegrationSyncStateAdmin(ModelAdmin):
    pass

@admin.register(CampaignBudget)
class CampaignBudgetAdmin(ModelAdmin):
    list_display = ('campaign', 'platform', 'budget_type', 'daily_budget_minor', 'start_date', 'end_date', 'run_continuously')
    search_fields = ('campaign__name',)
    list_filter = ('platform', 'budget_type', 'run_continuously')
    
# @admin.register(AdGroup)
# class AdGroupAdmin(admin.ModelAdmin):
#     list_display = ('name', 'campaign', 'platform_adgroup_id')
#     search_fields = ('name', 'platform_adgroup_id', 'campaign__name')
#     list_filter = ('campaign',)
#     date_hierarchy = 'campaign__created_at'

@admin.register(AIInsight)
class AIInsightAdmin(ModelAdmin):
    pass


@admin.register(PlatformSyncEvent)
class PlatformSyncEventAdmin(ModelAdmin):
    list_display = ('campaign', 'platform', 'operation', 'status', 'created_at', 'completed_at')
    search_fields = ('campaign__name', 'error_message', 'message')
    list_filter = ('platform', 'operation', 'status')
