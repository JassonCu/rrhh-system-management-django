"""Consultas de lectura de ausencias (ADR-005).

El alcance se apoya en `employees_visible_for`, como asistencia: lo propio, lo
del equipo o toda la organización. Aquí se añade una regla propia de la fase:
**quién puede aprobar qué**, que sube por el organigrama.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db.models import QuerySet, Sum
from django.shortcuts import get_object_or_404

from apps.accounts.constants import Role
from apps.departments.selectors import departments_headed_by
from apps.employees.selectors import employees_visible_for
from apps.leave.constants import BLOCKING_STATUSES, LeaveStatus
from apps.leave.models import LeaveLedgerEntry, LeaveRequest, LeaveType

#: Roles que aprueban en toda la organización (§J.2).
HR_ROLES = frozenset({Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER})


def _roles_of(user) -> set[str]:
    return set(user.groups.values_list("name", flat=True))


def _is_hr(user) -> bool:
    return user.is_superuser or bool(_roles_of(user) & HR_ROLES)


def types_visible_for(user) -> QuerySet[LeaveType]:
    if not user.is_authenticated or not user.has_perm("leave.view_leavetype"):
        return LeaveType.objects.none()
    return LeaveType.objects.all()


def requests_visible_for(user) -> QuerySet[LeaveRequest]:
    """Solicitudes de las fichas al alcance de quien consulta."""
    if not user.is_authenticated:
        return LeaveRequest.objects.none()
    return LeaveRequest.objects.filter(employee__in=employees_visible_for(user)).select_related(
        "employee__person", "leave_type"
    )


def get_request_or_404(user, *, public_id) -> LeaveRequest:
    """Solicitud dentro del alcance; fuera de él, 404 y no 403."""
    return get_object_or_404(requests_visible_for(user), public_id=public_id)


def own_requests(user) -> QuerySet[LeaveRequest]:
    return requests_visible_for(user).filter(employee__user=user)


# --- Quién aprueba ----------------------------------------------------------- #


def approver_departments_for(employee) -> list[int]:
    """Departamentos cuya jefatura puede decidir sobre esta persona.

    Empieza por el departamento donde está asignada y **sube** por el
    organigrama. La escalada existe porque la jefatura no puede aprobar su
    propia solicitud (RN-44) y porque un área puede quedarse sin jefatura: sin
    escalada, el equipo se congela (decisión de negocio de la Fase 6).
    """
    from apps.contracts.selectors import current_primary_assignment, live_contract_of

    contract = live_contract_of(employee.pk)
    if contract is None:
        return []
    assignment = current_primary_assignment(contract)
    if assignment is None:
        return []

    chain: list[int] = []
    department = assignment.position.department
    seen: set[int] = set()
    while department is not None and department.pk not in seen:
        seen.add(department.pk)
        chain.append(department.pk)
        department = department.parent
    return chain


def can_approve(user, request: LeaveRequest) -> bool:
    """Si este usuario puede decidir sobre esa solicitud.

    Hacen falta tres cosas: el permiso, **no ser quien solicita** (RN-44) y
    tener autoridad sobre la persona, sea por rol de RRHH o por jefatura en su
    departamento o en alguno superior.
    """
    if not user.is_authenticated or not user.has_perm("leave.approve_leave"):
        return False
    if request.employee.user_id is not None and request.employee.user_id == user.pk:
        return False  # RN-44: nadie aprueba lo suyo
    if _is_hr(user):
        return True
    headed = departments_headed_by(user)
    return bool(headed & set(approver_departments_for(request.employee)))


def pending_for(user) -> QuerySet[LeaveRequest]:
    """Bandeja de aprobación: lo que este usuario puede decidir hoy."""
    pending = requests_visible_for(user).filter(status=LeaveStatus.SUBMITTED)
    if _is_hr(user):
        return pending.exclude(employee__user=user).order_by("start_date")
    approvable = [item.pk for item in pending if can_approve(user, item)]
    return pending.filter(pk__in=approvable).order_by("start_date")


# --- Saldos ------------------------------------------------------------------- #


# --- Antigüedad ------------------------------------------------------------- #


def years_of_service(employee, on: dt.date) -> int:
    """Años **cumplidos** desde la fecha de ingreso, a esa fecha."""
    hired = employee.hire_date
    years = on.year - hired.year - ((on.month, on.day) < (hired.month, hired.day))
    return max(0, years)


def annual_days_for(leave_type: LeaveType, years: int) -> Decimal:
    """Días por año que corresponden con esa antigüedad.

    El tramo de mayor antigüedad alcanzada; sin tramo, los días base del tipo.
    """
    tier = (
        leave_type.accrual_tiers.filter(min_years_of_service__lte=years)
        .order_by("-min_years_of_service")
        .first()
    )
    return tier.annual_days if tier is not None else leave_type.default_annual_days


def ledger_for(employee, leave_type: LeaveType | None = None) -> QuerySet[LeaveLedgerEntry]:
    entries = employee.leave_ledger.select_related("leave_type", "request").order_by("-created_at")
    return entries.filter(leave_type=leave_type) if leave_type else entries


def balance_for(employee, leave_type: LeaveType) -> Decimal:
    """Saldo = suma del libro. No se almacena en ninguna columna (ADR-015)."""
    total = employee.leave_ledger.filter(leave_type=leave_type).aggregate(total=Sum("days"))
    return total["total"] or Decimal("0")


def pending_days_for(employee, leave_type: LeaveType, *, exclude=None) -> Decimal:
    """Días ya comprometidos en solicitudes enviadas y aún sin decidir.

    No descuentan saldo (eso ocurre al aprobar), pero quien revisa o decide
    tiene que verlos: aprobar dos solicitudes contra el mismo saldo es posible
    si nadie los suma.
    """
    pending = employee.leave_requests.filter(leave_type=leave_type, status=LeaveStatus.SUBMITTED)
    if exclude is not None:
        pending = pending.exclude(pk=exclude.pk)
    return pending.aggregate(total=Sum("working_days"))["total"] or Decimal("0")


def balances_for(employee) -> list[dict]:
    """Saldo por tipo activo, con lo devengado y lo consumido por separado."""
    balances = []
    for leave_type in LeaveType.objects.filter(is_active=True).order_by("code"):
        entries = employee.leave_ledger.filter(leave_type=leave_type)
        accrued = entries.filter(days__gt=0).aggregate(total=Sum("days"))["total"] or Decimal("0")
        used = entries.filter(days__lt=0).aggregate(total=Sum("days"))["total"] or Decimal("0")
        balances.append(
            {
                "leave_type": leave_type,
                "accrued": accrued,
                "used": -used,
                "available": accrued + used,
            }
        )
    return balances


# --- Calendario ---------------------------------------------------------------- #


def is_on_leave(employee, day: dt.date) -> bool:
    """Si la persona tiene una ausencia **aprobada** que cubre ese día.

    Lo consulta asistencia al cerrar el día: una ausencia aprobada no es una falta.
    """
    return employee.leave_requests.filter(
        status=LeaveStatus.APPROVED, start_date__lte=day, end_date__gte=day
    ).exists()


def overlapping_requests(employee, start: dt.date, end: dt.date) -> QuerySet[LeaveRequest]:
    """Solicitudes que ocupan calendario en ese rango (RN-41)."""
    return employee.leave_requests.filter(
        status__in=BLOCKING_STATUSES, start_date__lte=end, end_date__gte=start
    )


def team_calendar(user, start: dt.date, end: dt.date) -> list[dict]:
    """Quién falta cada día, **sin revelar el tipo cuando es sensible**.

    Incapacidad y duelo se muestran como ausencia genérica a terceros: revelan
    salud o intimidad (§G.19). RRHH y la propia persona sí ven el tipo.
    """
    requests = (
        requests_visible_for(user)
        .filter(status__in=BLOCKING_STATUSES, start_date__lte=end, end_date__gte=start)
        .order_by("employee__person__last_name", "start_date")
    )

    rows: dict[int, dict] = {}
    for item in requests:
        employee = item.employee
        is_own = employee.user_id is not None and employee.user_id == user.pk
        shows_type = is_own or _is_hr(user) or not item.leave_type.is_sensitive
        row = rows.setdefault(employee.pk, {"employee": employee, "days": {}})
        day = max(item.start_date, start)
        while day <= min(item.end_date, end):
            row["days"][day] = {
                "request": item,
                "label": item.leave_type.name if shows_type else None,
                "status": item.status,
            }
            day += dt.timedelta(days=1)
    return list(rows.values())
