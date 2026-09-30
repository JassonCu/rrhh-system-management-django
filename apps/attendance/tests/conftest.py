"""Fixtures de asistencia.

Se reutilizan las de `contracts` (que a su vez usan las de `employees`): marcar
exige contrato vivo, así que el escenario mínimo ya incluye una contratación.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from apps.attendance import services
from apps.attendance.constants import Weekday
from apps.attendance.models import WorkSchedule, WorkScheduleDay
from apps.contracts.tests import conftest as contract_fixtures

department = contract_fixtures.department
draft = contract_fixtures.draft
grade = contract_fixtures.grade
hire = contract_fixtures.hire
make_employee = contract_fixtures.make_employee
make_person = contract_fixtures.make_person
other_position = contract_fixtures.other_position
position = contract_fixtures.position

#: Jornada de referencia: lunes a viernes, de 08:00 a 17:00 con una hora de almuerzo.
WORKDAY_START = dt.time(8, 0)
WORKDAY_END = dt.time(17, 0)
BREAK_MINUTES = 60
EXPECTED_MINUTES = 8 * 60  # 9 horas menos el almuerzo


@pytest.fixture
def schedule(db) -> WorkSchedule:
    work_schedule = WorkSchedule.objects.create(
        code="OFI", name="Oficina", weekly_hours=40, grace_minutes=10
    )
    for weekday in (
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
        Weekday.THURSDAY,
        Weekday.FRIDAY,
    ):
        WorkScheduleDay.objects.create(
            work_schedule=work_schedule,
            weekday=weekday,
            start_time=WORKDAY_START,
            end_time=WORKDAY_END,
            break_minutes=BREAK_MINUTES,
        )
    return work_schedule


@pytest.fixture
def working(hire, schedule):
    """Alguien contratado y con jornada asignada. Devuelve su ficha."""

    def _working(*, employee=None, start=dt.date(2025, 1, 1)):
        contract = hire(employee=employee, start=start)
        services.assign_schedule(
            contract=contract,
            work_schedule=schedule,
            start_date=start,
            actor=None,
            request=None,
        )
        return contract.employee

    return _working


@pytest.fixture
def monday() -> dt.date:
    """Un lunes cualquiera dentro de la vigencia del contrato de prueba."""
    return dt.date(2025, 3, 3)


def at(day: dt.date, hour: int, minute: int = 0) -> dt.datetime:
    """Momento local del día indicado, con zona horaria."""
    return timezone.make_aware(
        dt.datetime.combine(day, dt.time(hour, minute)), timezone.get_current_timezone()
    )
