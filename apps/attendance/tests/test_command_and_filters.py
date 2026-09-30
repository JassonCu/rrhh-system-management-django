"""Cierre diario y formato de horas."""

from __future__ import annotations

import datetime as dt
from io import StringIO

import pytest
from django.core.management import call_command

from apps.attendance.constants import IncidentType
from apps.attendance.templatetags.attendance_extras import as_hours
from apps.attendance.tests.conftest import EXPECTED_MINUTES

pytestmark = pytest.mark.django_db


def test_the_daily_close_opens_absences(working, monday) -> None:
    employee = working()
    out = StringIO()

    call_command("close_attendance_day", "--date", monday.isoformat(), stdout=out)

    incident = employee.attendance_incidents.get(incident_type=IncidentType.ABSENCE)
    assert incident.minutes == EXPECTED_MINUTES
    assert "cerrado" in out.getvalue()


def test_the_daily_close_is_idempotent(working, monday) -> None:
    working()
    for _ in range(3):
        call_command("close_attendance_day", "--date", monday.isoformat(), stdout=StringIO())

    from apps.attendance.models import AttendanceIncident

    assert AttendanceIncident.objects.count() == 1


def test_the_daily_close_ignores_people_hired_later(working, monday) -> None:
    """Nadie falta a un día anterior a su contratación."""
    working(start=monday + dt.timedelta(days=10))

    call_command("close_attendance_day", "--date", monday.isoformat(), stdout=StringIO())

    from apps.attendance.models import AttendanceIncident

    assert not AttendanceIncident.objects.exists()


def test_without_a_date_it_closes_yesterday(working) -> None:
    working()
    out = StringIO()

    call_command("close_attendance_day", stdout=out)

    assert "cerrado" in out.getvalue()


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(0, "—"), (None, "—"), (45, "45 min"), (480, "8 h"), (252, "4 h 12 min")],
)
def test_minutes_are_shown_as_hours(minutes, expected) -> None:
    assert as_hours(minutes) == expected
