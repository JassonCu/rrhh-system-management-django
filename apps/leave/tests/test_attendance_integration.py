"""Una ausencia aprobada no es una falta de asistencia."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.accounts.constants import Role
from apps.attendance import services as attendance
from apps.attendance.constants import IncidentStatus, IncidentType
from apps.leave import services

pytestmark = pytest.mark.django_db


@pytest.fixture
def hr(make_user):
    return make_user("rrhh.integracion@example.com", Role.HR_ADMIN)


def test_closing_a_day_on_approved_leave_opens_no_absence(
    working, vacation, ask, grant, hr, next_monday
) -> None:
    employee = working()
    grant(employee, vacation)
    leave_request = services.submit_request(
        leave_request=ask(employee, vacation), actor=None, request=None
    )
    services.approve_request(leave_request=leave_request, actor=hr, request=None)

    attendance.close_day(employee=employee, work_date=next_monday)

    assert not employee.attendance_incidents.exists()


def test_a_pending_request_does_not_excuse_the_day(working, vacation, ask, next_monday) -> None:
    """Hasta que alguien aprueba, la falta es una falta."""
    employee = working()
    services.submit_request(leave_request=ask(employee, vacation), actor=None, request=None)

    attendance.close_day(employee=employee, work_date=next_monday)

    assert employee.attendance_incidents.get().incident_type == IncidentType.ABSENCE


def test_approving_justifies_absences_already_opened(working, sick, ask, hr, next_monday) -> None:
    """Incapacidad pedida el mismo día: el cierre corrió antes de la aprobación."""
    employee = working()
    leave_request = services.submit_request(
        leave_request=ask(employee, sick, days=1, reason="Diagnóstico confidencial"),
        actor=None,
        request=None,
    )
    attendance.close_day(employee=employee, work_date=next_monday)
    outside = next_monday + dt.timedelta(days=1)
    attendance.close_day(employee=employee, work_date=outside)

    services.approve_request(leave_request=leave_request, actor=hr, request=None)

    covered = employee.attendance_incidents.get(work_date=next_monday)
    assert covered.status == IncidentStatus.JUSTIFIED
    assert covered.resolved_by == hr
    # Las fechas fuera de la ausencia siguen abiertas.
    assert employee.attendance_incidents.get(work_date=outside).status == IncidentStatus.OPEN


@pytest.mark.security
def test_the_automatic_justification_reveals_nothing_sensitive(
    working, sick, ask, hr, next_monday
) -> None:
    """La jefatura ve las incidencias: ni el tipo ni el motivo pueden aparecer."""
    employee = working()
    leave_request = services.submit_request(
        leave_request=ask(employee, sick, days=1, reason="Diagnóstico confidencial"),
        actor=None,
        request=None,
    )
    attendance.close_day(employee=employee, work_date=next_monday)

    services.approve_request(leave_request=leave_request, actor=hr, request=None)

    justification = employee.attendance_incidents.get().justification
    assert "Incapacidad" not in justification
    assert "Diagnóstico" not in justification
    assert str(leave_request.public_id) in justification
