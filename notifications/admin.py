from django.contrib import admin

from .models import InAppNotification


@admin.register(InAppNotification)
class InAppNotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'created_at', 'read_at')
    list_filter = ('created_at', 'read_at')
    search_fields = ('title', 'message', 'user__username', 'user__email')
    readonly_fields = ('user', 'title', 'message', 'url', 'created_at', 'read_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
