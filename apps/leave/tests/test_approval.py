"""Quién aprueba qué, y qué ve cada quien en el calendario."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.accounts.constants import Role
from apps.departments.models import Department, DepartmentHeadship
from apps.leave import selectors, services

pytestmark = pytest.mark.django_db


@pytest.fixture
def org(company, department):
    """Dirección → Tecnología (donde trabaja el equipo) y un área hermana."""
    parent = Department.objects.create(company=company, code="DIR", name="Dirección")
    department.parent = parent
    department.save()
    sibling = Department.objects.create(company=company, code="FIN", name="Finanzas", parent=parent)
    return {"parent": parent, "team": department, "sibling": sibling}


@pytest.fixture
def head_of(make_user, make_employee):
    def _head_of(department, email):
        account = make_user(email, Role.MANAGER)
        DepartmentHeadship.objects.create(
            department=department, employee=make_employee(user=account), start_date="2024-01-01"
        )
        return account

    return _head_of


@pytest.fixture
def pending(working, vacation, ask):
    """Solicitud enviada por alguien del equipo de Tecnología."""
    leave_request = ask(working(), vacation)
    return services.submit_request(leave_request=leave_request, actor=None, request=None)


def test_the_head_of_the_team_approves(org, head_of, pending) -> None:
    assert selectors.can_approve(head_of(org["team"], "jefa.ti@example.com"), pending)


def test_approval_escalates_to_the_parent_department(org, head_of, pending) -> None:
    """Decisión de negocio: si el área no tiene jefatura, decide la de arriba."""
    assert selectors.can_approve(head_of(org["parent"], "direccion@example.com"), pending)


@pytest.mark.security
def test_a_sibling_head_has_no_say(org, head_of, pending) -> None:
    assert not selectors.can_approve(head_of(org["sibling"], "finanzas@example.com"), pending)


@pytest.mark.security
def test_a_manager_cannot_approve_their_own_request(
    org, working, vacation, ask, make_user, make_employee
) -> None:
    """RN-44: la jefatura que pide sube un nivel, no se aprueba a sí misma."""
    boss = make_user("jefe.pide@example.com", Role.MANAGER)
    employee = working(employee=make_employee(user=boss))
    DepartmentHeadship.objects.create(
        department=org["team"], employee=employee, start_date="2024-01-01"
    )
    leave_request = services.submit_request(
        leave_request=ask(employee, vacation), actor=boss, request=None
    )

    assert not selectors.can_approve(boss, leave_request)
    assert leave_request not in selectors.pending_for(boss)


def test_the_parent_head_sees_the_head_request_in_their_inbox(
    org, working, vacation, ask, make_user, make_employee, head_of
) -> None:
    boss = make_user("jefe.escala@example.com", Role.MANAGER)
    employee = working(employee=make_employee(user=boss))
    DepartmentHeadship.objects.create(
        department=org["team"], employee=employee, start_date="2024-01-01"
    )
    leave_request = services.submit_request(
        leave_request=ask(employee, vacation), actor=boss, request=None
    )

    director = head_of(org["parent"], "director.escala@example.com")

    assert leave_request in selectors.pending_for(director)


@pytest.mark.security
def test_an_employee_never_approves(make_user, pending) -> None:
    assert not selectors.can_approve(make_user("colega@example.com", Role.EMPLOYEE), pending)


def test_hr_sees_every_pending_request_but_their_own(
    make_user, make_employee, working, vacation, ask, pending
) -> None:
    hr = make_user("rrhh.bandeja@example.com", Role.HR_MANAGER)
    own = services.submit_request(
        leave_request=ask(working(employee=make_employee(user=hr)), vacation),
        actor=hr,
        request=None,
    )

    inbox = list(selectors.pending_for(hr))

    assert pending in inbox
    assert own not in inbox


# --- Calendario de equipo ------------------------------------------------------ #


def _calendar_labels(user, leave_request) -> set:
    rows = selectors.team_calendar(user, leave_request.start_date, leave_request.end_date)
    return {cell["label"] for row in rows for cell in row["days"].values()}


@pytest.mark.security
def test_sensitive_leave_is_anonymous_for_the_team(org, head_of, working, sick, ask) -> None:
    leave_request = services.submit_request(
        leave_request=ask(working(), sick), actor=None, request=None
    )

    assert _calendar_labels(head_of(org["team"], "jefe.cal@example.com"), leave_request) == {None}


def test_hr_sees_the_sensitive_type(make_user, working, sick, ask) -> None:
    leave_request = services.submit_request(
        leave_request=ask(working(), sick), actor=None, request=None
    )

    labels = _calendar_labels(make_user("rrhh.cal@example.com", Role.HR_ADMIN), leave_request)

    assert labels == {"Incapacidad"}


def test_the_owner_sees_their_own_sensitive_type(
    make_user, make_employee, working, sick, ask
) -> None:
    account = make_user("propia.cal@example.com", Role.EMPLOYEE)
    leave_request = services.submit_request(
        leave_request=ask(working(employee=make_employee(user=account)), sick),
        actor=account,
        request=None,
    )

    assert _calendar_labels(account, leave_request) == {"Incapacidad"}


def test_ordinary_leave_shows_its_type(org, head_of, working, vacation, ask) -> None:
    leave_request = services.submit_request(
        leave_request=ask(working(), vacation), actor=None, request=None
    )

    labels = _calendar_labels(head_of(org["team"], "jefe.vac@example.com"), leave_request)

    assert labels == {"Vacaciones"}


def test_drafts_do_not_appear_in_the_calendar(make_user, working, vacation, ask) -> None:
    leave_request = ask(working(), vacation)

    rows = selectors.team_calendar(
        make_user("rrhh.borrador@example.com", Role.HR_ADMIN),
        leave_request.start_date,
        leave_request.end_date,
    )

    assert rows == []


def test_pending_days_count_other_submitted_requests(working, vacation, ask, next_monday) -> None:
    employee = working()
    first = services.submit_request(leave_request=ask(employee, vacation), actor=None, request=None)
    second = ask(employee, vacation, start=next_monday + dt.timedelta(days=7), days=2)

    assert selectors.pending_days_for(employee, vacation, exclude=second) == first.working_days
    assert selectors.pending_days_for(employee, vacation, exclude=first) == 0
