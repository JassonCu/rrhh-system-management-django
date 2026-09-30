"""Fixtures de ausencias.

Se reutilizan las de asistencia: los días hábiles salen de la jornada asignada,
así que el escenario mínimo ya incluye contrato y jornada de lunes a viernes.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.attendance.tests import conftest as attendance_fixtures
from apps.leave import services
from apps.leave.models import LeaveType

department = attendance_fixtures.department
draft = attendance_fixtures.draft
grade = attendance_fixtures.grade
hire = attendance_fixtures.hire
make_employee = attendance_fixtures.make_employee
make_person = attendance_fixtures.make_person
other_position = attendance_fixtures.other_position
position = attendance_fixtures.position
schedule = attendance_fixtures.schedule
working = attendance_fixtures.working


@pytest.fixture
def vacation(db) -> LeaveType:
    """Vacaciones: 15 días al año, con aprobación y sin saldo negativo."""
    return LeaveType.objects.create(
        code="VAC", name="Vacaciones", default_annual_days=Decimal("15"), requires_approval=True
    )


@pytest.fixture
def sick(db) -> LeaveType:
    """Incapacidad: sensible, sin derecho anual y admite saldo negativo."""
    return LeaveType.objects.create(
        code="ENF",
        name="Incapacidad",
        default_annual_days=Decimal("0"),
        allows_negative_balance=True,
        is_sensitive=True,
    )


@pytest.fixture
def errand(db) -> LeaveType:
    """Permiso personal que no requiere aprobación."""
    return LeaveType.objects.create(
        code="PER",
        name="Permiso personal",
        default_annual_days=Decimal("0"),
        requires_approval=False,
        allows_negative_balance=True,
    )


@pytest.fixture
def next_monday() -> dt.date:
    """Un lunes al menos dos semanas en el futuro: cumple cualquier preaviso."""
    today = timezone.localdate()
    return today + dt.timedelta(days=14 + (7 - today.weekday()) % 7)


@pytest.fixture
def grant():
    """Deja saldo disponible mediante un ajuste, como lo haría RRHH."""

    def _grant(employee, leave_type, days: str = "10") -> None:
        services.adjust_balance(
            employee=employee,
            leave_type=leave_type,
            days=Decimal(days),
            note="Saldo inicial de prueba",
            actor=None,
            request=None,
        )

    return _grant


@pytest.fixture
def ask(next_monday):
    """Crea una solicitud en borrador de lunes a viernes (5 días hábiles)."""

    def _ask(employee, leave_type, *, start=None, days: int = 5, reason: str = ""):
        start = start or next_monday
        return services.create_request(
            employee=employee,
            leave_type=leave_type,
            start_date=start,
            end_date=start + dt.timedelta(days=days - 1),
            reason=reason,
            actor=employee.user,
            request=None,
        )

    return _ask
