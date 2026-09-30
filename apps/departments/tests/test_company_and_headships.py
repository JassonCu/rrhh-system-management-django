"""Empresas y jefaturas fuera del admin de Django (UX-3, D-07)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.urls import reverse

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.core.models import Company
from apps.departments.models import Department, DepartmentHeadship
from apps.employees.models import Employee, Person

pytestmark = pytest.mark.django_db


def sign_in(client, make_user, role: str, email: str):
    account = make_user(email, role)
    client.force_login(account)
    return account


@pytest.fixture
def head(db) -> Employee:
    person = Person.objects.create(
        first_name="Ana", last_name="Pérez", birth_date=dt.date(1990, 5, 17)
    )
    return Employee.objects.create(
        person=person, employee_code="EMP-J01", hire_date=dt.date(2024, 1, 15)
    )


@pytest.fixture
def other_head(db) -> Employee:
    person = Person.objects.create(
        first_name="Luis", last_name="García", birth_date=dt.date(1988, 2, 3)
    )
    return Employee.objects.create(
        person=person, employee_code="EMP-J02", hire_date=dt.date(2024, 2, 1)
    )


@pytest.fixture
def area(company) -> Department:
    return Department.objects.create(company=company, code="TI", name="Tecnología")


# --- Empresas ----------------------------------------------------------------- #


def test_hr_admin_creates_a_company_through_the_web(client, make_user) -> None:
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.empresa@example.com")

    response = client.post(
        reverse("departments:company_create"),
        {
            "code": "SUC",
            "legal_name": "Sucursal Ejemplo, S. A.",
            "trade_name": "",
            "tax_id": "9876543-2",
            "country": "GT",
            "is_active": "on",
        },
    )

    assert response.status_code == 302
    assert Company.objects.filter(code="SUC").exists()
    assert AuditEvent.objects.filter(action=AuditAction.COMPANY_CREATE).exists()


def test_editing_a_company_records_what_changed(client, make_user, company) -> None:
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.edita@example.com")

    client.post(
        reverse("departments:company_update", args=[company.pk]),
        {
            "code": company.code,
            "legal_name": "Industrias Ejemplo y Asociados, S. A.",
            "trade_name": company.trade_name,
            "tax_id": company.tax_id,
            "country": company.country,
            "is_active": "on",
        },
    )

    company.refresh_from_db()
    assert company.legal_name.endswith("Asociados, S. A.")
    event = AuditEvent.objects.get(action=AuditAction.COMPANY_UPDATE)
    assert event.metadata["changed"] == ["legal_name"]


@pytest.mark.security
@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.HR_ADMIN, 200), (Role.HR_MANAGER, 200), (Role.AUDITOR, 200), (Role.EMPLOYEE, 403)],
)
def test_company_list_permissions(client, make_user, role, expected) -> None:
    sign_in(client, make_user, role, f"empresa.{role.lower()}@example.com")

    assert client.get(reverse("departments:company_list")).status_code == expected


@pytest.mark.security
def test_hr_manager_cannot_create_companies(client, make_user) -> None:
    """Ver la empresa no es administrarla."""
    sign_in(client, make_user, Role.HR_MANAGER, "analista.empresa@example.com")

    assert client.get(reverse("departments:company_create")).status_code == 403


# --- Jefaturas ---------------------------------------------------------------- #


def test_hr_admin_appoints_a_head(client, make_user, area, head) -> None:
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.jefatura@example.com")

    response = client.post(
        reverse("departments:headship_assign", args=[area.pk]),
        {"employee": head.pk, "start_date": "2026-01-01", "appointment_note": "Acta 12"},
    )

    assert response.status_code == 302
    headship = DepartmentHeadship.objects.get(department=area)
    assert headship.employee == head
    assert headship.is_current
    assert AuditEvent.objects.filter(action=AuditAction.HEADSHIP_ASSIGN).exists()


def test_a_new_appointment_closes_the_previous_one(
    client, make_user, area, head, other_head
) -> None:
    """No se sobrescribe: el historial responde quién mandaba cada día (ADR-014)."""
    DepartmentHeadship.objects.create(
        department=area, employee=head, start_date=dt.date(2025, 1, 1)
    )
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.releva@example.com")

    client.post(
        reverse("departments:headship_assign", args=[area.pk]),
        {"employee": other_head.pk, "start_date": "2026-03-01", "appointment_note": ""},
    )

    previous, current = DepartmentHeadship.objects.order_by("start_date")
    assert previous.end_date == dt.date(2026, 2, 28)
    assert current.employee == other_head
    assert current.is_current


def test_an_appointment_cannot_start_before_the_current_one(
    client, make_user, area, head, other_head
) -> None:
    DepartmentHeadship.objects.create(
        department=area, employee=head, start_date=dt.date(2026, 6, 1)
    )
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.fecha@example.com")

    client.post(
        reverse("departments:headship_assign", args=[area.pk]),
        {"employee": other_head.pk, "start_date": "2026-01-01", "appointment_note": ""},
    )

    assert DepartmentHeadship.objects.count() == 1


@pytest.mark.security
def test_ending_a_headship_confirms_first(client, make_user, area, head) -> None:
    headship = DepartmentHeadship.objects.create(
        department=area, employee=head, start_date=dt.date(2025, 1, 1)
    )
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.cierra@example.com")
    url = reverse("departments:headship_end", args=[area.pk, headship.pk])

    confirmation = client.get(url)

    assert confirmation.status_code == 200
    assert b"csrfmiddlewaretoken" in confirmation.content
    headship.refresh_from_db()
    assert headship.is_current

    client.post(url, {"end_date": "2026-05-31"})

    headship.refresh_from_db()
    assert headship.end_date == dt.date(2026, 5, 31)
    assert AuditEvent.objects.filter(action=AuditAction.HEADSHIP_END).exists()


@pytest.mark.security
def test_a_headship_of_another_department_is_404(client, make_user, company, area, head) -> None:
    """La jefatura se busca DENTRO del departamento de la URL (IDOR)."""
    other_area = Department.objects.create(company=company, code="RH", name="Recursos Humanos")
    headship = DepartmentHeadship.objects.create(
        department=other_area, employee=head, start_date=dt.date(2025, 1, 1)
    )
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.idor@example.com")

    response = client.get(reverse("departments:headship_end", args=[area.pk, headship.pk]))

    assert response.status_code == 404
    headship.refresh_from_db()
    assert headship.is_current


@pytest.mark.security
@pytest.mark.parametrize("role", [Role.HR_MANAGER, Role.MANAGER, Role.EMPLOYEE, Role.AUDITOR])
def test_only_hr_admin_appoints_heads(client, make_user, area, role) -> None:
    sign_in(client, make_user, role, f"jefatura.{role.lower()}@example.com")

    assert client.get(reverse("departments:headship_assign", args=[area.pk])).status_code == 403


@pytest.mark.security
def test_the_appointment_form_only_offers_visible_people(client, make_user, area, head) -> None:
    """El desplegable se acota con el selector: no se nombra por POST a quien no se ve."""
    sign_in(client, make_user, Role.HR_ADMIN, "rrhh.alcance@example.com")

    form = client.get(reverse("departments:headship_assign", args=[area.pk])).context["form"]

    assert head in form.fields["employee"].queryset
