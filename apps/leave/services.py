"""Casos de uso de ausencias (Fase 6).

Invariantes que viven aquí porque la base no puede expresarlas:

- **RN-41**: las solicitudes vigentes de una persona no se traslapan.
- **RN-42**: los días se cuentan en **hábiles**, según la jornada y los feriados.
- **RN-43**: aprobar no puede dejar el saldo negativo, salvo tipos que lo admitan.
- **RN-44**: quien aprueba no puede ser quien solicita.
- **RN-45**: la máquina de estados rechaza lo que no está declarado.
- **RN-46**: aprobar asienta consumo; cancelar asienta la reversa. **Nunca se
  edita ni se borra un asiento.**
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.attendance.selectors import expected_minutes
from apps.attendance.services import justify_for_leave
from apps.audit.constants import AuditAction
from apps.audit.services import record
from apps.contracts.selectors import live_contract_of, live_contracts_on
from apps.core.exceptions import ConflictError
from apps.leave import selectors
from apps.leave.constants import (
    ALLOWED_TRANSITIONS,
    DAYS_QUANTUM,
    MONTHS_PER_YEAR,
    EntitlementSource,
    LeaveStatus,
    LedgerEntryType,
)
from apps.leave.models import (
    LeaveAccrualTier,
    LeaveEntitlement,
    LeaveLedgerEntry,
    LeaveRequest,
    LeaveRequestTransition,
    LeaveType,
)

ONE_DAY = dt.timedelta(days=1)

#: Días hábiles por defecto cuando la persona aún no tiene jornada asignada.
#: Se documenta a propósito: es una suposición, no un dato.
DEFAULT_WORKING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})


# --------------------------------------------------------------------------- #
# Cálculo de días
# --------------------------------------------------------------------------- #


def working_days_between(employee, start: dt.date, end: dt.date) -> Decimal:
    """Días hábiles del rango, según la jornada vigente y los feriados (RN-42).

    Si la persona todavía no tiene jornada asignada se asume lunes a viernes: es
    una suposición explícita, no un dato, y la pantalla lo advierte.
    """
    contract = live_contract_of(employee.pk)
    if contract is None:
        raise ConflictError("no_live_contract")

    days = Decimal("0")
    day = start
    has_schedule = contract.schedule_assignments.exists()
    while day <= end:
        if has_schedule:
            if expected_minutes(employee, day) > 0:
                days += 1
        elif day.weekday() in DEFAULT_WORKING_WEEKDAYS:
            days += 1
        day += ONE_DAY
    return days


# --------------------------------------------------------------------------- #
# Solicitud
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_request(
    *,
    employee,
    leave_type,
    start_date: dt.date,
    end_date: dt.date,
    reason: str,
    actor,
    request: HttpRequest | None,
) -> LeaveRequest:
    """Crea la solicitud en borrador, con sus días hábiles ya calculados."""
    if not leave_type.is_active:
        raise ConflictError("leave_type_inactive", leave_type=leave_type.code)
    if end_date < start_date:
        raise ConflictError("dates_unordered")
    if selectors.overlapping_requests(employee, start_date, end_date).exists():
        raise ConflictError("overlapping_request")  # RN-41

    _ensure_timing(leave_type, start_date)

    days = working_days_between(employee, start_date, end_date)
    if days <= 0:
        raise ConflictError("no_working_days")

    leave_request = LeaveRequest(
        employee=employee,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        working_days=days,
        reason=(reason or "").strip(),
        status=LeaveStatus.DRAFT,
    )
    leave_request.full_clean()
    leave_request.save()

    _record_transition(leave_request, "", LeaveStatus.DRAFT, actor, "")
    record(
        action=AuditAction.LEAVE_CREATE,
        actor=actor,
        obj=leave_request,
        request=request,
        metadata=_metadata(leave_request),
    )
    return leave_request


@transaction.atomic
def submit_request(
    *, leave_request: LeaveRequest, actor, request: HttpRequest | None
) -> LeaveRequest:
    """Envía a aprobación. Un tipo que no la requiere se aprueba en el acto."""
    _lock_requests_of(leave_request.employee_id)
    leave_request = _lock(leave_request)
    _ensure_transition(leave_request, LeaveStatus.SUBMITTED)
    _ensure_owner(leave_request, actor)
    # Se revalida: un borrador olvidado no puede enviarse fuera de plazo.
    _ensure_timing(leave_request.leave_type, leave_request.start_date)

    # El traslape se valida al crear, pero los borradores no ocupan calendario:
    # dos borradores traslapados son válidos y solo uno puede enviarse.
    overlapping = selectors.overlapping_requests(
        leave_request.employee, leave_request.start_date, leave_request.end_date
    ).exclude(pk=leave_request.pk)
    if overlapping.exists():
        raise ConflictError("overlapping_request")  # RN-41

    _change_status(leave_request, LeaveStatus.SUBMITTED, actor, "")
    record(
        action=AuditAction.LEAVE_SUBMIT,
        actor=actor,
        obj=leave_request,
        request=request,
        metadata=_metadata(leave_request),
    )

    if not leave_request.leave_type.requires_approval:
        # Sin aprobación, el envío y la aprobación son el mismo acto —incluida
        # la comprobación de saldo. Queda constancia igual: la transición lleva
        # la nota.
        _approve(leave_request, actor, request, note="Type does not require approval")
    return leave_request


@transaction.atomic
def approve_request(
    *, leave_request: LeaveRequest, actor, request: HttpRequest | None, note: str = ""
) -> LeaveRequest:
    """Aprueba y asienta el consumo (RN-43, RN-44, RN-46)."""
    _lock_requests_of(leave_request.employee_id)
    leave_request = _lock(leave_request)
    _ensure_transition(leave_request, LeaveStatus.APPROVED)

    if not selectors.can_approve(actor, leave_request):
        raise ConflictError("cannot_approve")

    return _approve(leave_request, actor, request, note=note)


@transaction.atomic
def reject_request(
    *, leave_request: LeaveRequest, actor, request: HttpRequest | None, note: str
) -> LeaveRequest:
    """Rechaza. El motivo es obligatorio: lo va a leer la persona."""
    leave_request = _lock(leave_request)
    _ensure_transition(leave_request, LeaveStatus.REJECTED)

    if not selectors.can_approve(actor, leave_request):
        raise ConflictError("cannot_approve")

    note = (note or "").strip()
    if not note:
        raise ConflictError("rejection_needs_reason")

    _change_status(leave_request, LeaveStatus.REJECTED, actor, note, decided=True)
    record(
        action=AuditAction.LEAVE_REJECT,
        actor=actor,
        obj=leave_request,
        request=request,
        metadata=_metadata(leave_request),
    )
    return leave_request


@transaction.atomic
def cancel_request(
    *, leave_request: LeaveRequest, actor, request: HttpRequest | None, note: str = ""
) -> LeaveRequest:
    """Cancela. Si estaba aprobada, asienta la reversa del consumo (RN-46)."""
    leave_request = _lock(leave_request)
    _ensure_transition(leave_request, LeaveStatus.CANCELLED)

    was_approved = leave_request.status == LeaveStatus.APPROVED
    if was_approved:
        # Una ausencia ya disfrutada no se cancela: eso sería reescribir el pasado.
        if leave_request.start_date <= timezone.localdate():
            raise ConflictError("leave_already_started")
        if not selectors.can_approve(actor, leave_request):
            raise ConflictError("cannot_cancel_approved")
    else:
        _ensure_owner_or_approver(leave_request, actor)

    _change_status(leave_request, LeaveStatus.CANCELLED, actor, note)

    if was_approved:
        _write_entry(
            leave_request.employee,
            leave_request.leave_type,
            LedgerEntryType.REVERSAL,
            leave_request.working_days,
            actor,
            leave_request=leave_request,
            note=note,
        )

    record(
        action=AuditAction.LEAVE_CANCEL,
        actor=actor,
        obj=leave_request,
        request=request,
        metadata=_metadata(leave_request),
    )
    return leave_request


# --------------------------------------------------------------------------- #
# Saldos
# --------------------------------------------------------------------------- #


@transaction.atomic
def accrue_month(*, employee, leave_type, month_start: dt.date) -> LeaveEntitlement | None:
    """Devenga el mes: derecho del período y su asiento en el libro.

    Los días salen del tramo de antigüedad vigente al inicio del mes. Es
    idempotente: el índice único del período impide devengar dos veces.
    """
    if month_start.day != 1:
        raise ConflictError("month_must_start_the_month", month=month_start.isoformat())
    if month_start < employee.hire_date.replace(day=1):
        # Un mes anterior al ingreso no se devenga: nadie trabajó ese mes.
        return None
    # El contrato tiene que haber empezado antes de ese mes, no solo existir
    # hoy. Límite conocido: un contrato ya terminado no se puede devengar hacia
    # atrás, porque no hay selector de contratos por fecha que alcance a los
    # terminados; queda anotado como pendiente.
    if not live_contracts_on(month_start).filter(employee=employee).exists():
        return None
    years = selectors.years_of_service(employee, month_start)
    annual = selectors.annual_days_for(leave_type, years)
    if annual <= 0:
        return None

    month_end = (month_start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - ONE_DAY
    if LeaveEntitlement.objects.filter(
        employee=employee, leave_type=leave_type, period_start=month_start
    ).exists():
        return None

    granted = _monthly_share(annual, month_start.month)
    entitlement = LeaveEntitlement(
        employee=employee,
        leave_type=leave_type,
        period_start=month_start,
        period_end=month_end,
        granted_days=granted,
        source=EntitlementSource.ACCRUAL,
    )
    entitlement.full_clean()
    try:
        with transaction.atomic():
            entitlement.save()
    except IntegrityError:
        # Dos ejecuciones simultáneas del comando: el índice único ya hizo su
        # trabajo, y repetir el devengo no es un error que deba cortar el mes.
        return None

    _write_entry(
        employee,
        leave_type,
        LedgerEntryType.ACCRUAL,
        granted,
        None,
        entitlement=entitlement,
        # Explica el cálculo sin consultar nada más: mes, antigüedad y días/año.
        note=f"{month_start:%Y-%m} years={years} annual={annual}",
    )
    # El devengo mueve el saldo de una persona: deja rastro aunque lo ejecute
    # una tarea programada y no un humano.
    record(
        action=AuditAction.LEAVE_ACCRUAL,
        actor=None,
        obj=entitlement,
        request=None,
        metadata={
            "employee_code": employee.employee_code,
            "leave_type": leave_type.code,
            "period": f"{month_start:%Y-%m}",
            "granted_days": str(granted),
            "years_of_service": years,
        },
    )
    return entitlement


@transaction.atomic
def adjust_balance(
    *, employee, leave_type, days: Decimal, note: str, actor, request: HttpRequest | None
) -> LeaveLedgerEntry:
    """Corrección manual de saldo. Exige motivo y queda auditada.

    Nadie ajusta su propio saldo: es separación de funciones, igual que nadie
    modifica su propia relación laboral (RN-44 aplicado a saldos).
    """
    actor_id = getattr(actor, "pk", None)
    if actor_id is not None and employee.user_id == actor_id:
        raise ConflictError("cannot_adjust_own_balance")
    # Un ajuste mueve el mismo saldo que una aprobación: se serializa con ella,
    # o una resta simultánea deja el saldo negativo sin que nadie lo vea.
    _lock_requests_of(employee.pk)
    note = (note or "").strip()
    if not note:
        raise ConflictError("adjustment_needs_reason")
    if days == 0:
        raise ConflictError("adjustment_needs_days")

    entry = _write_entry(employee, leave_type, LedgerEntryType.ADJUSTMENT, days, actor, note=note)
    record(
        action=AuditAction.LEAVE_BALANCE_ADJUST,
        actor=actor,
        obj=entry,
        request=request,
        metadata={
            "employee_code": employee.employee_code,
            "leave_type": leave_type.code,
            "days": str(days),
            "note": note,
        },
    )
    return entry


# --------------------------------------------------------------------------- #
# Catálogo de tipos
# --------------------------------------------------------------------------- #


@transaction.atomic
def create_leave_type(*, actor, request: HttpRequest | None, **fields) -> LeaveType:
    """Alta de un tipo. Cambia lo que se devenga en toda la organización: se audita."""
    leave_type = LeaveType(**fields)
    leave_type.full_clean()
    leave_type.save()
    record(
        action=AuditAction.LEAVE_TYPE_CREATE,
        actor=actor,
        obj=leave_type,
        request=request,
        metadata={"code": leave_type.code, "annual_days": str(leave_type.default_annual_days)},
    )
    return leave_type


@transaction.atomic
def update_leave_type(
    *, leave_type: LeaveType, actor, request: HttpRequest | None, **fields
) -> LeaveType:
    """Edición auditada con el antes y el después de lo que cambió."""
    # Contra la fila de la base: la instancia de un ModelForm ya trae lo nuevo.
    stored = LeaveType.objects.select_for_update().get(pk=leave_type.pk)
    new_base = fields.get("default_annual_days", stored.default_annual_days)
    if stored.accrual_tiers.filter(annual_days__lt=new_base).exists():
        # Subir el piso por encima de un tramo dejaría a los más antiguos con
        # menos días que a los nuevos.
        raise ConflictError("base_above_a_tier")
    changes = {
        name: {"from": str(getattr(stored, name)), "to": str(value)}
        for name, value in fields.items()
        if getattr(stored, name) != value
    }
    for name, value in fields.items():
        setattr(leave_type, name, value)
    leave_type.full_clean()
    leave_type.save()
    record(
        action=AuditAction.LEAVE_TYPE_UPDATE,
        actor=actor,
        obj=leave_type,
        request=request,
        metadata={"code": leave_type.code, "changes": changes},
    )
    return leave_type


@transaction.atomic
def add_accrual_tier(
    *,
    leave_type: LeaveType,
    min_years_of_service: int,
    annual_days: Decimal,
    actor,
    request: HttpRequest | None,
) -> LeaveAccrualTier:
    """Añade un tramo por antigüedad. Nunca por debajo del piso ni de un tramo menor.

    «Conforme a la legislación y sin ser injustos» (decisión de negocio): a más
    antigüedad, nunca menos días.
    """
    leave_type = LeaveType.objects.select_for_update().get(pk=leave_type.pk)
    if annual_days < leave_type.default_annual_days:
        raise ConflictError("tier_below_base", base=str(leave_type.default_annual_days))

    tiers = leave_type.accrual_tiers
    if tiers.filter(min_years_of_service=min_years_of_service).exists():
        raise ConflictError("tier_already_exists")
    lower = (
        tiers.filter(min_years_of_service__lt=min_years_of_service)
        .order_by("-min_years_of_service")
        .first()
    )
    higher = (
        tiers.filter(min_years_of_service__gt=min_years_of_service)
        .order_by("min_years_of_service")
        .first()
    )
    if lower is not None and annual_days < lower.annual_days:
        raise ConflictError("tier_below_previous", previous=str(lower.annual_days))
    if higher is not None and annual_days > higher.annual_days:
        raise ConflictError("tier_above_next", next=str(higher.annual_days))

    tier = LeaveAccrualTier(
        leave_type=leave_type,
        min_years_of_service=min_years_of_service,
        annual_days=annual_days,
    )
    tier.full_clean()
    tier.save()
    record(
        action=AuditAction.LEAVE_TYPE_UPDATE,
        actor=actor,
        obj=leave_type,
        request=request,
        metadata={
            "code": leave_type.code,
            "tier_added": {"from_years": min_years_of_service, "annual_days": str(annual_days)},
        },
    )
    return tier


@transaction.atomic
def remove_accrual_tier(*, tier: LeaveAccrualTier, actor, request: HttpRequest | None) -> None:
    """Quita un tramo. Lo ya devengado no cambia: está en el libro."""
    leave_type = tier.leave_type
    snapshot = {"from_years": tier.min_years_of_service, "annual_days": str(tier.annual_days)}
    tier.delete()
    record(
        action=AuditAction.LEAVE_TYPE_UPDATE,
        actor=actor,
        obj=leave_type,
        request=request,
        metadata={"code": leave_type.code, "tier_removed": snapshot},
    )


# --------------------------------------------------------------------------- #
# Internas
# --------------------------------------------------------------------------- #


def _monthly_share(annual: Decimal, month: int) -> Decimal:
    """Doceava parte del año **sin deriva**: doce meses suman los días anuales.

    Redondear cada mes por separado no cuadra al cabo del año: 20/12 son 1.67,
    y doce veces 1.67 son 20.04 días inventados. Se reparte por diferencia
    contra lo acumulado hasta el mes anterior, así el último mes absorbe el
    resto y la suma es exacta.
    """
    accumulated = (annual * month / MONTHS_PER_YEAR).quantize(DAYS_QUANTUM)
    previous = (annual * (month - 1) / MONTHS_PER_YEAR).quantize(DAYS_QUANTUM)
    return accumulated - previous


def _lock(leave_request: LeaveRequest) -> LeaveRequest:
    return LeaveRequest.objects.select_for_update().get(pk=leave_request.pk)


def _lock_requests_of(employee_id: int) -> None:
    """Serializa las operaciones que leen el calendario o el saldo de alguien.

    Sin este bloqueo, dos envíos simultáneos de borradores traslapados (RN-41)
    o dos aprobaciones simultáneas contra el mismo saldo (RN-43) pasarían cada
    una su chequeo sin ver a la otra. En SQLite es inocuo; en PostgreSQL toma
    un bloqueo de fila por solicitud de la persona.
    """
    list(
        LeaveRequest.objects.select_for_update()
        .filter(employee_id=employee_id)
        .values_list("pk", flat=True)
    )


def _ensure_timing(leave_type: LeaveType, start_date: dt.date) -> None:
    """Preaviso para lo futuro; ventana de registro retroactivo para lo pasado.

    Un accidente de hoy puede reportarse pasado mañana: el tipo decide cuántos
    días hacia atrás admite (`max_backdating_days`). Lo que no lo admite exige
    que la ausencia empiece hoy o después.
    """
    offset = (start_date - timezone.localdate()).days
    if offset < 0:
        allowed = leave_type.max_backdating_days
        if -offset > allowed:
            raise ConflictError("too_far_in_the_past", allowed=allowed)
        return
    if offset < leave_type.min_notice_days:
        raise ConflictError("not_enough_notice", required=leave_type.min_notice_days)


def _ensure_transition(leave_request: LeaveRequest, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS[leave_request.status]:
        raise ConflictError("invalid_leave_transition", current=leave_request.status, target=target)


def _ensure_owner(leave_request: LeaveRequest, actor) -> None:
    actor_id = getattr(actor, "pk", None)
    if actor_id is not None and leave_request.employee.user_id != actor_id:
        raise ConflictError("not_your_request")


def _ensure_owner_or_approver(leave_request: LeaveRequest, actor) -> None:
    actor_id = getattr(actor, "pk", None)
    if actor_id is None:
        return
    if leave_request.employee.user_id == actor_id:
        return
    if not selectors.can_approve(actor, leave_request):
        raise ConflictError("not_your_request")


def _approve(leave_request: LeaveRequest, actor, request, *, note: str) -> LeaveRequest:
    """Aprueba y asienta el consumo.

    La comprobación de saldo vive **aquí**, no en `approve_request`: un tipo que
    no requiere aprobación se aprueba al enviarse, y por ese camino RN-43 se
    saltaba. Todo lo que escribe un consumo pasa por esta función.
    """
    _ensure_balance(leave_request)
    _change_status(leave_request, LeaveStatus.APPROVED, actor, note, decided=True)
    _write_entry(
        leave_request.employee,
        leave_request.leave_type,
        LedgerEntryType.CONSUMPTION,
        -leave_request.working_days,
        actor,
        leave_request=leave_request,
        note=note,
    )
    # Las faltas que el cierre diario haya abierto en esos días dejan de serlo.
    justify_for_leave(
        employee=leave_request.employee,
        start_date=leave_request.start_date,
        end_date=leave_request.end_date,
        reference=f"Approved leave {leave_request.public_id}",
        actor=actor,
        request=request,
    )
    record(
        action=AuditAction.LEAVE_APPROVE,
        actor=actor,
        obj=leave_request,
        request=request,
        metadata=_metadata(leave_request),
    )
    return leave_request


def _ensure_balance(leave_request: LeaveRequest) -> None:
    """RN-43: aprobar no deja el saldo negativo, salvo tipos que lo admitan."""
    leave_type = leave_request.leave_type
    if leave_type.allows_negative_balance:
        return
    balance = selectors.balance_for(leave_request.employee, leave_type)
    if balance - leave_request.working_days < 0:
        raise ConflictError(
            "insufficient_balance",
            available=str(balance),
            requested=str(leave_request.working_days),
        )


def _change_status(
    leave_request: LeaveRequest, target: str, actor, note: str, *, decided: bool = False
) -> None:
    previous = leave_request.status
    leave_request.status = target
    fields = ["status", "updated_at"]

    if decided:
        leave_request.decided_by = actor if getattr(actor, "pk", None) else None
        leave_request.decided_at = timezone.now()
        leave_request.decision_note = (note or "")[:300]
        fields += ["decided_by", "decided_at", "decision_note"]

    leave_request.save(update_fields=fields)
    _record_transition(leave_request, previous, target, actor, note)


def _record_transition(
    leave_request: LeaveRequest, previous: str, target: str, actor, note: str
) -> None:
    LeaveRequestTransition.objects.create(
        request=leave_request,
        from_status=previous,
        to_status=target,
        actor=actor if getattr(actor, "pk", None) else None,
        note=(note or "")[:300],
    )


def _write_entry(
    employee,
    leave_type,
    entry_type: str,
    days: Decimal,
    actor,
    *,
    leave_request: LeaveRequest | None = None,
    entitlement: LeaveEntitlement | None = None,
    note: str = "",
) -> LeaveLedgerEntry:
    entry = LeaveLedgerEntry(
        employee=employee,
        leave_type=leave_type,
        entry_type=entry_type,
        days=days,
        request=leave_request,
        entitlement=entitlement,
        note=(note or "")[:300],
        created_by=actor if getattr(actor, "pk", None) else None,
    )
    entry.full_clean()
    entry.save()
    return entry


def _metadata(leave_request: LeaveRequest) -> dict:
    """Metadata de auditoría: sin el motivo, que puede contener datos de salud.

    `backdated_days` deja a la vista el registro retroactivo, que es donde una
    ausencia se presta más a abuso.
    """
    registered_on = timezone.localtime(leave_request.created_at).date()
    return {
        "backdated_days": max(0, (registered_on - leave_request.start_date).days),
        "employee_code": leave_request.employee.employee_code,
        "leave_type": leave_request.leave_type.code,
        "start_date": leave_request.start_date.isoformat(),
        "end_date": leave_request.end_date.isoformat(),
        "working_days": str(leave_request.working_days),
        "status": leave_request.status,
    }
