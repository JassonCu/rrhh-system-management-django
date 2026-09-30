"""Fixtures del dominio de empleados."""

from __future__ import annotations

import datetime as dt

import pytest

from apps.employees.models import Employee, Person
from apps.employees.validators import cui_check_digit


def valid_cui(correlative: int = 19283746) -> str:
    """CUI con verificador correcto, para no depender de un literal frágil."""
    for candidate in range(correlative, correlative + 20):
        padded = str(candidate).zfill(8)
        check = cui_check_digit(padded)
        if check is not None:
            return f"{padded}{check}0101"
    raise AssertionError("sin correlativo válido")


@pytest.fixture
def make_person(db):
    counter = {"n": 0}

    def _make(**overrides) -> Person:
        counter["n"] += 1
        defaults = {
            "first_name": "Ana",
            "last_name": f"Pérez{counter['n']}",
            "birth_date": dt.date(1990, 5, 17),
        }
        return Person.objects.create(**{**defaults, **overrides})

    return _make


@pytest.fixture
def make_employee(db, make_person):
    counter = {"n": 0}

    def _make(*, person=None, user=None, **overrides) -> Employee:
        counter["n"] += 1
        defaults = {
            "employee_code": f"EMP-{counter['n']:04d}",
            "hire_date": dt.date(2024, 1, 15),
        }
        return Employee.objects.create(
            person=person or make_person(),
            user=user,
            **{**defaults, **overrides},
        )

    return _make


@pytest.fixture
def person(make_person) -> Person:
    return make_person()


@pytest.fixture
def employee_record(make_employee) -> Employee:
    """Una ficha de empleado sin cuenta asociada."""
    return make_employee()
