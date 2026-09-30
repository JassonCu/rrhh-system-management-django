"""Matriz de autorización de las vistas de empleados (§J.2, §J.7)."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.constants import Role
from apps.employees.models import Employee

pytestmark = pytest.mark.django_db


def as_role(client, make_user, *roles: str):
    account = make_user(f"{'-'.join(roles) or 'sinrol'}@example.com", *roles)
    client.force_login(account)
    return client


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.HR_MANAGER,), 200),
        ((Role.MANAGER,), 200),
        ((Role.EMPLOYEE,), 200),
        ((Role.AUDITOR,), 200),
        ((), 403),
    ],
    ids=["hr_admin", "hr_manager", "manager", "employee", "auditor", "sin_rol"],
)
def test_list_permissions(client, make_user, roles, expected) -> None:
    """El permiso abre la vista; el alcance decide qué filas aparecen."""
    response = as_role(client, make_user, *roles).get(reverse("employees:list"))
    assert response.status_code == expected


@pytest.mark.security
def test_list_rejects_anonymous(client) -> None:
    assert client.get(reverse("employees:list")).status_code == 302


@pytest.mark.security
def test_employee_list_shows_only_themselves(client, make_user, make_employee) -> None:
    account = make_user("solo.yo@example.com", Role.EMPLOYEE)
    own = make_employee(user=account)
    other = make_employee()
    client.force_login(account)

    response = client.get(reverse("employees:list"))

    assert own.employee_code.encode() in response.content
    assert other.employee_code.encode() not in response.content


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.HR_MANAGER,), 200),
        ((Role.MANAGER,), 403),
        ((Role.EMPLOYEE,), 403),
        ((Role.AUDITOR,), 403),  # el auditor no escribe
    ],
    ids=["hr_admin", "hr_manager", "manager", "employee", "auditor"],
)
def test_create_permissions(client, make_user, roles, expected) -> None:
    response = as_role(client, make_user, *roles).get(reverse("employees:create"))
    assert response.status_code == expected


def test_hr_admin_creates_an_employee(client, make_user) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).post(
        reverse("employees:create"),
        {
            "person-first_name": "Luis",
            "person-last_name": "García",
            "person-birth_date": "1988-11-02",
            "person-gender": "MALE",
            "person-marital_status": "SINGLE",
            "person-nationality": "GT",
            "employee-employee_code": "EMP-0500",
            "employee-hire_date": "2025-03-01",
        },
    )
    assert response.status_code == 302
    assert Employee.objects.filter(employee_code="EMP-0500").exists()


@pytest.mark.security
def test_auditor_cannot_create_by_post(client, make_user) -> None:
    response = as_role(client, make_user, Role.AUDITOR).post(
        reverse("employees:create"),
        {"employee-employee_code": "EMP-0666", "employee-hire_date": "2025-01-01"},
    )
    assert response.status_code == 403
    assert not Employee.objects.filter(employee_code="EMP-0666").exists()


# --- Pestañas de la ficha (UX-2) -------------------------------------------- #


def test_the_record_tab_is_the_default(client, make_user, employee_record) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("employees:detail", args=[employee_record.public_id])
    )

    assert response.status_code == 200
    assert response.context["tab"] == "record"
    assert b'class="tabs"' in response.content


@pytest.mark.parametrize("tab", ["record", "documents", "contracts"])
def test_each_tab_renders(client, make_user, employee_record, tab) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("employees:detail", args=[employee_record.public_id]), {"tab": tab}
    )

    assert response.status_code == 200
    assert response.context["tab"] == tab


@pytest.mark.security
def test_an_unknown_tab_falls_back_to_the_record(client, make_user, employee_record) -> None:
    """El valor viene de la URL: no puede elegir plantilla arbitraria."""
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("employees:detail", args=[employee_record.public_id]),
        {"tab": "../../etc/passwd"},
    )

    assert response.status_code == 200
    assert response.context["tab"] == "record"


@pytest.mark.security
def test_the_contracts_tab_needs_the_contract_permission(client, make_user, make_employee) -> None:
    """Ver la ficha no abre los contratos: sin permiso, la pestaña no existe.

    Se usa un `MANAGER` sobre **su propia** ficha: la ve por alcance, pero su rol
    no incluye `view_employmentcontract`.
    """
    account = make_user("jefe.sin.contratos@example.com", Role.MANAGER)
    own_record = make_employee(user=account)
    client.force_login(account)

    response = client.get(
        reverse("employees:detail", args=[own_record.public_id]), {"tab": "contracts"}
    )

    assert response.context["can_view_contracts"] is False
    assert list(response.context["contracts"]) == []
    assert b"?tab=contracts" not in response.content


@pytest.mark.security
def test_employee_form_does_not_expose_the_account_link() -> None:
    """Vincular una cuenta es una operación con servicio propio, no un desplegable."""
    from apps.employees.forms import EmployeeForm

    assert "user" not in EmployeeForm._meta.fields
    assert "employment_status" not in EmployeeForm._meta.fields
