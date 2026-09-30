"""Modelos transversales y sus restricciones de integridad."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError

from apps.core.models import Company, Holiday

pytestmark = pytest.mark.django_db


def test_company_code_is_unique(company: Company) -> None:
    with pytest.raises(IntegrityError):
        Company.objects.create(code=company.code, legal_name="Otra, S.A.", tax_id="9999999-9")


def test_company_tax_id_is_unique(company: Company) -> None:
    with pytest.raises(IntegrityError):
        Company.objects.create(code="OTRO", legal_name="Otra, S.A.", tax_id=company.tax_id)


@pytest.mark.parametrize("value", ["gt", "GTM", "1A", "", "Guatemala"])
def test_invalid_country_code_is_rejected(value: str) -> None:
    company = Company(code="X", legal_name="X", tax_id="X", country=value)
    with pytest.raises(ValidationError):
        company.full_clean()


def test_holiday_is_unique_per_company_and_date(company: Company) -> None:
    Holiday.objects.create(company=company, date=dt.date(2026, 9, 15), name="Independencia")
    with pytest.raises(IntegrityError):
        Holiday.objects.create(company=company, date=dt.date(2026, 9, 15), name="Duplicado")


def test_company_cannot_be_deleted_while_referenced(company: Company) -> None:
    """PROTECT, no CASCADE: borrar la empresa no puede vaciar sus catálogos."""
    Holiday.objects.create(company=company, date=dt.date(2026, 9, 15), name="Independencia")
    with pytest.raises(ProtectedError):
        company.delete()


def test_timestamps_are_populated(company: Company) -> None:
    assert company.created_at is not None
    assert company.updated_at is not None
