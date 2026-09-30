"""Formato de días en pantalla."""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.leave.templatetags.leave_extras import as_days


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("5.00"), "5"),
        (Decimal("12.50"), "12.5"),
        (Decimal("1.25"), "1.25"),
        (Decimal("-1.00"), "-1"),
        (Decimal("0"), "0"),
        (None, "—"),
        ("n/a", "n/a"),
    ],
)
def test_days_are_shown_without_padding(value, expected) -> None:
    assert as_days(value) == expected
