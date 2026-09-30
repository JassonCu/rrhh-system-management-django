"""Formato localizado para Guatemala.

Esta prueba existe para impedir una regresión concreta y cara: el catálogo «es»
de Django usa la convención de España (1.500,00). Si alguien retira
FORMAT_MODULE_PATH o cambia LANGUAGE_CODE, todos los importes salariales
cambiarían de significado en silencio. Ver §O.2.2.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.template import Context, Template
from django.utils import formats, translation


@pytest.mark.unit
def test_decimal_uses_guatemalan_separators():
    with translation.override("es-gt"):
        rendered = formats.number_format(Decimal("1500.00"), decimal_pos=2, force_grouping=True)
    assert rendered == "1,500.00", (
        "Se esperaba punto decimal y coma de millares. "
        "Si esto falla, revisa config/formats/es_GT/formats.py."
    )


@pytest.mark.unit
def test_large_decimal_grouping():
    with translation.override("es-gt"):
        rendered = formats.number_format(Decimal("1234567.89"), decimal_pos=2, force_grouping=True)
    assert rendered == "1,234,567.89"


@pytest.mark.unit
def test_generic_spanish_would_use_a_different_convention():
    """Demuestra que el módulo propio es lo que marca la diferencia.

    El catálogo «es» de Django usa coma decimal y espacio duro (U+00A0) como
    separador de millares: 1500 quedaría como «1 500,00». Lo peligroso no es el
    separador de millares sino la coma decimal, que invierte la lectura del
    importe respecto de la convención guatemalteca.
    """
    with translation.override("es"):
        rendered = formats.number_format(Decimal("1500.00"), decimal_pos=2, force_grouping=True)
    assert rendered == "1 500,00"  # noqa: RUF001 - el NBSP es justamente lo que se comprueba
    assert "," in rendered  # coma DECIMAL: justo lo que no queremos en Guatemala


@pytest.mark.unit
def test_date_format_is_day_first():
    with translation.override("es-gt"):
        rendered = formats.date_format(date(2026, 9, 9), "SHORT_DATE_FORMAT")
    assert rendered == "09/09/2026"


@pytest.mark.unit
def test_date_input_accepts_local_and_iso():
    with translation.override("es-gt"):
        accepted = formats.get_format("DATE_INPUT_FORMATS")
    assert "%d/%m/%Y" in accepted
    assert "%Y-%m-%d" in accepted  # el input type=date del navegador envía ISO


@pytest.mark.unit
def test_week_starts_on_monday():
    with translation.override("es-gt"):
        assert formats.get_format("FIRST_DAY_OF_WEEK") == 1


@pytest.mark.unit
def test_template_rendering_is_localized():
    template = Template("{% load l10n %}{{ value }}")
    with translation.override("es-gt"):
        rendered = template.render(Context({"value": Decimal("2500.50")}))
    assert rendered == "2,500.50"
