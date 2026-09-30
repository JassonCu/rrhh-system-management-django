"""Cabeceras de seguridad presentes en toda respuesta (§K.1, §K.2)."""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.security]


@pytest.fixture
def response(client):
    """Se comprueban las cabeceras sobre la pantalla de acceso.

    Es la única página accesible sin sesión, así que es donde un atacante llega
    primero: si le faltan cabeceras a esta, le faltan a todas.
    """
    return client.get(reverse("account_login"))


def test_login_page_is_reachable(response) -> None:
    assert response.status_code == 200


def test_authenticated_pages_carry_the_same_headers(logged_client, employee) -> None:
    authenticated = logged_client(employee).get(reverse("dashboard:home"))
    assert authenticated.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in authenticated.headers


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "same-origin"),
        ("Cross-Origin-Opener-Policy", "same-origin"),
    ],
)
def test_security_headers(response, header: str, expected: str) -> None:
    assert response.headers.get(header) == expected


def test_csp_header_is_present(response) -> None:
    assert "Content-Security-Policy" in response.headers


def test_csp_is_strict(response) -> None:
    """Sin unsafe-inline ni unsafe-eval: es el punto de toda la política."""
    policy = response.headers["Content-Security-Policy"]
    assert "unsafe-inline" not in policy
    assert "unsafe-eval" not in policy
    assert "default-src 'self'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "form-action 'self'" in policy
    assert "base-uri 'none'" in policy


def test_request_id_is_attached(client) -> None:
    """Sin request_id no se puede correlacionar un log con un AuditEvent."""
    from apps.core.middleware import RequestIDMiddleware

    captured = {}

    def view(request):
        captured["request_id"] = request.request_id
        from django.http import HttpResponse

        return HttpResponse("ok")

    from django.test import RequestFactory

    RequestIDMiddleware(view)(RequestFactory().get("/"))
    assert captured["request_id"] is not None


def test_forged_request_id_header_is_ignored() -> None:
    """Una cabecera arbitraria no debe poder inyectar texto en los logs."""
    import uuid

    from django.http import HttpResponse
    from django.test import RequestFactory

    from apps.core.middleware import RequestIDMiddleware

    captured = {}

    def view(request):
        captured["request_id"] = request.request_id
        return HttpResponse("ok")

    request = RequestFactory().get("/", HTTP_X_REQUEST_ID="not-a-uuid\ninjected line")
    RequestIDMiddleware(view)(request)

    assert isinstance(captured["request_id"], uuid.UUID)
