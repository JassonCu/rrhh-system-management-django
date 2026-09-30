"""Alcance y matriz rol × vista de asistencia (§J.2, §J.7)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse

from apps.accounts.constants import Role
from apps.attendance import selectors, services
from apps.attendance.constants import IncidentStatus, IncidentType
from apps.attendance.models import AttendanceIncident
from apps.attendance.tests.conftest import at
from apps.departments.models import DepartmentHeadship

pytestmark = pytest.mark.django_db


def sign_in(client, make_user, role: str, email: str):
    account = make_user(email, role)
    client.force_login(account)
    return account


@pytest.fixture
def worker(working, make_employee, make_user):
    """Un EMPLOYEE contratado, con jornada y cuenta propia."""
    account = make_user("marcador@example.com", Role.EMPLOYEE)
    return account, working(employee=make_employee(user=account))


# --- Marcaje en autoservicio --------------------------------------------------- #


@pytest.mark.security
def test_punch_requires_post(client, worker) -> None:
    """Un cambio de estado por GET sería vulnerable a CSRF por enlace."""
    account, _employee = worker
    client.force_login(account)

    assert client.get(reverse("attendance:punch")).status_code == 405


def test_an_employee_clocks_in_and_out(client, worker) -> None:
    account, employee = worker
    client.force_login(account)

    client.post(reverse("attendance:punch"))
    assert selectors.open_entry_for(employee) is not None

    client.post(reverse("attendance:punch"))
    assert selectors.open_entry_for(employee) is None
    assert employee.attendance_entries.count() == 1


@pytest.mark.security
def test_punching_marks_only_your_own_attendance(client, worker, working) -> None:
    """La ficha sale de la sesión: no hay parámetro que apunte a otra persona."""
    account, employee = worker
    other = working()
    client.force_login(account)

    client.post(reverse("attendance:punch"), {"employee": other.pk})

    assert employee.attendance_entries.exists()
    assert not other.attendance_entries.exists()


def test_an_account_without_a_record_is_told_so(client, make_user) -> None:
    sign_in(client, make_user, Role.EMPLOYEE, "sin.ficha.asistencia@example.com")

    response = client.post(reverse("attendance:punch"), follow=True)

    assert response.status_code == 200
    assert [str(message) for message in response.context["messages"]]


# --- Alcance ------------------------------------------------------------------- #


@pytest.mark.security
def test_an_employee_only_sees_their_own_entries(worker, working, monday) -> None:
    account, employee = worker
    other = working()
    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8))
    services.check_in(employee=other, actor=None, request=None, at=at(monday, 8))

    visible = selectors.entries_visible_for(account)

    assert visible.filter(employee=employee).exists()
    assert not visible.filter(employee=other).exists()


@pytest.mark.security
def test_a_manager_sees_the_attendance_of_their_team(
    make_user, make_employee, working, department, monday
) -> None:
    account = make_user("jefe.asistencia@example.com", Role.MANAGER)
    DepartmentHeadship.objects.create(
        department=department, employee=make_employee(user=account), start_date="2024-01-01"
    )
    subordinate = working()  # su puesto pertenece a `department`
    services.check_in(employee=subordinate, actor=None, request=None, at=at(monday, 8))

    assert selectors.entries_visible_for(account).filter(employee=subordinate).exists()


@pytest.mark.security
def test_hr_sees_everyone(make_user, working, monday) -> None:
    employee = working()
    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8))
    hr = make_user("rrhh.asistencia@example.com", Role.HR_ADMIN)

    assert selectors.entries_visible_for(hr).filter(employee=employee).exists()


@pytest.mark.security
def test_someone_elses_entry_is_404(client, worker, working, monday) -> None:
    """IDOR: la clave de un marcaje ajeno no abre nada."""
    account, _employee = worker
    other = working()
    services.check_in(employee=other, actor=None, request=None, at=at(monday, 8))
    entry = other.attendance_entries.get()
    client.force_login(account)

    assert client.get(reverse("attendance:entry_adjust", args=[entry.pk])).status_code == 403


# --- Matriz rol × vista ---------------------------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("view", "role", "expected"),
    [
        ("attendance:my_attendance", Role.EMPLOYEE, 200),
        ("attendance:my_attendance", Role.AUDITOR, 200),
        ("attendance:team", Role.MANAGER, 200),
        ("attendance:team", Role.EMPLOYEE, 200),  # su alcance es su propia ficha
        ("attendance:incident_list", Role.HR_ADMIN, 200),
        ("attendance:incident_list", Role.EMPLOYEE, 200),
        ("attendance:schedule_list", Role.HR_ADMIN, 200),
        ("attendance:schedule_list", Role.EMPLOYEE, 403),
        ("attendance:schedule_create", Role.HR_ADMIN, 200),
        ("attendance:schedule_create", Role.HR_MANAGER, 403),
        ("attendance:schedule_create", Role.AUDITOR, 403),
    ],
)
def test_view_permissions(client, make_user, view, role, expected) -> None:
    sign_in(client, make_user, role, f"{view}.{role}@example.com".replace(":", "."))

    assert client.get(reverse(view)).status_code == expected


@pytest.mark.security
def test_an_employee_cannot_adjust_entries(client, worker, monday) -> None:
    account, employee = worker
    services.check_in(employee=employee, actor=None, request=None, at=at(monday, 8))
    services.check_out(employee=employee, actor=None, request=None, at=at(monday, 17))
    entry = employee.attendance_entries.get()
    client.force_login(account)

    assert client.get(reverse("attendance:entry_adjust", args=[entry.pk])).status_code == 403


@pytest.mark.security
def test_an_employee_cannot_resolve_incidents(client, worker, monday) -> None:
    account, employee = worker
    incident = AttendanceIncident.objects.create(
        employee=employee,
        work_date=monday,
        incident_type=IncidentType.LATE,
        minutes=20,
        status=IncidentStatus.OPEN,
    )
    client.force_login(account)

    assert client.get(reverse("attendance:incident_resolve", args=[incident.pk])).status_code == 403


@pytest.mark.security
def test_an_auditor_cannot_resolve_by_post(client, make_user, working, monday) -> None:
    employee = working()
    incident = AttendanceIncident.objects.create(
        employee=employee, work_date=monday, incident_type=IncidentType.LATE, minutes=20
    )
    sign_in(client, make_user, Role.AUDITOR, "auditor.asistencia@example.com")

    response = client.post(
        reverse("attendance:incident_resolve", args=[incident.pk]),
        {"status": IncidentStatus.JUSTIFIED, "justification": "No debería poder"},
    )

    assert response.status_code == 403
    incident.refresh_from_db()
    assert incident.is_open


def test_hr_resolves_an_incident_through_the_web(client, make_user, working, monday) -> None:
    employee = working()
    incident = AttendanceIncident.objects.create(
        employee=employee, work_date=monday, incident_type=IncidentType.OVERTIME, minutes=90
    )
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.resuelve@example.com")

    response = client.post(
        reverse("attendance:incident_resolve", args=[incident.pk]),
        {"status": IncidentStatus.JUSTIFIED, "justification": "Cierre de mes"},
    )

    assert response.status_code == 302
    incident.refresh_from_db()
    assert incident.status == IncidentStatus.JUSTIFIED


def test_hr_creates_a_schedule_through_the_web(client, make_user) -> None:
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.jornada@example.com")

    response = client.post(
        reverse("attendance:schedule_create"),
        {
            "code": "TUR",
            "name": "Turno A",
            "weekly_hours": "44",
            "grace_minutes": "5",
            "is_active": "on",
            "weekdays": ["0", "1", "2", "3", "4", "5"],
            "start_time": "07:00",
            "end_time": "15:00",
            "break_minutes": "30",
        },
    )

    assert response.status_code == 302
    from apps.attendance.models import WorkSchedule

    schedule = WorkSchedule.objects.get(code="TUR")
    assert schedule.days.count() == 6
    assert schedule.grace_minutes == 5


def test_hr_assigns_a_schedule_to_a_contract(client, make_user, hire, schedule) -> None:
    contract = hire(start=dt.date(2025, 1, 1))
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.asigna@example.com")

    response = client.post(
        reverse("attendance:schedule_assign", args=[contract.public_id]),
        {"work_schedule": schedule.pk, "start_date": "2025-01-01"},
    )

    assert response.status_code == 302
    assert contract.schedule_assignments.filter(work_schedule=schedule).exists()
