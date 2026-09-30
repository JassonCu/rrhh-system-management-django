"""Inicio por rol: cada quien entra a lo suyo, y solo a lo suyo."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.constants import Role
from apps.contracts import services as contract_services
from apps.departments.models import DepartmentHeadship

pytestmark = pytest.mark.django_db

HOME = reverse("dashboard:home")


def sign_in(client, make_user, role: str, email: str):
    account = make_user(email, role)
    client.force_login(account)
    return account


# --- Panel de RRHH ----------------------------------------------------------- #


def test_hr_sees_pending_work(client, make_user, draft, hire) -> None:
    pending = draft()
    hire()
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.inicio@example.com")

    response = client.get(HOME)

    assert response.status_code == 200
    assert response.context["shows_hr_panel"] is True
    assert response.context["hr"]["draft_contracts"] == 1
    assert response.context["hr"]["active_employees"] == 2
    assert pending in list(response.context["hr"]["drafts"])


def test_hr_sees_contracts_ending_soon(client, make_user, hire) -> None:
    from django.utils import timezone

    soon = timezone.localdate() + dt.timedelta(days=10)
    contract = hire(contract_type="FIXED_TERM", end_date=soon, start=soon - dt.timedelta(days=200))
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.vencimientos@example.com")

    response = client.get(HOME)

    assert list(response.context["hr"]["expiring"]) == [contract]


def test_hr_sees_active_employees_without_a_contract(
    client,
    make_user,
    make_employee,
) -> None:
    """Es el hueco que produce fichas sin contratar: el inicio lo hace visible."""
    orphan = make_employee()
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.sin.contrato@example.com")

    response = client.get(HOME)

    assert orphan in list(response.context["hr"]["pending_employees"])


@pytest.mark.security
def test_the_home_never_shows_salary_amounts(client, make_user, hire) -> None:
    """El inicio se queda abierto en la pantalla: no lleva importes (§7.1)."""
    hire(amount=Decimal("7000"))
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.sin.importes@example.com")

    content = client.get(HOME).content

    for form in (b"7,000.00", b"7000.00", b"7000", b"7,000"):
        assert form not in content


# --- Panel de jefatura -------------------------------------------------------- #


@pytest.mark.security
def test_a_manager_sees_only_their_team(
    client,
    make_user,
    make_employee,
    company,
    department,
    position,
    hire,
) -> None:
    account = make_user("jefe.inicio@example.com", Role.MANAGER)
    DepartmentHeadship.objects.create(
        department=department, employee=make_employee(user=account), start_date="2024-01-01"
    )
    subordinate = hire()  # usa `position`, que pertenece a `department`
    outsider = make_employee()
    client.force_login(account)

    response = client.get(HOME)

    assert response.context["shows_team_panel"] is True
    assert response.context["shows_hr_panel"] is False
    team = list(response.context["team"])
    assert subordinate.employee in team
    assert outsider not in team


# --- Autoservicio -------------------------------------------------------------- #


def test_an_employee_sees_their_own_record_and_contract(
    client,
    make_user,
    make_employee,
    hire,
) -> None:
    account = make_user("empleado.inicio@example.com", Role.EMPLOYEE)
    record = make_employee(user=account)
    contract = hire(employee=record)
    client.force_login(account)

    response = client.get(HOME)

    assert response.context["shows_hr_panel"] is False
    assert response.context["own_employee"] == record
    assert response.context["own_contract"] == contract


def test_an_account_without_a_record_still_gets_a_home(client, make_user) -> None:
    sign_in(client, make_user, Role.EMPLOYEE, "sin.ficha@example.com")

    response = client.get(HOME)

    assert response.status_code == 200
    assert response.context["own_employee"] is None
    assert response.context["own_contract"] is None


@pytest.mark.security
def test_the_home_requires_a_session(client) -> None:
    response = client.get(HOME)

    assert response.status_code == 302
    assert reverse("account_login") in response.url


@pytest.mark.security
def test_a_suspended_contract_still_counts_as_the_employees_own(
    client,
    make_user,
    make_employee,
    hire,
) -> None:
    """Suspendido sigue siendo un vínculo vivo (RN-13): la persona lo ve."""
    account = make_user("suspendido.inicio@example.com", Role.EMPLOYEE)
    contract = hire(employee=make_employee(user=account))
    contract_services.suspend_contract(contract=contract, actor=None, request=None)
    client.force_login(account)

    response = client.get(HOME)

    assert response.context["own_contract"] == contract
