from django.contrib import admin

from .models import AuditLog, Conversation, Question

# titles on the Django admin pages
admin.site.site_header = "NOP Intelligence - admin"
admin.site.site_title = "NOP Intelligence admin"


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "text", "status", "rows_count", "secs", "tries")
    list_filter = ("status", "user")
    search_fields = ("text", "answer", "sql", "error")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("updated_at", "user", "title", "archived", "deleted_at")
    list_filter = ("archived", "user")
    search_fields = ("title",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """The audit log in the admin: read-only - nobody can add, change or delete a line here."""
    list_display = ("created_at", "username", "action", "target", "ip_address")
    list_filter = ("action",)
    search_fields = ("username", "target")
    readonly_fields = [field.name for field in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
