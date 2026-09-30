from django.contrib import admin

from apps.core.models import Company, Holiday


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("code", "legal_name", "tax_id", "country", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("code", "legal_name", "trade_name", "tax_id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name", "company", "is_mandatory")
    list_filter = ("company", "is_mandatory")
    search_fields = ("name",)
    date_hierarchy = "date"
    readonly_fields = ("created_at", "updated_at")
