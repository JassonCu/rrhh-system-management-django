from django.contrib import admin

from apps.positions.models import JobGrade, Position


@admin.register(JobGrade)
class JobGradeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "level", "min_salary", "max_salary", "currency", "is_active")
    list_filter = ("is_active", "currency")
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("code", "title", "department", "job_grade", "is_active")
    list_filter = ("department", "job_grade", "is_active")
    search_fields = ("code", "title")
    list_select_related = ("department", "job_grade")
    readonly_fields = ("created_at", "updated_at")
