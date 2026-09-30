"""El admin no tiene un login propio (revisión de la Fase 4, H-7).

El formulario de acceso de `django.contrib.admin` no pasa por allauth: sin
límite de intentos, sin verificación de correo obligatoria. Era una segunda
puerta, sin frenos, justo hacia las cuentas con más privilegios. Se detectó al
probar la aplicación a mano.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db

EMAIL = "super.admin@example.com"
PASSWORD = "Segura-12345678"  # pragma: allowlist secret


@pytest.fixture
def staff_superuser(django_user_model):
    return django_user_model.objects.create_superuser(email=EMAIL, password=PASSWORD)


@pytest.mark.security
def test_admin_login_sends_anonymous_users_to_allauth(client) -> None:
    response = client.get("/admin/login/")

    assert response.status_code == 302
    assert response.url.startswith(reverse("account_login"))


@pytest.mark.security
def test_admin_login_form_cannot_be_used_to_authenticate(client, staff_superuser) -> None:
    """Credenciales válidas enviadas al formulario del admin no abren sesión."""
    client.post("/admin/login/", {"username": EMAIL, "password": PASSWORD})

    assert "_auth_user_id" not in client.session


@pytest.mark.security
def test_admin_index_still_requires_login(client) -> None:
    response = client.get("/admin/")

    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.security
def test_a_logged_in_superuser_reaches_the_admin(client, staff_superuser) -> None:
    client.force_login(staff_superuser)

    assert client.get("/admin/").status_code == 200
