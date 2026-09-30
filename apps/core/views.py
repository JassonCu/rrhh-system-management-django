"""Vistas transversales: portada y páginas de error.

Las páginas de error no consultan la base ni dependen de contexto: si el error
que las provoca es un fallo de base de datos, la página no puede fallar también
(§K.6).

El parámetro ``exception`` no se usa, pero **no puede renombrarse**: Django
invoca estos handlers como ``callback(request, exception=exception)``, es decir,
por palabra clave.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def bad_request(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:  # noqa: ARG001
    return render(request, "errors/400.html", status=400)


def permission_denied(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:  # noqa: ARG001
    return render(request, "errors/403.html", status=403)


def page_not_found(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:  # noqa: ARG001
    return render(request, "errors/404.html", status=404)


def server_error(request: HttpRequest) -> HttpResponse:
    return render(request, "errors/500.html", status=500)
