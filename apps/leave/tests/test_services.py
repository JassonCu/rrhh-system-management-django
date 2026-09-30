"""Invariantes de ausencias (RN-40 a RN-46)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.core.exceptions import ConflictError
from apps.core.models import Holiday
from apps.leave import selectors, services
from apps.leave.constants import LeaveStatus, LedgerEntryType
from apps.leave.models import LeaveEntitlement

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(make_user):
    return make_user("rrhh.ausencias@example.com", Role.HR_ADMIN)


def submitted(ask, employee, leave_type, **kwargs):
    leave_request = ask(employee, leave_type, **kwargs)
    return services.submit_request(leave_request=leave_request, actor=None, request=None)


# --- Días hábiles (RN-42) ------------------------------------------------------ #


def test_working_days_follow_the_schedule(working, vacation, ask) -> None:
    employee = working()

    week = ask(employee, vacation, days=7)  # lunes a domingo

    assert week.working_days == Decimal("5")
    assert week.status == LeaveStatus.DRAFT


def test_company_holidays_are_not_counted(working, vacation, ask, next_monday, company) -> None:
    employee = working()
    Holiday.objects.create(company=company, date=next_monday, name="Feriado de prueba")

    week = ask(employee, vacation)

    assert week.working_days == Decimal("4")


def test_a_weekend_only_request_is_rejected(working, vacation, ask, next_monday) -> None:
    employee = working()

    with pytest.raises(ConflictError) as error:
        ask(employee, vacation, start=next_monday + dt.timedelta(days=5), days=2)

    assert error.value.code == "no_working_days"


def test_without_a_schedule_monday_to_friday_is_assumed(hire, vacation, ask) -> None:
    """Suposición documentada: sin jornada no hay dato, se asume L-V."""
    employee = hire().employee

    assert ask(employee, vacation, days=7).working_days == Decimal("5")


def test_without_a_live_contract_nobody_requests_leave(make_employee, vacation, ask) -> None:
    with pytest.raises(ConflictError) as error:
        ask(make_employee(), vacation)

    assert error.value.code == "no_live_contract"


# --- Reglas de la solicitud ---------------------------------------------------- #


def test_notice_is_enforced(working, vacation, ask) -> None:
    vacation.min_notice_days = 60
    vacation.save()

    with pytest.raises(ConflictError) as error:
        ask(working(), vacation)

    assert error.value.code == "not_enough_notice"


def test_an_inactive_type_cannot_be_requested(working, vacation, ask) -> None:
    vacation.is_active = False
    vacation.save()

    with pytest.raises(ConflictError) as error:
        ask(working(), vacation)

    assert error.value.code == "leave_type_inactive"


def test_submitted_requests_block_the_calendar(working, vacation, ask) -> None:
    """RN-41: una solicitud vigente ocupa sus días."""
    employee = working()
    submitted(ask, employee, vacation)

    with pytest.raises(ConflictError) as error:
        ask(employee, vacation, days=2)

    assert error.value.code == "overlapping_request"


def test_two_overlapping_drafts_cannot_both_be_submitted(working, vacation, ask) -> None:
    """Los borradores no ocupan calendario, así que el traslape se revalida al enviar."""
    employee = working()
    first = ask(employee, vacation)
    second = ask(employee, vacation, days=2)
    services.submit_request(leave_request=first, actor=None, request=None)

    with pytest.raises(ConflictError) as error:
        services.submit_request(leave_request=second, actor=None, request=None)

    assert error.value.code == "overlapping_request"


def test_only_the_owner_submits(working, vacation, ask, make_user) -> None:
    stranger = make_user("ajeno@example.com", Role.EMPLOYEE)
    leave_request = ask(working(), vacation)

    with pytest.raises(ConflictError) as error:
        services.submit_request(leave_request=leave_request, actor=stranger, request=None)

    assert error.value.code == "not_your_request"


def test_undeclared_transitions_are_refused(working, vacation, ask, hr) -> None:
    """RN-45: un borrador no se aprueba sin pasar por el envío."""
    leave_request = ask(working(), vacation)

    with pytest.raises(ConflictError) as error:
        services.approve_request(leave_request=leave_request, actor=hr, request=None)

    assert error.value.code == "invalid_leave_transition"


# --- Aprobación y saldo (RN-43, RN-44, RN-46) ---------------------------------- #


def test_approving_writes_the_consumption(working, vacation, ask, grant, hr) -> None:
    employee = working()
    grant(employee, vacation, "10")
    leave_request = submitted(ask, employee, vacation)

    services.approve_request(leave_request=leave_request, actor=hr, request=None, note="Ok")

    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.APPROVED
    assert leave_request.decided_by == hr
    assert selectors.balance_for(employee, vacation) == Decimal("5")
    entry = employee.leave_ledger.get(entry_type=LedgerEntryType.CONSUMPTION)
    assert entry.days == Decimal("-5")
    assert entry.request == leave_request


def test_approval_cannot_overdraw_the_balance(working, vacation, ask, grant, hr) -> None:
    employee = working()
    grant(employee, vacation, "3")
    leave_request = submitted(ask, employee, vacation)

    with pytest.raises(ConflictError) as error:
        services.approve_request(leave_request=leave_request, actor=hr, request=None)

    assert error.value.code == "insufficient_balance"
    assert selectors.balance_for(employee, vacation) == Decimal("3")


def test_types_that_allow_it_go_negative(working, sick, ask, hr) -> None:
    """Una incapacidad no espera a que haya saldo."""
    employee = working()
    leave_request = submitted(ask, employee, sick)

    services.approve_request(leave_request=leave_request, actor=hr, request=None)

    assert selectors.balance_for(employee, sick) == Decimal("-5")


def test_nobody_approves_their_own_request(
    working, vacation, ask, grant, make_employee, hr
) -> None:
    """RN-44, incluso con rol de RRHH."""
    employee = working(employee=make_employee(user=hr))
    grant(employee, vacation)
    leave_request = submitted(ask, employee, vacation)

    with pytest.raises(ConflictError) as error:
        services.approve_request(leave_request=leave_request, actor=hr, request=None)

    assert error.value.code == "cannot_approve"


def test_a_type_without_approval_is_approved_on_submission(working, errand, ask) -> None:
    employee = working()

    leave_request = submitted(ask, employee, errand, days=1)

    assert leave_request.status == LeaveStatus.APPROVED
    assert selectors.balance_for(employee, errand) == Decimal("-1")
    assert list(
        leave_request.transitions.order_by("created_at", "pk").values_list("to_status", flat=True)
    ) == [
        LeaveStatus.DRAFT,
        LeaveStatus.SUBMITTED,
        LeaveStatus.APPROVED,
    ]


def test_rejecting_requires_a_reason(working, vacation, ask, hr) -> None:
    leave_request = submitted(ask, working(), vacation)

    with pytest.raises(ConflictError) as error:
        services.reject_request(leave_request=leave_request, actor=hr, request=None, note="  ")

    assert error.value.code == "rejection_needs_reason"


def test_rejecting_leaves_the_balance_untouched(working, vacation, ask, grant, hr) -> None:
    employee = working()
    grant(employee, vacation, "10")
    leave_request = submitted(ask, employee, vacation)

    services.reject_request(
        leave_request=leave_request, actor=hr, request=None, note="Cierre de mes"
    )

    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.REJECTED
    assert leave_request.decision_note == "Cierre de mes"
    assert selectors.balance_for(employee, vacation) == Decimal("10")


# --- Cancelación --------------------------------------------------------------- #


def test_cancelling_an_approved_leave_writes_a_reversal(working, vacation, ask, grant, hr) -> None:
    employee = working()
    grant(employee, vacation, "10")
    leave_request = submitted(ask, employee, vacation)
    services.approve_request(leave_request=leave_request, actor=hr, request=None)

    services.cancel_request(leave_request=leave_request, actor=hr, request=None, note="Viaje")

    assert selectors.balance_for(employee, vacation) == Decimal("10")
    # Ningún asiento se borró: el consumo y su reversa quedan a la vista.
    assert set(employee.leave_ledger.values_list("entry_type", flat=True)) == {
        LedgerEntryType.ADJUSTMENT,
        LedgerEntryType.CONSUMPTION,
        LedgerEntryType.REVERSAL,
    }


def test_a_started_leave_cannot_be_cancelled(
    working, vacation, ask, grant, hr, monkeypatch, next_monday
) -> None:
    employee = working()
    grant(employee, vacation)
    leave_request = submitted(ask, employee, vacation)
    services.approve_request(leave_request=leave_request, actor=hr, request=None)
    monkeypatch.setattr(services.timezone, "localdate", lambda: next_monday)

    with pytest.raises(ConflictError) as error:
        services.cancel_request(leave_request=leave_request, actor=hr, request=None)

    assert error.value.code == "leave_already_started"


def test_the_owner_cannot_cancel_an_approved_leave(
    working, vacation, ask, grant, hr, make_user, make_employee
) -> None:
    """Deshacer una aprobación devuelve saldo: lo decide quien aprueba."""
    account = make_user("dueno@example.com", Role.EMPLOYEE)
    employee = working(employee=make_employee(user=account))
    grant(employee, vacation)
    leave_request = submitted(ask, employee, vacation)
    services.approve_request(leave_request=leave_request, actor=hr, request=None)

    with pytest.raises(ConflictError) as error:
        services.cancel_request(leave_request=leave_request, actor=account, request=None)

    assert error.value.code == "cannot_cancel_approved"


def test_the_owner_withdraws_a_pending_request(
    working, vacation, ask, make_user, make_employee
) -> None:
    account = make_user("retira@example.com", Role.EMPLOYEE)
    employee = working(employee=make_employee(user=account))
    leave_request = ask(employee, vacation)
    services.submit_request(leave_request=leave_request, actor=account, request=None)

    services.cancel_request(leave_request=leave_request, actor=account, request=None)

    leave_request.refresh_from_db()
    assert leave_request.status == LeaveStatus.CANCELLED
    assert not employee.leave_ledger.exists()


def test_a_stranger_cannot_withdraw_a_request(working, vacation, ask, make_user) -> None:
    stranger = make_user("otro.ajeno@example.com", Role.EMPLOYEE)
    leave_request = ask(working(), vacation)

    with pytest.raises(ConflictError) as error:
        services.cancel_request(leave_request=leave_request, actor=stranger, request=None)

    assert error.value.code == "not_your_request"


# --- Devengo y ajustes --------------------------------------------------------- #


def test_accrual_grants_a_twelfth_per_month(working, vacation) -> None:
    employee = working()

    entitlement = services.accrue_month(
        employee=employee, leave_type=vacation, month_start=dt.date(2025, 3, 1)
    )

    assert entitlement.granted_days == Decimal("1.25")
    assert entitlement.period_end == dt.date(2025, 3, 31)
    assert selectors.balance_for(employee, vacation) == Decimal("1.25")


def test_accruing_the_same_month_twice_changes_nothing(working, vacation) -> None:
    employee = working()
    month = dt.date(2025, 3, 1)

    services.accrue_month(employee=employee, leave_type=vacation, month_start=month)
    again = services.accrue_month(employee=employee, leave_type=vacation, month_start=month)

    assert again is None
    assert LeaveEntitlement.objects.filter(employee=employee).count() == 1
    assert selectors.balance_for(employee, vacation) == Decimal("1.25")


def test_types_without_annual_days_do_not_accrue(working, sick) -> None:
    assert (
        services.accrue_month(employee=working(), leave_type=sick, month_start=dt.date(2025, 3, 1))
        is None
    )


def test_an_adjustment_needs_a_reason_and_days(working, vacation, hr) -> None:
    employee = working()

    with pytest.raises(ConflictError) as no_reason:
        services.adjust_balance(
            employee=employee,
            leave_type=vacation,
            days=Decimal("1"),
            note="",
            actor=hr,
            request=None,
        )
    with pytest.raises(ConflictError) as no_days:
        services.adjust_balance(
            employee=employee,
            leave_type=vacation,
            days=Decimal("0"),
            note="x",
            actor=hr,
            request=None,
        )

    assert no_reason.value.code == "adjustment_needs_reason"
    assert no_days.value.code == "adjustment_needs_days"


def test_an_adjustment_is_audited(working, vacation, hr) -> None:
    employee = working()

    services.adjust_balance(
        employee=employee,
        leave_type=vacation,
        days=Decimal("2.5"),
        note="Traslado de saldo",
        actor=hr,
        request=None,
    )

    event = AuditEvent.objects.get(action=AuditAction.LEAVE_BALANCE_ADJUST)
    assert event.metadata["days"] == "2.5"
    assert event.metadata["employee_code"] == employee.employee_code


# --- Privacidad en la bitácora -------------------------------------------------- #


@pytest.mark.security
def test_the_reason_never_reaches_the_audit_log(working, sick, ask) -> None:
    """El motivo puede contener datos de salud: la bitácora guarda fechas y tipo."""
    leave_request = ask(working(), sick, reason="Diagnóstico confidencial")
    services.submit_request(leave_request=leave_request, actor=None, request=None)

    event = AuditEvent.objects.get(action=AuditAction.LEAVE_SUBMIT)
    assert "Diagnóstico" not in str(event.metadata)
    assert Decimal(event.metadata["working_days"]) == Decimal("5")


@pytest.mark.security
def test_nobody_adjusts_their_own_balance(working, vacation, make_employee, hr) -> None:
    """Separación de funciones: RRHH tampoco se regala días a sí mismo."""
    employee = working(employee=make_employee(user=hr))

    with pytest.raises(ConflictError) as error:
        services.adjust_balance(
            employee=employee,
            leave_type=vacation,
            days=Decimal("5"),
            note="Autoajuste",
            actor=hr,
            request=None,
        )

    assert error.value.code == "cannot_adjust_own_balance"
    assert not employee.leave_ledger.exists()


def test_editing_a_leave_type_is_audited_with_its_changes(vacation, hr) -> None:
    services.update_leave_type(
        leave_type=vacation,
        actor=hr,
        request=None,
        name=vacation.name,
        default_annual_days=Decimal("20"),
        is_sensitive=True,
    )

    event = AuditEvent.objects.get(action=AuditAction.LEAVE_TYPE_UPDATE)
    assert event.metadata["changes"] == {
        "default_annual_days": {"from": "15.00", "to": "20"},
        "is_sensitive": {"from": "False", "to": "True"},
    }
