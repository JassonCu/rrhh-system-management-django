"""Las fronteras del monolito modular se verifican, no se confían.

Un monolito modular sin control automático se erosiona en el mes tres: alguien
importa ``employees.models`` desde ``payroll`` porque es rápido, y la
modularidad pasa a ser un diagrama en un documento.

Verifica ADR-001 (monolito modular) y ADR-009 (capas services/selectors).
Ver docs/architecture/08-arquitectura-django.md §H.4.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APPS_DIR = Path(__file__).resolve().parents[1] / "apps"

#: App de primitivas compartidas: cualquiera puede importarla, ella a nadie.
SHARED_APP = "core"

#: Interfaz pública de una app. El resto de sus módulos es privado.
PUBLIC_MODULES = frozenset({"services", "selectors", "constants", "exceptions"})

#: Apps que no pueden depender de ningún dominio (solo de `core`).
DOMAIN_FREE_APPS = frozenset({"core", "audit"})


def iter_app_modules() -> list[tuple[str, Path]]:
    """Devuelve (app, ruta) de cada módulo de producción de cada app.

    Se excluyen migraciones (las genera Django) y **pruebas**: la regla de
    fronteras existe para evitar acoplamiento en el código de producción, y una
    prueba que verifica que se escribió un `AuditEvent` tiene que poder
    consultarlo. Excluirlas es una decisión consciente, no un descuido: si las
    pruebas fueran el único sitio donde se cruza la frontera, el sistema sigue
    siendo modular.
    """
    modules: list[tuple[str, Path]] = []
    excluded = {"migrations", "tests"}
    for app_dir in sorted(p for p in APPS_DIR.iterdir() if p.is_dir()):
        for path in sorted(app_dir.rglob("*.py")):
            if excluded & set(path.parts) or path.name.startswith("test_"):
                continue
            modules.append((app_dir.name, path))
    return modules


def iter_app_imports(path: Path) -> list[tuple[str, str, int]]:
    """Extrae los imports que apuntan a ``apps.<app>.<modulo>``.

    Devuelve tuplas ``(app_destino, modulo_destino, linea)``.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str, int]] = []

    def add(dotted: str, lineno: int) -> None:
        parts = dotted.split(".")
        if len(parts) >= 2 and parts[0] == "apps":
            target_app = parts[1]
            target_module = parts[2] if len(parts) > 2 else ""
            found.append((target_app, target_module, lineno))

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            add(node.module, node.lineno)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                add(alias.name, node.lineno)
    return found


ALL_MODULES = iter_app_modules()
SHARED_APP_MODULES = [m for m in ALL_MODULES if m[0] == SHARED_APP]
DOMAIN_FREE_MODULES = [m for m in ALL_MODULES if m[0] in DOMAIN_FREE_APPS]


@pytest.mark.unit
def test_there_are_modules_to_check() -> None:
    """Si esta prueba falla, el resto está pasando en vacío."""
    assert len(ALL_MODULES) > 10


@pytest.mark.unit
@pytest.mark.parametrize(
    ("app", "path"), SHARED_APP_MODULES, ids=lambda v: getattr(v, "name", str(v))
)
def test_shared_app_depends_on_nobody(app: str, path: Path) -> None:
    """`core` no puede importar ninguna otra app: es la base de todas."""
    offenders = [
        f"{path.name}:{line} importa apps.{target}"
        for target, _module, line in iter_app_imports(path)
        if target != SHARED_APP
    ]
    assert not offenders, f"`core` no debe depender de otras apps: {offenders}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("app", "path"), DOMAIN_FREE_MODULES, ids=lambda v: getattr(v, "name", str(v))
)
def test_domain_free_apps_only_use_core(app: str, path: Path) -> None:
    """`audit` recibe cadenas y diccionarios, no objetos tipados de otros dominios."""
    offenders = [
        f"{path.name}:{line} importa apps.{target}"
        for target, _module, line in iter_app_imports(path)
        if target not in {app, SHARED_APP}
    ]
    assert not offenders, f"`{app}` no debe depender de apps de dominio: {offenders}"


@pytest.mark.unit
@pytest.mark.parametrize(("app", "path"), ALL_MODULES, ids=lambda v: getattr(v, "name", str(v)))
def test_cross_app_imports_use_the_public_interface(app: str, path: Path) -> None:
    """Entre apps solo se consume services/selectors/constants/exceptions.

    Importar ``models`` de otra app de dominio acopla el esquema ajeno al código
    propio; las FK entre apps se declaran por cadena (``"employees.Employee"``).
    """
    offenders = []
    for target, module, line in iter_app_imports(path):
        if target in {app, SHARED_APP}:
            continue  # dentro de la propia app o hacia las primitivas compartidas
        if module and module not in PUBLIC_MODULES:
            offenders.append(f"{path.name}:{line} importa apps.{target}.{module}")

    assert not offenders, (
        "Solo se consume la interfaz pública de otra app "
        f"({', '.join(sorted(PUBLIC_MODULES))}): {offenders}"
    )


@pytest.mark.unit
def test_detects_a_forbidden_import() -> None:
    """Comprueba que el analizador detecta de verdad, y no pasa por vacío."""
    source = "from apps.employees.models import Employee\nimport apps.payroll.views\n"
    tmp = Path(__file__).parent / "_boundary_probe.py"
    tmp.write_text(source, encoding="utf-8")
    try:
        imports = iter_app_imports(tmp)
    finally:
        tmp.unlink()

    assert ("employees", "models", 1) in imports
    assert ("payroll", "views", 2) in imports
