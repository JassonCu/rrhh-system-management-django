"""Consultas de lectura de asistencia (ADR-005).

El alcance no se reinventa: se apoya en `employees.employees_visible_for`, que ya
resuelve «lo propio, lo de mi equipo o toda la organización». Si mañana cambia la
regla de alcance, cambia en un solo sitio.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Q, QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.attendance.constants import IncidentStatus
from apps.attendance.models import (
    AttendanceEntry,
    AttendanceIncident,
    ScheduleAssignment,
    WorkSchedule,
    WorkScheduleDay,
)
from apps.contracts.selectors import live_contract_of
from apps.core.models import Holiday
from apps.employees.selectors import employees_visible_for


def _day(on: dt.date | None) -> dt.date:
    return on or timezone.localdate()


def entries_visible_for(user) -> QuerySet[AttendanceEntry]:
    """Marcajes que este usuario puede ver: los de las fichas a su alcance."""
    if not user.is_authenticated:
        return AttendanceEntry.objects.none()
    return AttendanceEntry.objects.filter(employee__in=employees_visible_for(user)).select_related(
        "employee__person"
    )


def incidents_visible_for(user) -> QuerySet[AttendanceIncident]:
    if not user.is_authenticated:
        return AttendanceIncident.objects.none()
    return AttendanceIncident.objects.filter(
        employee__in=employees_visible_for(user)
    ).select_related("employee__person")


def get_entry_or_404(user, *, pk: int) -> AttendanceEntry:
    """Marcaje dentro del alcance; fuera de él, 404 y no 403."""
    return get_object_or_404(entries_visible_for(user), pk=pk)


def get_incident_or_404(user, *, pk: int) -> AttendanceIncident:
    return get_object_or_404(incidents_visible_for(user), pk=pk)


def open_entry_for(employee) -> AttendanceEntry | None:
    """Segmento sin salida. La base garantiza que no haya más de uno."""
    return employee.attendance_entries.filter(check_out_at__isnull=True).first()


def entries_for_day(employee, day: dt.date | None = None) -> QuerySet[AttendanceEntry]:
    return employee.attendance_entries.filter(work_date=_day(day)).order_by("check_in_at")


def worked_minutes(employee, day: dt.date | None = None) -> int:
    """Minutos trabajados en el día, sumando segmentos cerrados.

    No se almacena: guardarlo sería un total que puede divergir del detalle.
    """
    return sum(entry.minutes for entry in entries_for_day(employee, day))


def schedule_assignment_for(contract, on: dt.date | None = None) -> ScheduleAssignment | None:
    """Jornada vigente de un contrato en una fecha."""
    day = _day(on)
    return (
        contract.schedule_assignments.filter(
            Q(end_date__isnull=True) | Q(end_date__gte=day), start_date__lte=day
        )
        .select_related("work_schedule")
        .first()
    )


def schedule_day_for(employee, day: dt.date | None = None) -> WorkScheduleDay | None:
    """Qué debía trabajar esa persona ese día, según su jornada vigente.

    Devuelve `None` si no hay contrato vivo, si no tiene jornada asignada o si
    ese día es de descanso.
    """
    day = _day(day)
    contract = live_contract_of(employee.pk)
    if contract is None:
        return None
    assignment = schedule_assignment_for(contract, day)
    if assignment is None:
        return None
    return assignment.work_schedule.days.filter(weekday=day.weekday()).first()


def is_holiday(company_id: int, day: dt.date) -> bool:
    """Si ese día es feriado para la empresa."""
    return Holiday.objects.filter(company_id=company_id, date=day).exists()


def expected_minutes(employee, day: dt.date | None = None) -> int:
    """Minutos que la jornada espera ese día.

    Cero si es día de descanso, si no hay jornada asignada o si es **feriado**:
    en un feriado no se espera trabajo, así que faltar no es una ausencia y
    trabajar es tiempo extra.
    """
    day = _day(day)
    contract = live_contract_of(employee.pk)
    if contract is None or is_holiday(contract.company_id, day):
        return 0
    scheduled = schedule_day_for(employee, day)
    return scheduled.expected_minutes if scheduled is not None else 0


def open_incidents_for(user) -> QuerySet[AttendanceIncident]:
    return incidents_visible_for(user).filter(status=IncidentStatus.OPEN).order_by("-work_date")


def day_summary(employee, day: dt.date | None = None) -> dict:
    """Resumen de un día: lo esperado, lo trabajado y sus incidencias."""
    day = _day(day)
    return {
        "date": day,
        "expected_minutes": expected_minutes(employee, day),
        "worked_minutes": worked_minutes(employee, day),
        "entries": list(entries_for_day(employee, day)),
        "incidents": list(employee.attendance_incidents.filter(work_date=day)),
        "open_entry": open_entry_for(employee),
    }


def period_summary(employee, start: dt.date, end: dt.date) -> list[dict]:
    """Resumen día a día de un período. Es la base del reporte de la Fase 5."""
    days = (end - start).days
    return [day_summary(employee, start + dt.timedelta(days=offset)) for offset in range(days + 1)]


def schedules_visible_for(user) -> QuerySet[WorkSchedule]:
    """Catálogo de jornadas. Quien tiene el permiso las ve todas."""
    if not user.is_authenticated or not user.has_perm("attendance.view_workschedule"):
        return WorkSchedule.objects.none()
    return WorkSchedule.objects.prefetch_related("days")
