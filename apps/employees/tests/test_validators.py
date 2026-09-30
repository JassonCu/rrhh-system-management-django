"""Validadores de documentos de identificación (Guatemala, supuesto S-01)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.employees.validators import (
    cui_check_digit,
    mask_document_number,
    nit_check_character,
    normalize_document_number,
    validate_cui,
    validate_document_number,
    validate_igss,
    validate_nit,
)

pytestmark = pytest.mark.unit


def build_cui(correlative: str = "19283746", municipality: str = "0101") -> str:
    """Construye un CUI con verificador correcto.

    Si el correlativo dado cae en el caso sin verificador (resto 10), avanza al
    siguiente: ese caso existe de verdad y no debe hacer frágil a la prueba.
    """
    number = int(correlative)
    for candidate in range(number, number + 20):
        padded = str(candidate).zfill(8)
        check = cui_check_digit(padded)
        if check is not None:
            return f"{padded}{check}{municipality}"
    raise AssertionError("no se encontró un correlativo con verificador válido")


# --- Normalización --------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234567-8", "12345678"),
        (" 1234 5678 ", "12345678"),
        ("1.234.567", "1234567"),
        ("123k", "123K"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalization(raw, expected: str) -> None:
    """Sin normalizar, `1234567-8` y `12345678` serían documentos distintos."""
    assert normalize_document_number(raw) == expected


# --- CUI / DPI ------------------------------------------------------------- #


def test_valid_cui_is_accepted() -> None:
    validate_cui(build_cui())


def test_cui_accepts_separators() -> None:
    cui = build_cui()
    formatted = f"{cui[:4]} {cui[4:9]} {cui[9:]}"
    validate_cui(formatted)


@pytest.mark.parametrize("value", ["123", "", "1234567890123456", "abcdefghijklm"])
def test_cui_length_and_digits_are_enforced(value: str) -> None:
    with pytest.raises(ValidationError) as error:
        validate_cui(value)
    assert error.value.code == "invalid_cui_length"


def test_cui_rejects_a_wrong_check_digit() -> None:
    cui = build_cui()
    wrong = f"{cui[:8]}{(int(cui[8]) + 1) % 10}{cui[9:]}"

    with pytest.raises(ValidationError) as error:
        validate_cui(wrong)
    assert error.value.code == "invalid_cui_check_digit"


def test_any_single_digit_change_is_detected() -> None:
    """Propiedad real del verificador: un error de captura de un dígito se ve.

    Solo se comprueban los 8 primeros: el resto del CUI es la parte geográfica,
    que deliberadamente no se valida (haría falta el catálogo de municipios).
    """
    cui = build_cui()
    detected = 0
    for index in range(8):
        mutated = list(cui)
        mutated[index] = str((int(cui[index]) + 1) % 10)
        try:
            validate_cui("".join(mutated))
        except ValidationError:
            detected += 1
    assert detected >= 7


def test_correlatives_without_a_valid_cui_are_reported() -> None:
    """Cuando el resto es 10 no existe CUI: el verificador no cabe en un dígito."""
    impossible = [str(n).zfill(8) for n in range(200) if cui_check_digit(str(n).zfill(8)) is None]
    assert impossible, "debería existir algún correlativo sin verificador válido"


# --- NIT ------------------------------------------------------------------- #


@pytest.mark.parametrize("body", ["123456", "7890123", "1", "99999999"])
def test_generated_nit_is_accepted(body: str) -> None:
    validate_nit(body + nit_check_character(body))


def test_nit_rejects_a_wrong_check_character() -> None:
    body = "1234567"
    correct = nit_check_character(body)
    wrong = "K" if correct != "K" else "0"

    with pytest.raises(ValidationError) as error:
        validate_nit(body + wrong)
    assert error.value.code == "invalid_nit_check"


def test_nit_supports_the_k_check_character() -> None:
    """El verificador K existe y debe aceptarse: rechazarlo bloquearía altas."""
    with_k = [
        str(n) + nit_check_character(str(n))
        for n in range(1, 500)
        if nit_check_character(str(n)) == "K"
    ]
    assert with_k, "debería existir algún NIT con verificador K"
    validate_nit(with_k[0])


@pytest.mark.parametrize("value", ["", "1", "12X4", "ABC"])
def test_malformed_nit_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_nit(value)


# --- IGSS ------------------------------------------------------------------ #


@pytest.mark.parametrize("value", ["123456", "1234567890123"])
def test_valid_igss_shapes(value: str) -> None:
    validate_igss(value)


@pytest.mark.parametrize("value", ["12345", "12345678901234", "12345A"])
def test_invalid_igss_shapes(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_igss(value)


# --- Despacho por tipo ----------------------------------------------------- #


def test_dispatch_applies_the_right_validator() -> None:
    with pytest.raises(ValidationError):
        validate_document_number("DPI", "123")
    validate_document_number("DPI", build_cui())


def test_types_without_a_validator_only_require_a_value() -> None:
    """Un pasaporte extranjero no puede validarse con reglas guatemaltecas."""
    validate_document_number("PASSPORT", "X1234567")
    with pytest.raises(ValidationError) as error:
        validate_document_number("PASSPORT", "   ")
    assert error.value.code == "empty_document"


# --- Enmascarado ----------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1928374650101", "*********0101"),
        ("1234", "****"),
        ("12", "**"),
        ("", ""),
    ],
)
def test_masking_keeps_only_the_last_digits(raw: str, expected: str) -> None:
    assert mask_document_number(raw) == expected


def test_masking_never_leaks_the_beginning() -> None:
    masked = mask_document_number("1928374650101")
    assert "192837" not in masked
