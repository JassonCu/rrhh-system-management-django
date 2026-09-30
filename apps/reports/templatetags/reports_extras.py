"""Filtros de presentación de reportes.

Solo formato: ninguna decisión de negocio ni de seguridad vive aquí (regla 3).
"""

from __future__ import annotations

from typing import Any

from django import template

register = template.Library()


@register.filter
def get(mapping: dict[str, Any], key: str) -> Any:
    """Valor de una clave calculada.

    Las filas de un reporte son diccionarios cuyas claves salen del catálogo, y
    la sintaxis de plantillas no permite `fila[columna.key]`.
    """
    if not hasattr(mapping, "get"):
        return ""
    return mapping.get(key, "")
