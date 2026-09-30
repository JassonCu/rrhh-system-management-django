"""Restricciones del catálogo de puestos y bandas salariales."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError

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


# --- JobGrade -------------------------------------------------------------- #


def test_grade_code_is_unique(grade: JobGrade) -> None:
    with pytest.raises(IntegrityError):
        JobGrade.objects.create(
            code=grade.code, name="Otro", level=6, min_salary=1000, max_salary=2000
        )


def test_minimum_salary_must_be_positive() -> None:
    with pytest.raises(IntegrityError):
        JobGrade.objects.create(code="G0", name="X", level=1, min_salary=0, max_salary=100)


def test_range_cannot_be_inverted() -> None:
    """El constraint vive en la base, no solo en `full_clean` (RN-34)."""
    with pytest.raises(IntegrityError):
        JobGrade.objects.create(code="GX", name="X", level=1, min_salary=9000, max_salary=1000)


def test_equal_minimum_and_maximum_is_valid() -> None:
    """Una banda de un solo punto es legítima; el constraint usa `>=`."""
    grade = JobGrade.objects.create(
        code="GF", name="Fijo", level=1, min_salary=5000, max_salary=5000
    )
    assert grade.pk is not None


@pytest.mark.parametrize("value", ["gtq", "GT", "GTQQ", ""])
def test_invalid_currency_is_rejected(value: str) -> None:
    grade = JobGrade(code="GC", name="X", level=1, min_salary=1, max_salary=2, currency=value)
    with pytest.raises(ValidationError):
        grade.full_clean()


def test_contains_checks_the_band(grade: JobGrade) -> None:
    assert grade.contains(Decimal("6000")) is True
    assert grade.contains(Decimal("9000")) is True
    assert grade.contains(Decimal("5999")) is False
    assert grade.contains(Decimal("9001")) is False


# --- Position -------------------------------------------------------------- #


def test_position_belongs_to_a_department(department: Department, grade: JobGrade) -> None:
    """ADR-011: el puesto pertenece a un área, y el departamento vive aquí."""
    position = Position.objects.create(
        department=department, job_grade=grade, code="ANA-2", title="Analista II"
    )
    assert position.department == department


def test_title_is_unique_within_the_department(department: Department, grade: JobGrade) -> None:
    """RN-35: dos puestos con el mismo título en la misma área es un error."""
    Position.objects.create(
        department=department, job_grade=grade, code="ANA-2", title="Analista II"
    )
    with pytest.raises(IntegrityError):
        Position.objects.create(
            department=department, job_grade=grade, code="OTRO", title="Analista II"
        )


def test_same_title_is_allowed_in_another_department(company, department, grade) -> None:
    """La unicidad es **por departamento**, no global."""
    other = Department.objects.create(company=company, code="RH", name="Recursos Humanos")
    Position.objects.create(
        department=department, job_grade=grade, code="ANA-TI", title="Analista II"
    )
    Position.objects.create(department=other, job_grade=grade, code="ANA-RH", title="Analista II")

    assert Position.objects.filter(title="Analista II").count() == 2


def test_position_code_is_globally_unique(company, department, grade) -> None:
    other = Department.objects.create(company=company, code="RH", name="Recursos Humanos")
    Position.objects.create(department=department, job_grade=grade, code="ANA", title="Analista")
    with pytest.raises(IntegrityError):
        Position.objects.create(department=other, job_grade=grade, code="ANA", title="Otro")


def test_department_is_protected(department: Department, grade: JobGrade) -> None:
    """Borrar un departamento no puede borrar las definiciones de puesto del área."""
    Position.objects.create(department=department, job_grade=grade, code="ANA", title="Analista")
    with pytest.raises(ProtectedError):
        department.delete()


def test_job_grade_is_protected(department: Department, grade: JobGrade) -> None:
    Position.objects.create(department=department, job_grade=grade, code="ANA", title="Analista")
    with pytest.raises(ProtectedError):
        grade.delete()


def test_position_has_no_salary_fields() -> None:
    """El rango vive solo en `JobGrade` (3NF, §D.5.2)."""
    field_names = {f.name for f in Position._meta.get_fields()}
    assert not {"min_salary", "max_salary", "salary"} & field_names
