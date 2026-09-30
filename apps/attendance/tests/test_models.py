"""Restricciones de asistencia garantizadas por la base."""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.attendance.constants import IncidentStatus, IncidentType, Weekday
from apps.attendance.models import (
    AttendanceEntry,
    AttendanceIncident,
    ScheduleAssignment,
    WorkSchedule,
    WorkScheduleDay,
)
from apps.attendance.tests.conftest import at

pytestmark = pytest.mark.django_db

MONDAY = dt.date(2025, 3, 3)


# --- Jornada ----------------------------------------------------------------- #


def test_weekly_hours_must_be_plausible() -> None:
    with pytest.raises(IntegrityError):
        WorkSchedule.objects.create(code="X", name="Imposible", weekly_hours=200)


def test_grace_has_a_ceiling() -> None:
    """Una tolerancia enorme vacía de sentido la jornada."""
    with pytest.raises(IntegrityError):
        WorkSchedule.objects.create(code="Y", name="Laxa", weekly_hours=40, grace_minutes=500)


def test_a_schedule_cannot_repeat_a_weekday(schedule) -> None:
    with pytest.raises(IntegrityError):
        WorkScheduleDay.objects.create(
            work_schedule=schedule,
            weekday=Weekday.MONDAY,
            start_time=dt.time(9, 0),
            end_time=dt.time(18, 0),
        )


def test_a_day_ends_after_it_starts(schedule) -> None:
    with pytest.raises(IntegrityError):
        WorkScheduleDay.objects.create(
            work_schedule=schedule,
            weekday=Weekday.SATURDAY,
            start_time=dt.time(18, 0),
            end_time=dt.time(9, 0),
        )


def test_expected_minutes_discounts_the_break(schedule) -> None:
    monday = schedule.days.get(weekday=Weekday.MONDAY)
    assert monday.expected_minutes == 8 * 60


def test_a_schedule_in_use_cannot_be_deleted(working, schedule) -> None:
    working()
    with pytest.raises(ProtectedError):
        schedule.delete()


# --- Asignación de jornada ---------------------------------------------------- #


def test_only_one_open_schedule_per_contract(hire, schedule) -> None:
    contract = hire()
    ScheduleAssignment.objects.create(
        contract=contract, work_schedule=schedule, start_date=dt.date(2025, 1, 1)
    )
    with pytest.raises(IntegrityError):
        ScheduleAssignment.objects.create(
            contract=contract, work_schedule=schedule, start_date=dt.date(2025, 6, 1)
        )


# --- Marcajes ----------------------------------------------------------------- #


def test_only_one_open_entry_per_person(make_employee) -> None:
    """Marcar dos entradas seguidas es el error más común: lo impide la base."""
    employee = make_employee()
    AttendanceEntry.objects.create(employee=employee, work_date=MONDAY, check_in_at=at(MONDAY, 8))
    with pytest.raises(IntegrityError):
        AttendanceEntry.objects.create(
            employee=employee, work_date=MONDAY, check_in_at=at(MONDAY, 13)
        )


def test_check_out_must_come_after_check_in(make_employee) -> None:
    with pytest.raises(IntegrityError):
        AttendanceEntry.objects.create(
            employee=make_employee(),
            work_date=MONDAY,
            check_in_at=at(MONDAY, 17),
            check_out_at=at(MONDAY, 8),
        )


def test_two_segments_cannot_share_the_check_in(make_employee) -> None:
    employee = make_employee()
    AttendanceEntry.objects.create(
        employee=employee,
        work_date=MONDAY,
        check_in_at=at(MONDAY, 8),
        check_out_at=at(MONDAY, 12),
    )
    with pytest.raises(IntegrityError):
        AttendanceEntry.objects.create(
            employee=employee,
            work_date=MONDAY,
            check_in_at=at(MONDAY, 8),
            check_out_at=at(MONDAY, 13),
        )


def test_minutes_of_an_open_entry_are_zero(make_employee) -> None:
    entry = AttendanceEntry.objects.create(
        employee=make_employee(), work_date=MONDAY, check_in_at=at(MONDAY, 8)
    )
    assert entry.is_open
    assert entry.minutes == 0


# --- Incidencias --------------------------------------------------------------- #


def test_one_incident_per_type_and_day(make_employee) -> None:
    employee = make_employee()
    AttendanceIncident.objects.create(
        employee=employee, work_date=MONDAY, incident_type=IncidentType.LATE, minutes=15
    )
    with pytest.raises(IntegrityError):
        AttendanceIncident.objects.create(
            employee=employee, work_date=MONDAY, incident_type=IncidentType.LATE, minutes=20
        )


def test_a_resolved_incident_needs_the_date_it_was_resolved(make_employee) -> None:
    """Resolver exige constancia de cuándo (RN-53)."""
    with pytest.raises(IntegrityError):
        AttendanceIncident.objects.create(
            employee=make_employee(),
            work_date=MONDAY,
            incident_type=IncidentType.OVERTIME,
            minutes=30,
            status=IncidentStatus.JUSTIFIED,
        )
