"""Validadores de documentos de identificación.

Dependen de la jurisdicción (supuesto S-01: Guatemala) y **no** se implementan
como `CheckConstraint`: SQLite no trae `REGEXP`, el algoritmo no es expresable en
SQL portable, y las reglas de formato cambian con la ley mientras que el esquema
no debería (§B.3).
"""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

CUI_LENGTH = 13
#: Pesos del dígito verificador del CUI: los 8 primeros dígitos se multiplican
#: por 2, 3, … 9.
_CUI_WEIGHTS = range(2, 10)

_DIGITS = re.compile(r"^\d+$")
_NIT_BODY = re.compile(r"^\d+$")


def normalize_document_number(value: str) -> str:
    """Quita espacios, guiones y puntos, y pasa a mayúsculas.

    La normalización es imprescindible **antes** de aplicar la unicidad: sin
    ella, `1234567-8` y `12345678` serían dos documentos distintos para la base y
    el mismo para una persona.
    """
    return re.sub(r"[\s\-.]", "", (value or "")).upper()


def cui_check_digit(correlative: str) -> int | None:
    """Dígito verificador de un CUI a partir de sus 8 primeros dígitos.

    Devuelve ``None`` cuando el resto es 10: ese correlativo no produce un CUI
    válido y el registro civil no lo emite.
    """
    total = sum(
        int(digit) * weight for digit, weight in zip(correlative, _CUI_WEIGHTS, strict=True)
    )
    remainder = total % 11
    return None if remainder == 10 else remainder


def validate_cui(value: str) -> None:
    """Valida un DPI/CUI guatemalteco.

    Comprueba longitud, que sean dígitos y el verificador. **No valida la parte
    geográfica** (departamento y municipio): hacerlo exigiría el catálogo de
    municipios, que este diseño descarta explícitamente (§A.6). Validar de más
    con una tabla incompleta rechazaría documentos legítimos, que es peor que no
    validar.
    """
    number = normalize_document_number(value)

    if len(number) != CUI_LENGTH or not _DIGITS.match(number):
        raise ValidationError(
            _("A DPI must have exactly %(length)s digits."),
            params={"length": CUI_LENGTH},
            code="invalid_cui_length",
        )

    expected = cui_check_digit(number[:8])
    if expected is None or expected != int(number[8]):
        raise ValidationError(
            _("The DPI check digit is not valid."),
            code="invalid_cui_check_digit",
        )


def nit_check_character(body: str) -> str:
    """Carácter verificador de un NIT a partir de su cuerpo.

    Suma ponderada descendente, módulo 11: ``11 - resto``, con 11 → ``0`` y
    10 → ``K``.
    """
    length = len(body)
    total = sum(int(digit) * (length + 1 - index) for index, digit in enumerate(body))
    modulus = 11 - (total % 11)
    if modulus == 11:
        return "0"
    if modulus == 10:
        return "K"
    return str(modulus)


def validate_nit(value: str) -> None:
    """Valida un NIT guatemalteco.

    El último carácter es el verificador y puede ser ``K``.

    .. warning::
       El algoritmo es el públicamente documentado. **Debe contrastarse con
       varios NIT reales antes de salir a producción**: un validador demasiado
       estricto sobre un identificador fiscal bloquea altas legítimas, y ese
       fallo se descubre con el empleado delante.
    """
    number = normalize_document_number(value)

    if len(number) < 2:
        raise ValidationError(_("The NIT is too short."), code="invalid_nit_length")

    body, check = number[:-1], number[-1]
    if not _NIT_BODY.match(body) or check not in "0123456789K":
        raise ValidationError(
            _("A NIT may only contain digits, optionally ending in K."),
            code="invalid_nit_format",
        )

    if nit_check_character(body) != check:
        raise ValidationError(_("The NIT check character is not valid."), code="invalid_nit_check")


def validate_igss(value: str) -> None:
    """Valida un número de afiliación al IGSS.

    Solo se comprueba la forma (dígitos, longitud razonable): el algoritmo del
    verificador no es público, así que validar más sería inventarse una regla.
    """
    number = normalize_document_number(value)
    if not _DIGITS.match(number) or not (6 <= len(number) <= 13):
        raise ValidationError(
            _("The IGSS number must contain between 6 and 13 digits."),
            code="invalid_igss",
        )


#: Validador aplicable a cada tipo de documento. Los tipos sin entrada solo
#: pasan la validación genérica de no estar vacíos.
VALIDATORS_BY_TYPE = {
    "DPI": validate_cui,
    "NIT": validate_nit,
    "IGSS": validate_igss,
}


def validate_document_number(document_type: str, value: str) -> None:
    """Aplica el validador que corresponda al tipo."""
    number = normalize_document_number(value)
    if not number:
        raise ValidationError(_("The document number cannot be empty."), code="empty_document")

    validator = VALIDATORS_BY_TYPE.get(document_type)
    if validator is not None:
        validator(number)


def mask_document_number(value: str, visible: int = 4) -> str:
    """Enmascara un identificador dejando visibles sus últimos dígitos.

    Se usa en listados y en cualquier pantalla donde el número no sea necesario:
    ver que existe un DPI no requiere ver el DPI (§G.19).
    """
    number = (value or "").strip()
    if len(number) <= visible:
        return "*" * len(number)
    return "*" * (len(number) - visible) + number[-visible:]
