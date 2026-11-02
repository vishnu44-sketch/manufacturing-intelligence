from django.contrib import admin

from .models import Conversation, Question

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
    list_display = ("updated_at", "user", "title", "archived")
    list_filter = ("archived", "user")
    search_fields = ("title",)
