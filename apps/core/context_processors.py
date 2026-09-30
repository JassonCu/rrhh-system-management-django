"""Procesadores de contexto de plantillas.

`core` no importa ninguna otra app: aquí solo entra lo que es transversal y no
pertenece a ningún dominio.
"""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def brand(_request: HttpRequest) -> dict[str, str]:
    """Nombre del producto para todas las plantillas.

    Es una marca, no texto de interfaz: **no se traduce** y vive en un único
    lugar (docs/ux/16-identidad-de-marca.md).
    """
    return {"PRODUCT_NAME": settings.PRODUCT_NAME}
