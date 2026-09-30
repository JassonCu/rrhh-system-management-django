"""Restricciones de base de datos y libro append-only (ADR-015)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.leave.constants import LeaveStatus, LedgerEntryType
from apps.leave.models import (
    LeaveEntitlement,
    LeaveLedgerEntry,
    LeaveRequest,
    LeaveRequestTransition,
    LedgerImmutableError,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def entry(working, vacation, grant) -> LeaveLedgerEntry:
    employee = working()
    grant(employee, vacation, "3")
    return employee.leave_ledger.get()


# --- Libro append-only --------------------------------------------------------- #


@pytest.mark.security
def test_a_ledger_entry_cannot_be_rewritten(entry) -> None:
    entry.days = Decimal("30")

    with pytest.raises(LedgerImmutableError):
        entry.save()


@pytest.mark.security
def test_a_ledger_entry_cannot_be_deleted(entry) -> None:
    with pytest.raises(LedgerImmutableError):
        entry.delete()


@pytest.mark.security
def test_bulk_writes_cannot_bypass_the_guard(entry) -> None:
    """`QuerySet.update/delete` no pasan por `Model.save/delete`."""
    entries = LeaveLedgerEntry.objects.filter(pk=entry.pk)

    with pytest.raises(LedgerImmutableError):
        entries.update(days=Decimal("30"))
    with pytest.raises(LedgerImmutableError):
        entries.delete()

    entry.refresh_from_db()
    assert entry.days == Decimal("3")


def test_a_zero_day_entry_is_refused_by_the_database(working, vacation) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveLedgerEntry.objects.create(
            employee=working(), leave_type=vacation, entry_type=LedgerEntryType.ADJUSTMENT, days=0
        )


def test_a_consumption_needs_its_request(working, vacation) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveLedgerEntry.objects.create(
            employee=working(),
            leave_type=vacation,
            entry_type=LedgerEntryType.CONSUMPTION,
            days=Decimal("-1"),
        )


# --- Solicitudes ---------------------------------------------------------------- #


def _request(employee, leave_type, **overrides) -> LeaveRequest:
    values = {
        "employee": employee,
        "leave_type": leave_type,
        "start_date": dt.date(2025, 3, 3),
        "end_date": dt.date(2025, 3, 7),
        "working_days": Decimal("5"),
        "status": LeaveStatus.DRAFT,
    }
    return LeaveRequest(**{**values, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"end_date": dt.date(2025, 3, 1)}, id="dates-unordered"),
        pytest.param({"working_days": Decimal("0")}, id="no-working-days"),
        pytest.param({"status": "LOST"}, id="unknown-status"),
        pytest.param({"status": LeaveStatus.APPROVED}, id="approved-without-decision"),
        pytest.param(
            {"status": LeaveStatus.SUBMITTED, "decided_at": dt.datetime(2025, 3, 1, tzinfo=dt.UTC)},
            id="pending-with-decision",
        ),
    ],
)
def test_the_database_refuses_inconsistent_requests(working, vacation, overrides) -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        _request(working(), vacation, **overrides).save()


def test_a_cancelled_request_may_keep_its_approval(working, vacation) -> None:
    """Aprobada y luego cancelada: la constancia de la aprobación no se borra."""
    _request(
        working(),
        vacation,
        status=LeaveStatus.CANCELLED,
        decided_at=dt.datetime(2025, 3, 1, tzinfo=dt.UTC),
    ).save()


def test_an_entitlement_period_is_granted_once(working, vacation) -> None:
    employee = working()
    period = {
        "employee": employee,
        "leave_type": vacation,
        "period_start": dt.date(2025, 3, 1),
        "period_end": dt.date(2025, 3, 31),
        "granted_days": Decimal("1.25"),
        "source": "ACCRUAL",
    }
    LeaveEntitlement.objects.create(**period)

    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveEntitlement.objects.create(**period)


@pytest.mark.parametrize(
    ("entry_type", "days"),
    [
        pytest.param(LedgerEntryType.ACCRUAL, Decimal("-1"), id="negative-accrual"),
        pytest.param(LedgerEntryType.CONSUMPTION, Decimal("1"), id="positive-consumption"),
    ],
)
def test_the_sign_must_match_the_entry_type(working, vacation, entry_type, days) -> None:
    """Un consumo que suma o un devengo que resta cambiaría el saldo en silencio."""
    employee = working()
    leave_request = _request(employee, vacation)
    leave_request.save()

    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveLedgerEntry.objects.create(
            employee=employee,
            leave_type=vacation,
            entry_type=entry_type,
            days=days,
            request=leave_request,
        )


def test_a_transition_must_change_the_status(working, vacation) -> None:
    leave_request = _request(working(), vacation)
    leave_request.save()

    with pytest.raises(IntegrityError), transaction.atomic():
        LeaveRequestTransition.objects.create(
            request=leave_request, from_status=LeaveStatus.DRAFT, to_status=LeaveStatus.DRAFT
        )


def test_creation_is_recorded_as_coming_from_nowhere(working, vacation, ask) -> None:
    leave_request = ask(working(), vacation)

    creation = leave_request.transitions.get()

    assert (creation.from_status, creation.to_status) == ("", LeaveStatus.DRAFT)
