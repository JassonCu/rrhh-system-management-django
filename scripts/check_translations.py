#!/usr/bin/env python
"""Falla si el catálogo obligatorio tiene cadenas sin traducir o marcadas fuzzy.

``makemessages`` no trae un modo ``--check``, así que el control en CI se compone
de dos piezas: el ``git diff`` sobre ``locale/`` detecta cadenas **nuevas sin
extraer**, y este script detecta cadenas **extraídas pero sin traducir** (§O.8).

Se parsea por bloques en lugar de con una expresión regular: los ``.po`` separan
cada entrada con una línea en blanco y admiten cadenas continuadas en varias
líneas, algo que un regex resuelve mal y de forma frágil.
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
REQUIRED_LOCALES = ("es_GT",)


def _is_empty_value(lines: list[str]) -> bool:
    """True si todas las partes de la cadena están vacías."""
    return all(part.strip() in ('""', "") for part in lines)


def check_catalog(path: Path) -> list[str]:
    problems: list[str] = []
    blocks = path.read_text(encoding="utf-8").split("\n\n")

    for index, block in enumerate(blocks):
        lines = block.splitlines()
        if not lines:
            continue

        # El primer bloque es la cabecera del catálogo: su msgid vacío y su marca
        # fuzzy son normales.
        is_header = index == 0

        msgid: list[str] = []
        msgstr: list[str] = []
        current: list[str] | None = None
        is_fuzzy = False
        reference = ""

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#, ") and "fuzzy" in stripped:
                is_fuzzy = True
            elif stripped.startswith("#:"):
                reference = stripped[2:].strip()
            elif stripped.startswith("msgid_plural "):
                current = None
            elif stripped.startswith("msgid "):
                current = msgid
                current.append(stripped[len("msgid ") :])
            elif stripped.startswith("msgstr["):
                current = msgstr
                current.append(stripped.split("]", 1)[1].strip())
            elif stripped.startswith("msgstr "):
                current = msgstr
                current.append(stripped[len("msgstr ") :])
            elif stripped.startswith('"') and current is not None:
                current.append(stripped)

        if is_header or not msgid or _is_empty_value(msgid):
            continue

        label = msgid[0][:70]
        if is_fuzzy:
            problems.append(f"{path.name}: marcada como fuzzy -> {label} ({reference})")
        elif not msgstr or _is_empty_value(msgstr):
            problems.append(f"{path.name}: sin traducir -> {label} ({reference})")

    return problems


def main() -> int:
    locale_dir = BASE_DIR / "locale"
    if not locale_dir.exists():
        print("No existe locale/: todavía no hay catálogos que comprobar.")
        return 0

    problems: list[str] = []
    checked = 0
    for locale in REQUIRED_LOCALES:
        for po in sorted((locale_dir / locale).glob("LC_MESSAGES/*.po")):
            checked += 1
            problems.extend(check_catalog(po))

    if checked == 0:
        print(f"No hay catálogos para {', '.join(REQUIRED_LOCALES)} todavía.")
        return 0

    if problems:
        print(f"Catálogos incompletos ({len(problems)} entradas):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nTraduce las entradas en locale/es_GT/LC_MESSAGES/ antes de fusionar.",
            file=sys.stderr,
        )
        return 1

    print(f"Catálogos completos ({checked} archivos).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
