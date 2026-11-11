from django.contrib import admin

# Register your models here.


from unfold.admin import ModelAdmin as _UnfoldModelAdmin
from django.contrib import admin as _admin
from .models import AdminAuditLog


@_admin.register(AdminAuditLog)
class AdminAuditLogAdmin(_UnfoldModelAdmin):
    list_display = ('created_at', 'actor_email', 'action', 'target_type', 'target_id', 'ip_address')
    list_filter = ('action', 'target_type')
    search_fields = ('actor_email', 'target_id', 'action')
    readonly_fields = [f.name for f in AdminAuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
