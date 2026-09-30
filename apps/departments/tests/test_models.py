"""Restricciones e integridad del organigrama."""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.core.models import Company
from apps.departments.models import Department

pytestmark = pytest.mark.django_db


@pytest.fixture
def root(company: Company) -> Department:
    return Department.objects.create(company=company, code="DIR", name="Dirección General")


def test_code_is_unique_per_company(company: Company, root: Department) -> None:
    with pytest.raises(IntegrityError):
        Department.objects.create(company=company, code=root.code, name="Otro")


def test_same_code_is_allowed_in_another_company(root: Department) -> None:
    """La unicidad es **por empresa**, no global (RN-30, ADR-010)."""
    other = Company.objects.create(code="SUB", legal_name="Filial, S.A.", tax_id="7654321-0")
    Department.objects.create(company=other, code=root.code, name="Dirección de la filial")
    assert Department.objects.filter(code=root.code).count() == 2


def test_a_department_cannot_be_its_own_parent(root: Department) -> None:
    """Lo impide la base, no solo el servicio."""
    root.parent = root
    with pytest.raises(IntegrityError):
        root.save()


def test_parent_is_protected(company: Company, root: Department) -> None:
    """Borrar un padre huérfanaría el subárbol: primero hay que reubicarlo."""
    Department.objects.create(company=company, code="TI", name="Tecnología", parent=root)
    with pytest.raises(ProtectedError):
        root.delete()


def test_company_is_protected(company: Company, root: Department) -> None:
    with pytest.raises(ProtectedError):
        company.delete()


def test_ancestors_walks_up_to_the_root(company: Company, root: Department) -> None:
    it = Department.objects.create(company=company, code="TI", name="Tecnología", parent=root)
    dev = Department.objects.create(company=company, code="DEV", name="Desarrollo", parent=it)

    assert [d.code for d in dev.ancestors()] == ["TI", "DIR"]
    assert root.ancestors() == []
    assert root.is_root is True
    assert dev.is_root is False


def test_ancestors_terminates_even_with_corrupted_data(company: Company, root: Department) -> None:
    """Un ciclo por corrupción no puede colgar el proceso.

    Se fuerza el ciclo saltándose el constraint con un `update` directo, que es
    justo como llegaría una corrupción real: sin pasar por el servicio.
    """
    child = Department.objects.create(company=company, code="TI", name="Tecnología", parent=root)
    Department.objects.filter(pk=root.pk).update(parent=child)

    root.refresh_from_db()
    chain = root.ancestors()

    assert len(chain) <= 2  # termina en lugar de iterar indefinidamente


def test_str_is_not_translated(root: Department) -> None:
    from django.utils import translation

    with translation.override("en"):
        english = str(root)
    with translation.override("es-gt"):
        spanish = str(root)
    assert english == spanish == "DIR - Dirección General"
