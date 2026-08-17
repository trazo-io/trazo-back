from django.contrib import admin

from .models import GeneratedDocument


@admin.register(GeneratedDocument)
class GeneratedDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "establishment", "folder", "source", "size_bytes", "created_at")
    list_filter = ("folder", "source")
    search_fields = ("title", "establishment__name")
    readonly_fields = ("public_id", "created_at", "size_bytes", "content_type")
