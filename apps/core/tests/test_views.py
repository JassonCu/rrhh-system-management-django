"""Páginas de error (§K.6).

El inicio ya no vive aquí: lo sirve `apps.dashboard`, que sí puede leer empleados
y contratos. `core` no depende de ningún dominio (ADR-001).
"""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from apps.core import views


@pytest.mark.django_db
def test_unknown_url_uses_the_custom_404(client) -> None:
    response = client.get("/esta-ruta-no-existe/")
    assert response.status_code == 404
    assert "errors/404.html" in [t.name for t in response.templates]


@pytest.mark.parametrize(
    ("view", "status"),
    [
        (views.bad_request, 400),
        (views.permission_denied, 403),
        (views.page_not_found, 404),
    ],
)
def test_error_views_return_their_status(view, status: int) -> None:
    response = view(RequestFactory().get("/"), Exception("boom"))
    assert response.status_code == status


def test_server_error_page_is_self_contained() -> None:
    """No extiende base.html: si falló la base, la página de error no puede fallar."""
    response = views.server_error(RequestFactory().get("/"))
    assert response.status_code == 500
    body = response.content.decode()
    assert "<html" in body
    # No debe filtrar detalles internos
    assert "Traceback" not in body


@pytest.mark.django_db
def test_error_pages_do_not_leak_internals(client) -> None:
    response = client.get("/esta-ruta-no-existe/")
    body = response.content.decode()
    for leak in ("Traceback", "django.", "settings", "DEBUG"):
        assert leak not in body
