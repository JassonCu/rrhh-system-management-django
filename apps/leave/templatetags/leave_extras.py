"""Filtros de presentación de ausencias.

Solo formato: ninguna decisión de negocio ni de seguridad vive aquí (regla 3).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def as_days(value) -> str:
    """Días sin ceros de relleno: 5.00 → «5», 12.50 → «12.5», 1.25 → «1.25».

    El saldo y los días hábiles son `Decimal` con dos posiciones; mostrarlos
    tal cual mezcla «0» con «5.00» en la misma pantalla.
    """
    if value is None or value == "":
        return "—"
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    exponent = number.normalize().as_tuple().exponent
    decimals = max(0, -exponent) if isinstance(exponent, int) else 0
    return number_format(number, decimal_pos=decimals, use_l10n=True)
