"""Alcance, confidencialidad salarial, IDOR y matriz de vistas de contratos."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.constants import Role
from apps.contracts import selectors

pytestmark = pytest.mark.django_db

#: El importe se muestra localizado (§O.2.2). Se comprueban todas las formas para
#: que una aserción negativa no pase por el motivo equivocado.
AMOUNT_FORMS = (b"7,000.00", b"7000.00", b"7000", b"7,000")


def as_role(client, make_user, *roles: str, email: str | None = None):
    account = make_user(email or f"{'-'.join(roles) or 'sinrol'}@example.com", *roles)
    client.force_login(account)
    return client, account


@pytest.fixture
def own_contract(make_user, make_employee, hire):
    """Un EMPLOYEE con su propio contrato activo."""
    account = make_user("titular@example.com", Role.EMPLOYEE)
    return account, hire(employee=make_employee(user=account))


# --- Alcance ---------------------------------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize("role", [Role.HR_ADMIN, Role.HR_MANAGER, Role.AUDITOR])
def test_organization_wide_roles_see_every_contract(make_user, hire, role) -> None:
    contract = hire()
    viewer = make_user(f"{role.lower()}@example.com", role)
    assert contract in selectors.contracts_visible_for(viewer)


@pytest.mark.security
def test_an_employee_sees_only_their_own_contracts(own_contract, hire) -> None:
    account, own = own_contract
    other = hire()
    visible = selectors.contracts_visible_for(account)
    assert own in visible
    assert other not in visible


@pytest.mark.security
def test_a_manager_sees_no_contracts_of_others(make_user, hire) -> None:
    manager = make_user("jefe.contratos@example.com", Role.MANAGER)
    assert not selectors.contracts_visible_for(manager).filter(pk=hire().pk).exists()


# --- Confidencialidad salarial --------------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.HR_ADMIN, True),
        (Role.AUDITOR, True),
        (Role.HR_MANAGER, False),  # ve contratos, NO importes
        (Role.MANAGER, False),
    ],
)
def test_salary_visibility_by_role(make_user, hire, role, expected) -> None:
    viewer = make_user(f"sal.{role.lower()}@example.com", role)
    assert selectors.can_view_salary(viewer, hire()) is expected


@pytest.mark.security
def test_an_employee_sees_their_own_salary(own_contract) -> None:
    account, own = own_contract
    assert selectors.can_view_salary(account, own) is True


@pytest.mark.security
def test_salary_scope_survives_a_misgranted_permission(make_user, hire) -> None:
    """Defensa en profundidad: conceder `view_salary` por error a HR_MANAGER no
    le abre los importes ajenos, porque el alcance salarial es un segundo filtro."""
    hr_manager = make_user("hrm.mal@example.com", Role.HR_MANAGER)
    hr_manager.user_permissions.add(Permission.objects.get(codename="view_salary"))
    hr_manager = type(hr_manager).objects.get(pk=hr_manager.pk)  # limpia la caché de permisos

    assert hr_manager.has_perm("contracts.view_salary")
    assert selectors.can_view_salary(hr_manager, hire()) is False


@pytest.mark.security
def test_hr_manager_opens_the_contract_but_not_the_amounts(client, make_user, hire) -> None:
    contract = hire(amount=Decimal("7000"))
    authenticated, _account = as_role(client, make_user, Role.HR_MANAGER)

    response = authenticated.get(reverse("contracts:detail", args=[contract.public_id]))

    assert response.status_code == 200
    for form in AMOUNT_FORMS:
        assert form not in response.content, f"se filtró el salario como {form!r}"


@pytest.mark.security
def test_hr_admin_sees_the_amounts(client, make_user, hire) -> None:
    contract = hire(amount=Decimal("7000"))
    authenticated, _account = as_role(client, make_user, Role.HR_ADMIN)
    response = authenticated.get(reverse("contracts:detail", args=[contract.public_id]))
    assert b"7,000.00" in response.content


# --- IDOR ------------------------------------------------------------------ #


@pytest.mark.security
def test_someone_elses_contract_uuid_is_404(client, own_contract, hire) -> None:
    account, own = own_contract
    other = hire()
    client.force_login(account)

    assert client.get(reverse("contracts:detail", args=[own.public_id])).status_code == 200
    assert client.get(reverse("contracts:detail", args=[other.public_id])).status_code == 404


@pytest.mark.security
def test_an_assignment_key_from_another_contract_is_404(client, make_user, hire) -> None:
    """La asignación se busca DENTRO del contrato de la URL: mezclar claves no sirve."""
    target, victim = hire(), hire()
    authenticated, _account = as_role(client, make_user, Role.HR_ADMIN)
    foreign_pk = victim.assignments.get().pk

    response = authenticated.post(
        reverse("contracts:assignment_end", args=[target.public_id, foreign_pk]),
        {"end_date": "2025-06-30"},
    )

    assert response.status_code == 404
    assert victim.assignments.get().end_date is None


# --- Matriz de vistas ------------------------------------------------------ #


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.HR_MANAGER,), 200),
        ((Role.AUDITOR,), 200),
        ((Role.EMPLOYEE,), 200),  # ve la lista, filtrada a lo suyo
        ((Role.MANAGER,), 403),
    ],
    ids=["hr_admin", "hr_manager", "auditor", "employee", "manager"],
)
def test_list_permissions(client, make_user, roles, expected) -> None:
    authenticated, _account = as_role(client, make_user, *roles)
    assert authenticated.get(reverse("contracts:list")).status_code == expected


@pytest.mark.security
@pytest.mark.parametrize(
    ("view", "roles", "expected"),
    [
        ("contracts:salary_set", (Role.HR_ADMIN,), 200),
        ("contracts:salary_set", (Role.HR_MANAGER,), 403),
        ("contracts:salary_set", (Role.AUDITOR,), 403),
        ("contracts:assignment_add", (Role.HR_MANAGER,), 200),
        ("contracts:assignment_add", (Role.MANAGER,), 403),
        ("contracts:terminate", (Role.HR_ADMIN,), 200),
        ("contracts:terminate", (Role.HR_MANAGER,), 403),
    ],
)
def test_write_views_permissions(client, make_user, hire, view, roles, expected) -> None:
    contract = hire()
    authenticated, _account = as_role(client, make_user, *roles)
    assert authenticated.get(reverse(view, args=[contract.public_id])).status_code == expected


@pytest.mark.security
@pytest.mark.parametrize("view", ["contracts:activate", "contracts:suspend", "contracts:resume"])
def test_state_changes_by_get_only_confirm(client, make_user, hire, view) -> None:
    """El GET muestra la confirmación; el estado solo cambia con POST y CSRF."""
    contract = hire()
    authenticated, _account = as_role(client, make_user, Role.HR_ADMIN)

    response = authenticated.get(reverse(view, args=[contract.public_id]))

    assert response.status_code == 200
    assert b"csrfmiddlewaretoken" in response.content
    contract.refresh_from_db()
    assert contract.status == "ACTIVE"


@pytest.mark.security
def test_an_auditor_cannot_terminate_by_post(client, make_user, hire) -> None:
    contract = hire()
    authenticated, _account = as_role(client, make_user, Role.AUDITOR)
    response = authenticated.post(
        reverse("contracts:terminate", args=[contract.public_id]),
        {"termination_date": "2025-06-30", "termination_reason": "RESIGNATION"},
    )
    assert response.status_code == 403
    contract.refresh_from_db()
    assert contract.status == "ACTIVE"


# --- Integración: contratación completa por HTTP --------------------------- #


@pytest.mark.integration
def test_hr_admin_hires_someone_through_the_web(
    client, make_user, make_employee, company, position
) -> None:
    """Borrador → salario → puesto → activación, todo por las vistas reales."""
    employee = make_employee()
    authenticated, _account = as_role(client, make_user, Role.HR_ADMIN)

    response = authenticated.post(
        reverse("contracts:create", args=[employee.public_id]),
        {"company": company.pk, "contract_type": "INDEFINITE", "start_date": "2025-01-01"},
    )
    assert response.status_code == 302
    contract = employee.contracts.get()
    detail = reverse("contracts:detail", args=[contract.public_id])

    authenticated.post(
        reverse("contracts:salary_set", args=[contract.public_id]),
        {
            "amount": "7000.00",
            "currency": "GTQ",
            "pay_frequency": "MONTHLY",
            "effective_from": "2025-01-01",
            "change_reason": "INITIAL",
        },
    )
    authenticated.post(
        reverse("contracts:assignment_add", args=[contract.public_id]),
        {
            "position": position.pk,
            "start_date": "2025-01-01",
            "fte": "1.00",
            "is_primary": "on",
            "assignment_reason": "INITIAL",
        },
    )
    response = authenticated.post(reverse("contracts:activate", args=[contract.public_id]))

    assert response.url == detail
    contract.refresh_from_db()
    employee.refresh_from_db()
    assert contract.status == "ACTIVE"
    assert employee.employment_status == "ACTIVE"
    assert selectors.find_status_inconsistencies() == []


@pytest.mark.integration
def test_a_rejected_transition_shows_a_message_instead_of_failing(client, make_user, draft) -> None:
    """Activar un borrador incompleto informa al usuario; no produce un 500."""
    contract = draft()
    authenticated, _account = as_role(client, make_user, Role.HR_ADMIN)

    response = authenticated.post(
        reverse("contracts:activate", args=[contract.public_id]), follow=True
    )

    assert response.status_code == 200
    contract.refresh_from_db()
    assert contract.status == "DRAFT"


@pytest.mark.security
def test_create_refuses_an_employee_out_of_scope(client, make_user, make_employee, company) -> None:
    """El titular sale de la URL validada por el selector: un EMPLOYEE con permiso
    de alta (si lo tuviera) no podría crear contratos a otra persona."""
    other = make_employee()
    authenticated, account = as_role(client, make_user, Role.EMPLOYEE)
    account.user_permissions.add(Permission.objects.get(codename="add_employmentcontract"))

    response = authenticated.post(
        reverse("contracts:create", args=[other.public_id]),
        {"company": company.pk, "contract_type": "INDEFINITE", "start_date": dt.date(2025, 1, 1)},
    )

    assert response.status_code == 404
    assert not other.contracts.exists()
