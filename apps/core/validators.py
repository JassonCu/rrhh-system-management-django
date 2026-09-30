"""Validadores reutilizables del dominio."""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def validate_country_code(value: str) -> None:
    """Valida un código ISO 3166-1 alfa-2.

    No se implementa como ``CheckConstraint``: SQLite no trae ``REGEXP`` y la
    lista completa de 249 países haría ilegible una restricción ``IN``. La
    integridad crítica sí vive en la base (ver docs/database/07-integridad-e-indices.md).
    """
    if not _COUNTRY_RE.match(value or ""):
        raise ValidationError(
            _("%(value)s is not a valid ISO 3166-1 alpha-2 country code."),
            params={"value": value},
            code="invalid_country_code",
        )


def validate_currency_code(value: str) -> None:
    """Valida un código ISO 4217."""
    if not _CURRENCY_RE.match(value or ""):
        raise ValidationError(
            _("%(value)s is not a valid ISO 4217 currency code."),
            params={"value": value},
            code="invalid_currency_code",
        )
