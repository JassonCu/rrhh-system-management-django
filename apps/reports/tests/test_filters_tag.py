"""Filtro de plantilla que resuelve la clave de cada columna."""

from __future__ import annotations

import pytest

from apps.reports.templatetags.reports_extras import get


@pytest.mark.parametrize(
    ("mapping", "key", "expected"),
    [
        ({"worked_hours": 8}, "worked_hours", 8),
        ({"worked_hours": 8}, "ausente", ""),
        ("no es un diccionario", "clave", ""),
        (None, "clave", ""),
    ],
)
def test_it_answers_without_breaking_the_page(mapping, key, expected) -> None:
    assert get(mapping, key) == expected
