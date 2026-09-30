"""Pantallas de entrada: el diseño nuevo no puede romper el acceso."""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.urls import reverse

pytestmark = pytest.mark.django_db

EMAIL = "entrada@example.com"
PASSWORD = "Una-Clave-Larga-2026"  # pragma: allowlist secret


@pytest.fixture
def account(django_user_model):
    user = django_user_model.objects.create_user(email=EMAIL, password=PASSWORD)
    EmailAddress.objects.create(user=user, email=EMAIL, primary=True, verified=True)
    return user


def test_login_uses_the_entrance_layout(client) -> None:
    content = client.get(reverse("account_login")).content

    assert b'class="auth__brand"' in content
    assert b'class="auth__card"' in content
    assert b'class="app-sidebar"' not in content, "la pantalla de entrada no lleva la navegación"


def test_login_explains_that_it_expects_an_email(client) -> None:
    """El campo es type=email: con un nombre de usuario el navegador no envía."""
    content = client.get(reverse("account_login")).content

    assert b'type="email"' in content
    assert b"email address" in content.lower() or b"correo" in content.lower()


def test_password_toggle_is_hidden_without_javascript(client) -> None:
    content = client.get(reverse("account_login")).content

    assert b"data-password-toggle" in content
    assert b"hidden" in content


def test_valid_credentials_sign_in(client, account) -> None:
    response = client.post(reverse("account_login"), {"login": EMAIL, "password": PASSWORD})

    assert response.status_code == 302
    assert "_auth_user_id" in client.session


def test_wrong_credentials_show_the_error_inside_the_card(client, account) -> None:
    response = client.post(reverse("account_login"), {"login": EMAIL, "password": "equivocada"})

    assert response.status_code == 200
    assert b"alert--error" in response.content
    assert "_auth_user_id" not in client.session


@pytest.mark.parametrize("url_name", ["account_reset_password", "account_reset_password_done"])
def test_other_entrance_pages_share_the_layout(client, url_name) -> None:
    response = client.get(reverse(url_name))

    assert response.status_code == 200
    assert b'class="auth__card"' in response.content


def test_regular_pages_keep_the_navigation(client, account) -> None:
    client.force_login(account)

    response = client.get(reverse("accounts:profile"))

    assert b'class="app-sidebar"' in response.content
