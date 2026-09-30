"""El verificador de catálogos es parte de la barrera de CI: se prueba como tal."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_translations import check_catalog

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n'


def write_po(tmp_path: Path, body: str) -> Path:
    po = tmp_path / "django.po"
    po.write_text(f"{HEADER}\n{body}", encoding="utf-8")
    return po


def test_translated_catalog_has_no_problems(tmp_path: Path) -> None:
    po = write_po(tmp_path, '#: apps/core/models.py:40\nmsgid "company"\nmsgstr "empresa"\n')
    assert check_catalog(po) == []


def test_untranslated_entry_is_reported(tmp_path: Path) -> None:
    po = write_po(tmp_path, '#: apps/core/models.py:41\nmsgid "holiday"\nmsgstr ""\n')
    problems = check_catalog(po)
    assert len(problems) == 1
    assert "sin traducir" in problems[0]
    assert "holiday" in problems[0]


def test_fuzzy_entry_is_reported(tmp_path: Path) -> None:
    po = write_po(
        tmp_path,
        '#: apps/core/models.py:42\n#, fuzzy\nmsgid "statutory"\nmsgstr "obligatorio"\n',
    )
    problems = check_catalog(po)
    assert len(problems) == 1
    assert "fuzzy" in problems[0]


def test_multiline_entry_is_understood(tmp_path: Path) -> None:
    """Las cadenas largas se parten en varias líneas: no deben dar falso positivo."""
    po = write_po(
        tmp_path,
        "#: apps/core/models.py:50\n"
        'msgid ""\n"A long message that spans "\n"several lines"\n'
        'msgstr ""\n"Un mensaje largo que ocupa "\n"varias lineas"\n',
    )
    assert check_catalog(po) == []


def test_multiline_entry_without_translation_is_reported(tmp_path: Path) -> None:
    po = write_po(
        tmp_path,
        "#: apps/core/models.py:50\n"
        'msgid ""\n"A long message that spans "\n"several lines"\n'
        'msgstr ""\n""\n',
    )
    problems = check_catalog(po)
    assert len(problems) == 1
    assert "sin traducir" in problems[0]


def test_plural_forms_are_understood(tmp_path: Path) -> None:
    po = write_po(
        tmp_path,
        "#: apps/core/models.py:60\n"
        'msgid "%(count)s day"\nmsgid_plural "%(count)s days"\n'
        'msgstr[0] "%(count)s día"\nmsgstr[1] "%(count)s días"\n',
    )
    assert check_catalog(po) == []


def test_header_is_not_flagged(tmp_path: Path) -> None:
    """La cabecera tiene msgid vacío y suele venir marcada fuzzy: es normal."""
    po = tmp_path / "django.po"
    po.write_text(f"#, fuzzy\n{HEADER}", encoding="utf-8")
    assert check_catalog(po) == []


@pytest.mark.parametrize("entries", [1, 3])
def test_reports_every_problem(tmp_path: Path, entries: int) -> None:
    body = "".join(
        f'#: apps/core/models.py:{i}\nmsgid "term{i}"\nmsgstr ""\n\n' for i in range(entries)
    )
    assert len(check_catalog(write_po(tmp_path, body))) == entries
