from django.contrib import admin

from .models import Company, Establishment


class EstablishmentInline(admin.TabularInline):
    model = Establishment
    extra = 0  # No extra empty forms
    fields = ("name", "city", "state")


class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "state")
    list_filter = ("name", "city", "state")
    search_fields = ("name", "city", "state")
    inlines = [EstablishmentInline]  # Add the inline here


class EstablishmentAdmin(admin.ModelAdmin):
    list_display = ("name", "public_id", "city", "state", "company")
    list_filter = ("city", "state", "company")
    search_fields = ("name", "city", "state", "public_id")
    readonly_fields = ("public_id",)


admin.site.register(Company, CompanyAdmin)
admin.site.register(Establishment, EstablishmentAdmin)
