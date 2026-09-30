"""Cobertura de auditoría: ningún servicio escribe sin dejar rastro (§K.7).

Esta prueba no comprueba un caso concreto, **fija una regla**: si un servicio
nuevo guarda algo en la base y nadie lo audita, la suite falla. Es la forma de
que «todo queda registrado» siga siendo cierto dentro de un año y no dependa de
que alguien se acuerde.

Lo hace leyendo el árbol sintáctico de cada `services.py`, no ejecutándolo: así
no hace falta inventar datos para cada operación.

Las excepciones se declaran abajo **con su motivo**. Añadir una es una decisión
consciente que se revisa en la revisión de seguridad de la fase.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from apps.audit.constants import AuditAction

BASE_DIR = pathlib.Path(__file__).resolve().parents[2]

#: Llamadas que escriben en la base.
WRITE_CALLS = frozenset(
    {"save", "create", "delete", "update", "bulk_create", "bulk_update", "get_or_create"}
)

#: Servicios que escriben y **no** auditan, con el motivo de cada uno.
#:
#: Cada excepción es una decisión documentada, no un olvido.
EXEMPTIONS: dict[str, str] = {
    "apps/audit/services.py::record": (
        "Es quien escribe la bitácora. Auditar la auditoría sería un bucle."
    ),
    "apps/accounts/services.py::invalidate_sessions_for": (
        "Cierra sesiones como consecuencia de un cambio de rol o una baja, y esos "
        "sí se auditan. El evento importante es la causa, no el efecto."
    ),
    "apps/reports/services.py::export_to_excel": (
        "El `save` es el del libro de Excel en memoria, no una escritura en la base. "
        "La exportación se audita en `record_export`."
    ),
}


def _module_functions(tree: ast.Module) -> list[ast.FunctionDef]:
    return [node for node in tree.body if isinstance(node, ast.FunctionDef)]


def _called_names(node: ast.FunctionDef) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                names.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                names.add(child.func.attr)
    return names


def _writes(node: ast.FunctionDef) -> set[str]:
    return {
        child.func.attr
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr in WRITE_CALLS
    }


def _audited(functions: list[ast.FunctionDef]) -> set[str]:
    """Funciones que auditan, directamente o llamando a otra que lo hace."""
    audited = {node.name for node in functions if "record" in _called_names(node)}
    for _ in range(len(functions)):  # propaga por la cadena de llamadas
        grown = {
            node.name
            for node in functions
            if node.name not in audited and _called_names(node) & audited
        }
        if not grown:
            break
        audited |= grown
    return audited


def _unaudited_writers() -> list[tuple[str, set[str]]]:
    findings = []
    for path in sorted(BASE_DIR.glob("apps/*/services.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = _module_functions(tree)
        audited = _audited(functions)
        relative = path.relative_to(BASE_DIR).as_posix()
        for node in functions:
            if node.name.startswith("_") or node.name in audited:
                continue
            written = _writes(node)
            if written:
                findings.append((f"{relative}::{node.name}", written))
    return findings


SERVICE_MODULES = sorted(BASE_DIR.glob("apps/*/services.py"))


@pytest.mark.security
def test_there_are_service_modules_to_check() -> None:
    """Si el descubrimiento se rompe, esta prueba deja de proteger nada."""
    assert len(SERVICE_MODULES) >= 8


@pytest.mark.security
def test_every_service_that_writes_leaves_a_trace() -> None:
    """Escribir en la base sin auditar es un hueco, no un detalle."""
    unexpected = {
        name: sorted(calls) for name, calls in _unaudited_writers() if name not in EXEMPTIONS
    }

    assert not unexpected, (
        "Estos servicios escriben en la base y no auditan nada:\n"
        + "\n".join(f"  {name}: {calls}" for name, calls in unexpected.items())
        + "\n\nAñada el evento de auditoría o declare la excepción con su motivo "
        "en EXEMPTIONS."
    )


@pytest.mark.security
def test_no_exemption_is_left_over() -> None:
    """Una excepción que ya no aplica es una regla que dejó de protegernos."""
    current = {name for name, _calls in _unaudited_writers()}
    stale = sorted(set(EXEMPTIONS) - current)

    assert not stale, f"Excepciones que ya no hacen falta, quítelas: {stale}"


@pytest.mark.security
def test_every_exemption_explains_itself() -> None:
    for name, reason in EXEMPTIONS.items():
        assert len(reason) > 40, f"La excepción de {name} no explica por qué"


@pytest.mark.security
def test_every_declared_action_is_actually_used() -> None:
    """Una acción declarada y nunca emitida es una promesa que nadie cumple."""
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            *BASE_DIR.glob("apps/*/services.py"),
            *BASE_DIR.glob("apps/*/views.py"),
            *BASE_DIR.glob("apps/*/*.py"),
        ]
    )
    #: Fases que aún no existen: sus acciones ya están declaradas a propósito.
    pending = {
        AuditAction.PAYROLL_RUN_EXECUTE,
        AuditAction.PAYROLL_RUN_APPROVE,
        AuditAction.ACTIVATION_CODE_ISSUE,
        AuditAction.ACTIVATION_CODE_REDEEM,
        AuditAction.ACTIVATION_CODE_FAILED,
        AuditAction.ACTIVATION_CODE_REVOKE,
    }

    unused = sorted(
        action.name
        for action in AuditAction
        if action not in pending and f"AuditAction.{action.name}" not in sources
    )

    assert not unused, f"Acciones declaradas que nadie emite: {unused}"
