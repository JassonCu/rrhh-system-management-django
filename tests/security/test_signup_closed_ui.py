"""La interfaz no invita a un registro que no existe (ADR-004).

`test_url_coverage.py` ya prueba que `/accounts/signup/` responde 404; esto
cubre la otra mitad: que ninguna pantalla pública lo enlace. La plantilla de
allauth lo hace por defecto, y se detectó al probar la aplicación a mano.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.mark.security
def test_login_page_does_not_link_to_signup(client) -> None:
    response = client.get(reverse("account_login"))

    assert response.status_code == 200
    assert b"/accounts/signup/" not in response.content
    assert b"sign up" not in response.content.lower()


@pytest.mark.security
def test_login_page_keeps_a_working_form(client) -> None:
    """Sustituir la plantilla no debe romper el formulario ni su protección CSRF."""
    response = client.get(reverse("account_login"))

    assert b'name="csrfmiddlewaretoken"' in response.content
    assert b'name="login"' in response.content
    assert b'name="password"' in response.content
