"""Matriz de autorización del organigrama.

A diferencia de los puestos, el organigrama es información interna no sensible:
cualquier usuario autenticado lo consulta. Lo que no ve todo el mundo es quién
trabaja en cada área, que llega con `employees` (§J.2).
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.roles import Role
from apps.departments.models import Department

pytestmark = pytest.mark.django_db


@pytest.fixture
def root(company) -> Department:
    return Department.objects.create(company=company, code="DIR", name="Dirección")


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
    assert (
        as_role(client, make_user, *roles).get(reverse("departments:list")).status_code == expected
    )


@pytest.mark.security
def test_list_rejects_anonymous(client) -> None:
    assert client.get(reverse("departments:list")).status_code == 302


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.HR_MANAGER,), 403),
        ((Role.MANAGER,), 403),
        ((Role.AUDITOR,), 403),
    ],
    ids=["hr_admin", "hr_manager", "manager", "auditor"],
)
def test_create_permissions(client, make_user, roles, expected) -> None:
    assert (
        as_role(client, make_user, *roles).get(reverse("departments:create")).status_code
        == expected
    )


def test_hr_admin_creates_a_department(client, make_user, company) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).post(
        reverse("departments:create"),
        {
            "company": company.pk,
            "parent": "",
            "code": "RH",
            "name": "Recursos Humanos",
            "cost_center": "",
        },
    )
    assert response.status_code == 302
    assert Department.objects.filter(code="RH").exists()


@pytest.mark.security
def test_employee_cannot_create(client, make_user, company) -> None:
    response = as_role(client, make_user, Role.EMPLOYEE).post(
        reverse("departments:create"),
        {"company": company.pk, "code": "X", "name": "Intruso"},
    )
    assert response.status_code == 403
    assert not Department.objects.filter(code="X").exists()


def test_detail_shows_the_breadcrumb(client, make_user, company, root) -> None:
    child = Department.objects.create(company=company, code="TI", name="Tecnología", parent=root)
    response = as_role(client, make_user, Role.EMPLOYEE).get(
        reverse("departments:detail", args=[child.pk])
    )
    assert response.status_code == 200
    assert b"Direcci" in response.content


@pytest.mark.security
def test_unknown_department_is_404(client, make_user) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("departments:detail", args=[9999])
    )
    assert response.status_code == 404


@pytest.mark.security
def test_deactivate_by_get_only_confirms(client, make_user, root) -> None:
    """El GET muestra las consecuencias; la baja exige POST con CSRF."""
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("departments:deactivate", args=[root.pk])
    )

    assert response.status_code == 200
    assert b"csrfmiddlewaretoken" in response.content
    root.refresh_from_db()
    assert root.is_active is True


@pytest.mark.security
def test_cycle_shows_an_error_instead_of_crashing(client, make_user, company, root) -> None:
    """La invariante de servicio debe llegar al usuario como mensaje, no como 500."""
    child = Department.objects.create(company=company, code="TI", name="Tecnología", parent=root)

    response = as_role(client, make_user, Role.HR_ADMIN).post(
        reverse("departments:update", args=[root.pk]),
        {
            "company": company.pk,
            "parent": child.pk,
            "code": "DIR",
            "name": "Dirección",
            "cost_center": "",
        },
        follow=True,
    )

    assert response.status_code == 200
    root.refresh_from_db()
    assert root.parent is None  # no se aplicó


@pytest.mark.security
def test_parent_choices_exclude_the_own_subtree(make_user, company, root) -> None:
    """El desplegable no ofrece opciones que el servicio va a rechazar."""
    from apps.departments.forms import DepartmentForm

    child = Department.objects.create(company=company, code="TI", name="Tecnología", parent=root)
    hr = make_user("hr.form@example.com", Role.HR_ADMIN)

    form = DepartmentForm(instance=root, user=hr)
    choices = set(form.fields["parent"].queryset)

    assert root not in choices
    assert child not in choices
