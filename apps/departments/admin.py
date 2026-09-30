from django.contrib import admin

from apps.departments.models import Department, DepartmentHeadship


@admin.register(DepartmentHeadship)
class DepartmentHeadshipAdmin(admin.ModelAdmin):
    """Hasta que exista una pantalla propia, las jefaturas se gestionan aquí.

    No se borran: el histórico de quién dirigía cada área es lo que permite
    responder quién aprobaba qué. Una jefatura termina poniendo `end_date`.
    """

    list_display = ("department", "employee", "start_date", "end_date")
    list_filter = ("department__company",)
    search_fields = ("department__code", "department__name", "employee__employee_code")
    list_select_related = ("department", "employee__person")
    autocomplete_fields = ("employee",)
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "parent", "company", "cost_center", "is_active")
    list_filter = ("company", "is_active")
    search_fields = ("code", "name", "cost_center")
    list_select_related = ("company", "parent")
    readonly_fields = ("created_at", "updated_at")
