from django.contrib import admin

from apps.contracts.models import Assignment, ContractSalary, EmploymentContract


class ContractSalaryInline(admin.TabularInline):
    """Solo lectura: el historial salarial se modifica con `set_salary`, que cierra
    el período anterior. Editarlo aquí rompería la continuidad (RN-21)."""

    model = ContractSalary
    extra = 0
    can_delete = False
    readonly_fields = (
        "amount",
        "currency",
        "pay_frequency",
        "effective_from",
        "effective_to",
        "change_reason",
        "justification",
        "created_by",
    )

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


class AssignmentInline(admin.TabularInline):
    model = Assignment
    extra = 0
    can_delete = False
    readonly_fields = (
        "position",
        "start_date",
        "end_date",
        "is_primary",
        "fte",
        "assignment_reason",
    )

    def has_add_permission(self, request, obj=None) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False


@admin.register(EmploymentContract)
class EmploymentContractAdmin(admin.ModelAdmin):
    """Consulta técnica, **solo lectura**. El ciclo de vida se gestiona desde la
    aplicación, donde los servicios aplican las invariantes y sincronizan el estado
    del empleado. Editar aquí `start_date` o `company` rompería RN-21 y RN-26 sin
    que ningún servicio se enterara (revisión de la Fase 4, H-3)."""

    list_display = ("employee", "contract_type", "status", "start_date", "end_date")
    list_filter = ("status", "contract_type", "company")
    search_fields = ("employee__employee_code",)
    list_select_related = ("employee__person",)
    readonly_fields = (
        "public_id",
        "employee",
        "status",
        "termination_date",
        "termination_reason",
        "created_at",
        "updated_at",
    )
    inlines = [AssignmentInline, ContractSalaryInline]

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
