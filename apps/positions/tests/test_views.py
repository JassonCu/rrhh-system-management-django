"""Matriz de autorización de puestos y bandas salariales.

El punto crítico de esta app: **la banda salarial es confidencial**. `HR_MANAGER`
ve los puestos pero no los importes, y el acceso al puesto **no hereda** acceso a
su banda (§J.2 y §J.4).
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.roles import Role
from apps.departments.models import Department
from apps.positions.models import JobGrade, Position

pytestmark = pytest.mark.django_db


@pytest.fixture
def department(company) -> Department:
    return Department.objects.create(company=company, code="TI", name="Tecnología")


@pytest.fixture
def grade() -> JobGrade:
    return JobGrade.objects.create(
        code="G05", name="Profesional", level=5, min_salary=6000, max_salary=9000
    )


@pytest.fixture
def position(department, grade) -> Position:
    return Position.objects.create(
        department=department, job_grade=grade, code="ANA-2", title="Analista II"
    )


def as_role(client, make_user, *roles: str):
    account = make_user(f"{'-'.join(roles) or 'sinrol'}@example.com", *roles)
    client.force_login(account)
    return client


# --- Catálogo de puestos --------------------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.HR_MANAGER,), 200),
        ((Role.AUDITOR,), 200),
        ((Role.MANAGER,), 403),
        ((Role.EMPLOYEE,), 403),
    ],
    ids=["hr_admin", "hr_manager", "auditor", "manager", "employee"],
)
def test_position_list_permissions(client, make_user, roles, expected) -> None:
    assert as_role(client, make_user, *roles).get(reverse("positions:list")).status_code == expected


@pytest.mark.security
def test_position_list_rejects_anonymous(client) -> None:
    assert client.get(reverse("positions:list")).status_code == 302


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [((Role.HR_ADMIN,), 200), ((Role.HR_MANAGER,), 403), ((Role.AUDITOR,), 403)],
    ids=["hr_admin", "hr_manager", "auditor"],
)
def test_position_create_permissions(client, make_user, roles, expected) -> None:
    """El AUDITOR no escribe nada, ni siquiera en un catálogo."""
    response = as_role(client, make_user, *roles).get(reverse("positions:create"))
    assert response.status_code == expected


# --- Bandas salariales: confidenciales ------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.AUDITOR,), 200),
        ((Role.HR_MANAGER,), 403),  # el "T (sin banda)" de la matriz
        ((Role.MANAGER,), 403),
        ((Role.EMPLOYEE,), 403),
    ],
    ids=["hr_admin", "auditor", "hr_manager", "manager", "employee"],
)
def test_job_grade_list_permissions(client, make_user, roles, expected) -> None:
    response = as_role(client, make_user, *roles).get(reverse("positions:job_grade_list"))
    assert response.status_code == expected


#: El importe se renderiza localizado (§O.2.2): 6000 se muestra como "6,000.00".
#: Se comprueban todas las formas plausibles para que una aserción negativa no
#: pase por el motivo equivocado — que es justo lo que ocurría al buscar "6000".
AMOUNT_FORMS = (b"6,000.00", b"6000.00", b"6000", b"6,000")


@pytest.mark.security
def test_hr_manager_sees_the_position_but_not_the_amounts(client, make_user, position) -> None:
    """Sin cascada de permisos: ver el puesto no da acceso a su banda."""
    response = as_role(client, make_user, Role.HR_MANAGER).get(
        reverse("positions:detail", args=[position.pk])
    )

    assert response.status_code == 200
    assert b"Analista II" in response.content
    for form in AMOUNT_FORMS:
        assert form not in response.content, f"se filtró el importe como {form!r}"


@pytest.mark.security
def test_hr_admin_sees_the_amounts(client, make_user, position) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("positions:detail", args=[position.pk])
    )
    assert response.status_code == 200
    assert b"6,000.00" in response.content  # localizado para Guatemala


@pytest.mark.security
def test_salary_band_selector_is_independent(make_user, grade) -> None:
    from apps.positions import selectors

    hr_manager = make_user("hrm@example.com", Role.HR_MANAGER)
    hr_admin = make_user("hra@example.com", Role.HR_ADMIN)

    assert list(selectors.job_grades_visible_for(hr_manager)) == []
    assert grade in selectors.job_grades_visible_for(hr_admin)


# --- Escritura y CSRF ------------------------------------------------------ #


def test_hr_admin_creates_a_position(client, make_user, department, grade) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).post(
        reverse("positions:create"),
        {
            "department": department.pk,
            "job_grade": grade.pk,
            "code": "DEV-1",
            "title": "Desarrollador I",
            "description": "",
        },
    )
    assert response.status_code == 302
    assert Position.objects.filter(code="DEV-1").exists()


@pytest.mark.security
def test_deactivate_by_get_only_confirms(client, make_user, position) -> None:
    """El GET muestra las consecuencias; la baja exige POST con CSRF."""
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("positions:deactivate", args=[position.pk])
    )

    assert response.status_code == 200
    assert b"csrfmiddlewaretoken" in response.content
    position.refresh_from_db()
    assert position.is_active is True


@pytest.mark.security
def test_employee_cannot_deactivate_a_position(client, make_user, position) -> None:
    response = as_role(client, make_user, Role.EMPLOYEE).post(
        reverse("positions:deactivate", args=[position.pk])
    )
    assert response.status_code == 403
    position.refresh_from_db()
    assert position.is_active is True


@pytest.mark.security
def test_unknown_position_is_404(client, make_user) -> None:
    response = as_role(client, make_user, Role.HR_ADMIN).get(
        reverse("positions:detail", args=[9999])
    )
    assert response.status_code == 404


@pytest.mark.security
def test_salary_amounts_never_reach_the_audit_log(client, make_user, department, grade) -> None:
    """La bitácora la lee el AUDITOR; los importes no deben viajar ahí."""
    from apps.audit.models import AuditEvent

    as_role(client, make_user, Role.HR_ADMIN).post(
        reverse("positions:job_grade_create"),
        {
            "code": "G09",
            "name": "Dirección",
            "level": 9,
            "min_salary": "25000.00",
            "max_salary": "40000.00",
            "currency": "GTQ",
        },
    )

    for event in AuditEvent.objects.all():
        metadata = str(event.metadata)
        for amount in ("25000", "25,000", "40000", "40,000"):
            assert amount not in metadata
