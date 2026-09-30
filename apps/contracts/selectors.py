"""Consultas de lectura de la relación laboral (ADR-005).

**Este módulo no importa nada de `employees` salvo sus constantes públicas.**
`employees.selectors` lo consulta para resolver el equipo de un jefe; una
importación en sentido contrario crearía un ciclo. El modelo `Employee` se
obtiene a través de la FK del contrato, sin importarlo.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.accounts.constants import Role
from apps.contracts.constants import FINAL_STATUSES, LIVE_STATUSES, ContractStatus
from apps.contracts.models import Assignment, ContractSalary, EmploymentContract
from apps.employees.constants import EmploymentStatus

#: Roles que ven los contratos de toda la organización (§J.2).
ORGANIZATION_WIDE = frozenset({Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER, Role.AUDITOR})

#: Roles que ven **importes** de toda la organización. HR_MANAGER no está: ve
#: contratos pero no salarios, que es la separación que pide la matriz.
SALARY_ORGANIZATION_WIDE = frozenset({Role.SUPERADMIN, Role.HR_ADMIN, Role.AUDITOR})


def _roles_of(user) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def _has_any_role(user, roles: frozenset[str]) -> bool:
    return user.is_superuser or bool(_roles_of(user) & roles)


def _day(on: dt.date | None) -> dt.date:
    # Fecha de Guatemala, no del servidor: con `date.today()` un servidor en UTC
    # cambia de día seis horas antes (hallazgo corregido en la Fase 3).
    return on or timezone.localdate()


def _assignment_covers(on: dt.date) -> Q:
    return Q(start_date__lte=on) & (Q(end_date__isnull=True) | Q(end_date__gte=on))


def contracts_visible_for(user) -> QuerySet[EmploymentContract]:
    """Contratos que este usuario puede ver.

    RRHH y auditoría, toda la organización; cualquier otro, solo los suyos. Un
    `MANAGER` **no** ve los contratos de su equipo (§J.2): la vista se lo impide
    por permiso, y aquí además solo obtendría los propios.
    """
    if not user.is_authenticated:
        return EmploymentContract.objects.none()
    base = EmploymentContract.objects.select_related("employee__person", "company")
    if _has_any_role(user, ORGANIZATION_WIDE):
        return base
    return base.filter(employee__user=user)


def get_contract_or_404(user, *, public_id) -> EmploymentContract:
    """Contrato dentro del alcance; fuera de él, 404 y no 403."""
    return get_object_or_404(contracts_visible_for(user), public_id=public_id)


def can_view_salary(user, contract: EmploymentContract) -> bool:
    """Si este usuario ve los importes de este contrato.

    Hacen falta **las dos** condiciones: el permiso `view_salary` y el alcance
    (rol con visión salarial de toda la organización, o ser el titular). Si por
    error se concediera `view_salary` a `HR_MANAGER`, seguiría viendo solo lo
    suyo: defensa en profundidad frente a una mala asignación de permisos.
    """
    if not user.is_authenticated or not user.has_perm("contracts.view_salary"):
        return False
    if _has_any_role(user, SALARY_ORGANIZATION_WIDE):
        return True
    return contract.employee.user_id is not None and contract.employee.user_id == user.pk


def salaries_for(user, contract: EmploymentContract) -> QuerySet[ContractSalary]:
    if not contracts_visible_for(user).filter(pk=contract.pk).exists():
        return ContractSalary.objects.none()
    if not can_view_salary(user, contract):
        return ContractSalary.objects.none()
    return contract.salaries.select_related("created_by").order_by("-effective_from")


def assignments_for(user, contract: EmploymentContract) -> QuerySet[Assignment]:
    if not contracts_visible_for(user).filter(pk=contract.pk).exists():
        return Assignment.objects.none()
    return contract.assignments.select_related("position__department").order_by("-start_date")


def current_salary(
    contract: EmploymentContract, on: dt.date | None = None
) -> ContractSalary | None:
    day = _day(on)
    return contract.salaries.filter(
        Q(effective_from__lte=day) & (Q(effective_to__isnull=True) | Q(effective_to__gte=day))
    ).first()


def current_primary_assignment(
    contract: EmploymentContract, on: dt.date | None = None
) -> Assignment | None:
    return (
        contract.assignments.filter(_assignment_covers(_day(on)), is_primary=True)
        .select_related("position__job_grade", "position__department")
        .first()
    )


def employee_ids_assigned_to(department_ids: set[int], on: dt.date | None = None) -> set[int]:
    """Empleados con una asignación **vigente** en esos departamentos.

    Resuelve el equipo de un `MANAGER`. Todas las condiciones van en la misma
    consulta sobre `Assignment` para que se refieran a la **misma fila**: con
    filtros encadenados sobre relaciones multivaluadas, una asignación antigua
    podría cumplir la fecha y otra distinta el departamento.
    """
    if not department_ids:
        return set()
    return set(
        Assignment.objects.filter(
            _assignment_covers(_day(on)),
            position__department_id__in=department_ids,
            contract__status__in=LIVE_STATUSES,
        ).values_list("contract__employee_id", flat=True)
    )


def live_contract_for(user, employee) -> EmploymentContract | None:
    """Contrato vigente de esa persona, dentro del alcance de quien consulta."""
    return contracts_visible_for(user).filter(employee=employee, status__in=LIVE_STATUSES).first()


def live_contracts_on(day: dt.date) -> QuerySet[EmploymentContract]:
    """Contratos vivos que ya habían empezado ese día, con su empleado.

    Lo consume el cierre diario de asistencia: necesita saber de quién esperar
    trabajo ese día sin importar el modelo de contratos.
    """
    return EmploymentContract.objects.filter(
        status__in=LIVE_STATUSES, start_date__lte=day
    ).select_related("employee")


def live_contract_of(employee_id: int) -> EmploymentContract | None:
    """Contrato vivo de esa persona, **sin** alcance de usuario.

    Lo usan los servicios de otras apps (asistencia) para responder preguntas del
    dominio —«¿puede marcar hoy?»—, no para decidir qué ve alguien.
    """
    return EmploymentContract.objects.filter(
        employee_id=employee_id, status__in=LIVE_STATUSES
    ).first()


def drafts_for(user) -> QuerySet[EmploymentContract]:
    """Borradores pendientes de activar: trabajo a medias, visible en el inicio."""
    return contracts_visible_for(user).filter(status=ContractStatus.DRAFT).order_by("start_date")


def expiring_soon(
    user, *, days: int = 30, on: dt.date | None = None
) -> QuerySet[EmploymentContract]:
    """Contratos vivos cuyo plazo termina dentro del horizonte indicado."""
    day = _day(on)
    return (
        contracts_visible_for(user)
        .filter(
            status__in=LIVE_STATUSES, end_date__gte=day, end_date__lte=day + dt.timedelta(days=days)
        )
        .order_by("end_date")
    )


def employee_ids_with_live_contract() -> set[int]:
    """Ids de empleados con un vínculo vivo. Sin alcance: se usa para excluir."""
    return set(
        EmploymentContract.objects.filter(status__in=LIVE_STATUSES).values_list(
            "employee_id", flat=True
        )
    )


def position_is_occupied(position_id: int, on: dt.date | None = None) -> bool:
    """Si el puesto tiene asignaciones vigentes o futuras en contratos no cerrados.

    Incluye borradores y fechas futuras: desactivar un puesto comprometido en un
    contrato pendiente dejaría ese contrato apuntando a un puesto inactivo.
    """
    day = _day(on)
    return (
        Assignment.objects.filter(position_id=position_id)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=day))
        .exclude(contract__status__in=FINAL_STATUSES)
        .exists()
    )


def expected_employment_status(employee_id: int) -> tuple[str | None, dt.date | None]:
    """Estado laboral que **deberían** reflejar los contratos (RN-18).

    Devuelve `(None, None)` si el empleado no tiene contratos fuera de borrador:
    no hay de dónde derivar nada.
    """
    contracts = list(
        EmploymentContract.objects.filter(employee_id=employee_id).exclude(
            status=ContractStatus.DRAFT
        )
    )
    statuses = {contract.status for contract in contracts}
    if ContractStatus.ACTIVE.value in statuses:
        return EmploymentStatus.ACTIVE.value, None
    if ContractStatus.SUSPENDED.value in statuses:
        return EmploymentStatus.SUSPENDED.value, None
    finals = [contract for contract in contracts if contract.status in FINAL_STATUSES]
    if finals:
        return EmploymentStatus.TERMINATED.value, max(c.effective_end for c in finals)
    return None, None


def find_status_inconsistencies() -> list[dict[str, str]]:
    """Empleados cuyo estado no coincide con sus contratos.

    `Employee.employment_status` es un estado derivado que se materializa
    (ADR-012). Que coincida con los contratos es una **invariante de servicio**,
    no una restricción de la base; esta función la verifica de punta a punta y
    la usan tanto la prueba de invariante como `check_employment_status`.
    """
    employee_model = EmploymentContract._meta.get_field("employee").related_model
    problems: list[dict[str, str]] = []

    for employee in employee_model.objects.only(
        "pk", "employee_code", "employment_status", "termination_date"
    ).iterator():
        expected, expected_date = expected_employment_status(employee.pk)
        actual = employee.employment_status

        if expected is None:
            consistent = actual == EmploymentStatus.ACTIVE.value
            expected_label = f"{EmploymentStatus.ACTIVE.value} (sin contratos)"
        elif expected == EmploymentStatus.ACTIVE.value:
            # ON_LEAVE lo gestionará el módulo de ausencias (Fase 6) sobre un
            # contrato activo: es compatible.
            consistent = actual in {EmploymentStatus.ACTIVE.value, EmploymentStatus.ON_LEAVE.value}
            expected_label = expected
        else:
            consistent = actual == expected and (
                expected != EmploymentStatus.TERMINATED.value
                or employee.termination_date == expected_date
            )
            expected_label = expected

        if not consistent:
            problems.append(
                {
                    "employee_code": employee.employee_code,
                    "actual": actual,
                    "expected": expected_label,
                }
            )
    return problems
