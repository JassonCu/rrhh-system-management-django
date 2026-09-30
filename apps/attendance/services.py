"""Casos de uso de asistencia (Fase 5).

Invariantes que viven aquí porque la base no puede expresarlas:

- **RN-52**: no se marca sin contrato vivo.
- **RN-53**: corregir un marcaje exige motivo y deja rastro en la bitácora.
- Las tardanzas y las horas extra se **detectan** al marcar, comparando con la
  jornada vigente y su tolerancia; nacen como incidencia abierta.
- Separación de funciones: nadie ajusta su propio marcaje ni resuelve su propia
  incidencia, igual que en contratos.

**El marcaje no se audita uno a uno.** Son miles al mes y ahogarían la bitácora;
el propio registro guarda quién lo hizo y desde qué origen. Sí se auditan el
ajuste y la resolución de incidencias, que es donde alguien cambia lo ocurrido.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.attendance import selectors
from apps.attendance.constants import (
    MAX_SEGMENT_HOURS,
    AttendanceSource,
    IncidentStatus,
    IncidentType,
)
from apps.attendance.models import (
    AttendanceEntry,
    AttendanceIncident,
    ScheduleAssignment,
    WorkSchedule,
    WorkScheduleDay,
)
from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.contracts.selectors import live_contract_of
from apps.core.exceptions import ConflictError
from apps.leave.selectors import is_on_leave

ONE_DAY = dt.timedelta(days=1)


# --------------------------------------------------------------------------- #
# Marcaje
# --------------------------------------------------------------------------- #


@transaction.atomic
def check_in(
    *,
    employee,
    actor,
    request: HttpRequest | None,
    at: dt.datetime | None = None,
    source: str = AttendanceSource.SELF,
) -> AttendanceEntry:
    """Registra una entrada y detecta la tardanza contra la jornada vigente."""
    moment = at or timezone.now()

    if live_contract_of(employee.pk) is None:
        raise ConflictError("no_live_contract")  # RN-52
    if selectors.open_entry_for(employee) is not None:
        raise ConflictError("entry_already_open")

    entry = AttendanceEntry(
        employee=employee,
        work_date=timezone.localdate(moment),
        check_in_at=moment,
        source=source,
        registered_by=actor if getattr(actor, "pk", None) else None,
    )
    entry.full_clean()
    entry.save()

    _record_punch_for_other(entry, employee, actor, request)
    _detect_late_arrival(employee, entry)
    return entry


@transaction.atomic
def check_out(
    *,
    employee,
    actor,
    request: HttpRequest | None,
    at: dt.datetime | None = None,
) -> AttendanceEntry:
    """Cierra el segmento abierto y evalúa el día."""
    entry = selectors.open_entry_for(employee)
    if entry is None:
        raise ConflictError("no_open_entry")

    moment = at or timezone.now()
    if moment <= entry.check_in_at:
        raise ConflictError("check_out_before_check_in")
    if moment - entry.check_in_at > dt.timedelta(hours=MAX_SEGMENT_HOURS):
        # Un segmento larguísimo casi siempre es una salida sin marcar: se
        # rechaza y se corrige con un ajuste, que deja motivo.
        raise ConflictError("segment_too_long", hours=MAX_SEGMENT_HOURS)

    entry.check_out_at = moment
    entry.full_clean()
    entry.save(update_fields=["check_out_at", "updated_at"])

    _record_punch_for_other(entry, employee, actor, request)
    _evaluate_day(employee, entry.work_date, moment)
    return entry


@transaction.atomic
def adjust_entry(
    *,
    entry: AttendanceEntry,
    check_in_at: dt.datetime,
    check_out_at: dt.datetime | None,
    reason: str,
    actor,
    request: HttpRequest | None,
) -> AttendanceEntry:
    """Corrige un marcaje. Exige motivo y queda auditado (RN-53)."""
    _ensure_not_own(entry.employee, actor)

    reason = (reason or "").strip()
    if not reason:
        raise ConflictError("adjustment_needs_reason")
    if check_out_at is not None and check_out_at <= check_in_at:
        raise ConflictError("check_out_before_check_in")

    before = {
        "check_in_at": entry.check_in_at.isoformat(),
        "check_out_at": entry.check_out_at.isoformat() if entry.check_out_at else None,
    }

    entry.check_in_at = check_in_at
    entry.check_out_at = check_out_at
    entry.note = reason[:200]
    entry.full_clean()
    entry.save(update_fields=["check_in_at", "check_out_at", "note", "updated_at"])

    # Un ajuste llega después de los hechos: el día ya se puede juzgar entero.
    _evaluate_day(entry.employee, entry.work_date, closing=True)

    record(
        action=AuditAction.ATTENDANCE_ADJUST,
        actor=actor,
        obj=entry,
        request=request,
        metadata={
            "employee_code": entry.employee.employee_code,
            "work_date": entry.work_date.isoformat(),
            "before": before,
            "after": {
                "check_in_at": entry.check_in_at.isoformat(),
                "check_out_at": entry.check_out_at.isoformat() if entry.check_out_at else None,
            },
            "reason": reason,
        },
    )
    return entry


# --------------------------------------------------------------------------- #
# Incidencias
# --------------------------------------------------------------------------- #


@transaction.atomic
def resolve_incident(
    *,
    incident: AttendanceIncident,
    status: str,
    justification: str,
    actor,
    request: HttpRequest | None,
) -> AttendanceIncident:
    """Justifica o rechaza una incidencia.

    Aprobar horas extra es justificar su incidencia: hasta entonces no cuentan
    para pago (decisión de negocio de la Fase 5).
    """
    _ensure_not_own(incident.employee, actor)

    if status not in {IncidentStatus.JUSTIFIED, IncidentStatus.REJECTED}:
        raise ConflictError("invalid_incident_status", status=status)
    if not incident.is_open:
        raise ConflictError("incident_already_resolved")

    justification = (justification or "").strip()
    if not justification:
        raise ConflictError("incident_needs_justification")

    incident.status = status
    incident.justification = justification
    incident.resolved_by = actor if getattr(actor, "pk", None) else None
    incident.resolved_at = timezone.now()
    incident.full_clean()
    incident.save(
        update_fields=["status", "justification", "resolved_by", "resolved_at", "updated_at"]
    )

    record(
        action=AuditAction.ATTENDANCE_INCIDENT_RESOLVE,
        actor=actor,
        obj=incident,
        request=request,
        metadata={
            "employee_code": incident.employee.employee_code,
            "work_date": incident.work_date.isoformat(),
            "incident_type": incident.incident_type,
            "status": status,
            "minutes": incident.minutes,
        },
    )
    return incident


@transaction.atomic
def justify_for_leave(
    *,
    employee,
    start_date: dt.date,
    end_date: dt.date,
    reference: str,
    actor,
    request: HttpRequest | None,
) -> int:
    """Justifica las faltas abiertas en los días de una ausencia recién aprobada.

    Cubre el caso en que el cierre diario corrió **antes** de la aprobación, como
    una incapacidad pedida el mismo día. No se exige separación de funciones
    aquí: la decisión ya la tomó quien aprobó la ausencia, y ese servicio ya la
    exigió (RN-44).

    La justificación cita la solicitud, **nunca su tipo ni su motivo**: la
    jefatura ve las incidencias, y «incapacidad» revelaría un dato de salud.
    """
    incidents = employee.attendance_incidents.select_for_update().filter(
        work_date__range=(start_date, end_date),
        incident_type__in=[IncidentType.ABSENCE, IncidentType.EARLY_LEAVE],
        status=IncidentStatus.OPEN,
    )
    justified = 0
    for incident in incidents:
        incident.status = IncidentStatus.JUSTIFIED
        incident.justification = reference[:300]
        incident.resolved_by = actor if getattr(actor, "pk", None) else None
        incident.resolved_at = timezone.now()
        incident.full_clean()
        incident.save(
            update_fields=["status", "justification", "resolved_by", "resolved_at", "updated_at"]
        )
        record(
            action=AuditAction.ATTENDANCE_INCIDENT_RESOLVE,
            actor=actor,
            obj=incident,
            request=request,
            metadata={
                "employee_code": employee.employee_code,
                "work_date": incident.work_date.isoformat(),
                "incident_type": incident.incident_type,
                "status": IncidentStatus.JUSTIFIED,
                "minutes": incident.minutes,
                "source": "approved_leave",
            },
        )
        justified += 1
    return justified


# --------------------------------------------------------------------------- #
# Jornadas
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_schedule(
    *, actor, request: HttpRequest | None, days: list[dict], **fields
) -> WorkSchedule:
    """Crea una jornada con sus días. Sin días, no hay nada contra qué comparar."""
    if not days:
        raise ConflictError("schedule_needs_days")

    schedule = WorkSchedule(**fields)
    schedule.full_clean()
    schedule.save()

    for day in days:
        entry = WorkScheduleDay(work_schedule=schedule, **day)
        entry.full_clean()
        entry.save()

    record(
        action=AuditAction.WORK_SCHEDULE_CREATE,
        actor=actor,
        obj=schedule,
        request=request,
        metadata={
            "code": schedule.code,
            "weekly_hours": str(schedule.weekly_hours),
            "grace_minutes": schedule.grace_minutes,
            "days": len(days),
        },
    )
    return schedule


@transaction.atomic
def assign_schedule(
    *,
    contract,
    work_schedule: WorkSchedule,
    start_date: dt.date,
    actor,
    request: HttpRequest | None,
) -> ScheduleAssignment:
    """Asigna la jornada a un contrato y cierra la anterior el día previo.

    Nunca se sobrescribe: para recalcular un período antiguo hay que saber qué
    jornada regía entonces (ADR-014).
    """
    _ensure_not_own(contract.employee, actor)

    if not work_schedule.is_active:
        raise ConflictError("schedule_inactive", schedule=work_schedule.code)
    if not contract.covers(start_date):
        raise ConflictError("schedule_outside_contract", day=start_date.isoformat())

    current = (
        ScheduleAssignment.objects.select_for_update()
        .filter(contract=contract, end_date__isnull=True)
        .first()
    )
    if current is not None:
        if start_date <= current.start_date:
            raise ConflictError("schedule_not_after_previous")
        current.end_date = start_date - ONE_DAY
        current.save(update_fields=["end_date", "updated_at"])

    assignment = ScheduleAssignment(
        contract=contract, work_schedule=work_schedule, start_date=start_date
    )
    assignment.full_clean()
    assignment.save()

    record(
        action=AuditAction.WORK_SCHEDULE_ASSIGN,
        actor=actor,
        obj=assignment,
        request=request,
        metadata={
            "employee_code": contract.employee.employee_code,
            "schedule": work_schedule.code,
            "start_date": start_date.isoformat(),
        },
    )
    return assignment


# --------------------------------------------------------------------------- #
# Detección de incidencias
# --------------------------------------------------------------------------- #


def _ensure_not_own(employee, actor) -> None:
    """Separación de funciones: nadie corrige su propia asistencia."""
    actor_id = getattr(actor, "pk", None)
    if actor_id is not None and employee.user_id == actor_id:
        raise ConflictError("cannot_change_own_attendance")


def _detect_late_arrival(employee, entry: AttendanceEntry) -> None:
    """Tardanza = entrada posterior al inicio de la jornada más su tolerancia.

    Solo se evalúa el **primer** segmento del día: volver de almorzar no es
    llegar tarde.
    """
    scheduled = selectors.schedule_day_for(employee, entry.work_date)
    if scheduled is None:
        return
    if selectors.entries_for_day(employee, entry.work_date).exclude(pk=entry.pk).exists():
        return

    expected_start = timezone.make_aware(
        dt.datetime.combine(entry.work_date, scheduled.start_time),
        timezone.get_current_timezone(),
    )
    late = int((timezone.localtime(entry.check_in_at) - expected_start).total_seconds() // 60)
    if late > scheduled.work_schedule.grace_minutes:
        _open_incident(employee, entry.work_date, IncidentType.LATE, late)


def _day_is_over(employee, work_date: dt.date, moment: dt.datetime | None) -> bool:
    """Si la jornada de ese día ya terminó en el momento indicado."""
    if moment is None:
        return False
    scheduled = selectors.schedule_day_for(employee, work_date)
    if scheduled is None:
        return True
    end = timezone.make_aware(
        dt.datetime.combine(work_date, scheduled.end_time), timezone.get_current_timezone()
    )
    return timezone.localtime(moment) >= end


def _evaluate_day(
    employee, work_date: dt.date, moment: dt.datetime | None = None, *, closing: bool = False
) -> None:
    """Compara lo trabajado con lo esperado y abre o actualiza incidencias.

    El **exceso** se sabe en el acto. El **defecto** no: que alguien lleve cuatro
    horas al mediodía no significa que se fue temprano, significa que se fue a
    almorzar. Por eso la salida temprana y la ausencia solo se determinan cuando
    la jornada terminó, o cuando el día se cierra con `close_day`.
    """
    if selectors.open_entry_for(employee) is not None:
        return

    expected = selectors.expected_minutes(employee, work_date)
    worked = selectors.worked_minutes(employee, work_date)

    if worked > expected:
        _open_incident(employee, work_date, IncidentType.OVERTIME, worked - expected)
        return

    if worked == expected or not (closing or _day_is_over(employee, work_date, moment)):
        return

    # Un día de ausencia aprobada no es una falta (Fase 6). El exceso sí se
    # registra: trabajar en vacaciones es un hecho que alguien debe revisar.
    if is_on_leave(employee, work_date):
        return

    incident = IncidentType.ABSENCE if worked == 0 else IncidentType.EARLY_LEAVE
    _open_incident(employee, work_date, incident, expected - worked)


@transaction.atomic
def close_day(*, employee, work_date: dt.date) -> None:
    """Cierra el día de una persona: determina ausencia o salida temprana.

    Es idempotente: se puede ejecutar mil veces y no duplica nada. Lo usa el
    comando diario `close_attendance_day`.
    """
    _evaluate_day(employee, work_date, closing=True)


def _record_punch_for_other(entry, employee, actor, request: HttpRequest | None) -> None:
    """Audita el marcaje **solo cuando lo hace otra persona**.

    El marcaje propio no entra en la bitácora: son miles al mes y ahogarían la
    señal (ADR-021, D-1 de la Fase 5). El propio registro ya guarda quién marcó
    y desde qué origen. Marcar por cuenta de otra persona es otra cosa: es
    excepcional y por eso sí se registra.
    """
    actor_id = getattr(actor, "pk", None)
    if actor_id is None or employee.user_id == actor_id:
        return
    record(
        action=AuditAction.ATTENDANCE_PUNCH_FOR_OTHER,
        actor=actor,
        obj=entry,
        request=request,
        metadata={
            "employee_code": employee.employee_code,
            "work_date": entry.work_date.isoformat(),
            "source": entry.source,
        },
    )


def _open_incident(employee, work_date: dt.date, incident_type: str, minutes: int) -> None:
    """Abre la incidencia o actualiza sus minutos si sigue abierta.

    Una incidencia ya resuelta **no se toca**: alguien la revisó y decidió.
    """
    if minutes <= 0:
        return
    existing = employee.attendance_incidents.filter(
        work_date=work_date, incident_type=incident_type
    ).first()
    if existing is None:
        AttendanceIncident.objects.create(
            employee=employee,
            work_date=work_date,
            incident_type=incident_type,
            minutes=minutes,
            status=IncidentStatus.OPEN,
        )
        return
    if existing.is_open and existing.minutes != minutes:
        existing.minutes = minutes
        existing.save(update_fields=["minutes", "updated_at"])
