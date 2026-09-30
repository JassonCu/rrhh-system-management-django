from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.core.validators import validate_country_code, validate_currency_code


@pytest.mark.unit
@pytest.mark.parametrize("value", ["GT", "US", "MX"])
def test_valid_country_codes(value: str) -> None:
    validate_country_code(value)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["gt", "GTM", "G1", "", None])
def test_invalid_country_codes(value) -> None:
    with pytest.raises(ValidationError):
        validate_country_code(value)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["GTQ", "USD"])
def test_valid_currency_codes(value: str) -> None:
    validate_currency_code(value)


@pytest.mark.unit
@pytest.mark.parametrize("value", ["gtq", "GT", "GTQQ", "", None])
def test_invalid_currency_codes(value) -> None:
    with pytest.raises(ValidationError):
        validate_currency_code(value)
