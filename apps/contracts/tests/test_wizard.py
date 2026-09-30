"""Asistente de contratación (UX-3, D-04): puesto → salario → revisar y activar."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import Permission
from django.urls import reverse

from apps.accounts.constants import Role

pytestmark = pytest.mark.django_db


def sign_in(client, make_user, role: str, email: str):
    account = make_user(email, role)
    client.force_login(account)
    return account


def wizard_url(contract) -> str:
    return reverse("contracts:wizard", args=[contract.public_id])


def test_creating_a_contract_opens_the_wizard(client, make_user, make_employee, company) -> None:
    employee = make_employee()
    sign_in(client, make_user, Role.HR_ADMIN, "asistente.alta@example.com")

    response = client.post(
        reverse("contracts:create", args=[employee.public_id]),
        {"company": company.pk, "contract_type": "INDEFINITE", "start_date": "2025-01-01"},
    )

    contract = employee.contracts.get()
    assert response.url == wizard_url(contract)


def test_the_first_step_is_the_position(client, make_user, draft) -> None:
    """El puesto va antes que el salario: así se puede avisar de la banda (RN-23)."""
    contract = draft()
    sign_in(client, make_user, Role.HR_ADMIN, "asistente.puesto@example.com")

    response = client.get(wizard_url(contract))

    assert response.status_code == 200
    assert response.context["step"] == "position"
    assert b"stepper" in response.content


def test_the_whole_hiring_happens_inside_the_wizard(
    client, make_user, draft, position, company
) -> None:
    contract = draft()
    sign_in(client, make_user, Role.HR_ADMIN, "asistente.completo@example.com")
    url = wizard_url(contract)

    client.post(
        url,
        {
            "position": position.pk,
            "start_date": "2025-01-01",
            "fte": "1.00",
            "is_primary": "on",
            "assignment_reason": "INITIAL",
        },
    )
    assert client.get(url).context["step"] == "salary"

    client.post(
        url,
        {
            "amount": "7000.00",
            "currency": "GTQ",
            "pay_frequency": "MONTHLY",
            "effective_from": "2025-01-01",
            "change_reason": "INITIAL",
        },
    )
    review = client.get(url)
    assert review.context["step"] == "review"
    assert review.context["band"] is not None, "se muestra la banda del grado"

    client.post(reverse("contracts:activate", args=[contract.public_id]))

    contract.refresh_from_db()
    assert contract.status == "ACTIVE"


def test_the_wizard_can_be_left_and_resumed(client, make_user, draft, position) -> None:
    """El paso se deduce del estado, no de la sesión: nada se pierde al salir."""
    contract = draft()
    sign_in(client, make_user, Role.HR_ADMIN, "asistente.retoma@example.com")
    client.post(
        wizard_url(contract),
        {
            "position": position.pk,
            "start_date": "2025-01-01",
            "fte": "1.00",
            "is_primary": "on",
            "assignment_reason": "INITIAL",
        },
    )

    client.get(reverse("contracts:list"))
    resumed = client.get(wizard_url(contract))

    assert resumed.context["step"] == "salary"
    assert resumed.context["assignment"].position == position


def test_a_rejected_step_explains_instead_of_failing(client, make_user, draft, position) -> None:
    contract = draft()
    sign_in(client, make_user, Role.HR_ADMIN, "asistente.error@example.com")

    response = client.post(
        wizard_url(contract),
        {
            "position": position.pk,
            "start_date": "2024-12-01",  # fuera del contrato
            "fte": "1.00",
            "is_primary": "on",
            "assignment_reason": "INITIAL",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert not contract.assignments.exists()
    assert [str(message) for message in response.context["messages"]]


@pytest.mark.security
def test_each_step_checks_its_own_permission(client, make_user, draft, position) -> None:
    """Quien puede asignar puestos no puede, por eso, registrar salarios.

    Se parte de un `HR_MANAGER` —que tiene alcance sobre todos los contratos y
    puede asignar puestos— y se le concede el permiso de cambiar el contrato para
    que el asistente abra. El paso de salario sigue cerrado: exige `change_salary`.
    """
    contract = draft()
    account = make_user("asistente.parcial@example.com", Role.HR_MANAGER)
    account.user_permissions.add(Permission.objects.get(codename="change_employmentcontract"))
    client.force_login(account)
    url = wizard_url(contract)

    client.post(
        url,
        {
            "position": position.pk,
            "start_date": "2025-01-01",
            "fte": "1.00",
            "is_primary": "on",
            "assignment_reason": "INITIAL",
        },
    )

    assert client.get(url).status_code == 403, "el paso de salario exige change_salary"


@pytest.mark.security
def test_the_wizard_respects_scope(client, make_user, hire) -> None:
    """Un contrato fuera del alcance es 404, igual que en la ficha."""
    contract = hire()
    sign_in(client, make_user, Role.EMPLOYEE, "asistente.ajeno@example.com")

    assert client.get(wizard_url(contract)).status_code == 403
