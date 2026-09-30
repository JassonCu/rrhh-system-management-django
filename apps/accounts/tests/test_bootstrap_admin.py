"""`manage.py bootstrap_admin`: la primera cuenta tiene que poder entrar."""

from __future__ import annotations

from io import StringIO

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.urls import reverse

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db

EMAIL = "Primera.Admin@Example.com"
PASSWORD = "Una-Clave-Larga-2026"  # pragma: allowlist secret


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", EMAIL)
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", PASSWORD)


def run(*args: str) -> str:
    out = StringIO()
    call_command("bootstrap_admin", *args, stdout=out)
    return out.getvalue()


def test_creates_a_verified_superadmin(env) -> None:
    run("--noinput")

    user = get_user_model().objects.get(email=EMAIL.lower())
    assert user.is_superuser and user.is_staff and user.is_active
    assert user.check_password(PASSWORD)
    assert list(user.groups.values_list("name", flat=True)) == [Role.SUPERADMIN]
    address = EmailAddress.objects.get(user=user)
    assert address.verified and address.primary


@pytest.mark.security
def test_the_account_can_sign_in_right_away(env, client) -> None:
    """Es el defecto que motiva el comando: `createsuperuser` deja una cuenta
    que la verificación obligatoria de correo no deja entrar."""
    run("--noinput")

    response = client.post(reverse("account_login"), {"login": EMAIL, "password": PASSWORD})

    assert response.status_code == 302
    assert "_auth_user_id" in client.session


@pytest.mark.security
def test_creation_is_audited_without_the_password(env) -> None:
    output = run("--noinput")

    event = AuditEvent.objects.get(action=AuditAction.USER_CREATE)
    assert PASSWORD not in str(event.metadata)
    assert PASSWORD not in output


@pytest.mark.security
def test_refuses_when_a_superuser_already_exists(env, superuser) -> None:
    """Solo arranca un sistema vacío; el resto de cuentas va por invitación."""
    with pytest.raises(CommandError, match="Ya existe un superusuario"):
        run("--noinput")


@pytest.mark.security
def test_rejects_a_weak_password(env, monkeypatch) -> None:
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "12345")

    with pytest.raises(CommandError, match="Contraseña rechazada"):
        run("--noinput")
    assert not get_user_model().objects.exists()


def test_rejects_an_invalid_email(env) -> None:
    with pytest.raises(CommandError, match="Correo no válido"):
        run("--noinput", "--email", "admin")


def test_noinput_requires_the_password_in_the_environment(env, monkeypatch) -> None:
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD")

    with pytest.raises(CommandError, match="DJANGO_SUPERUSER_PASSWORD"):
        run("--noinput")


def test_interactive_mode_asks_twice_and_rejects_a_mismatch(monkeypatch) -> None:
    answers = iter([PASSWORD, "otra-cosa-distinta"])
    monkeypatch.setattr("builtins.input", lambda _prompt: EMAIL)
    monkeypatch.setattr(
        "apps.accounts.management.commands.bootstrap_admin.getpass",
        lambda _prompt: next(answers),
    )

    with pytest.raises(CommandError, match="no coinciden"):
        run()
    assert not get_user_model().objects.exists()


def test_interactive_mode_creates_the_account(monkeypatch) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: EMAIL)
    monkeypatch.setattr(
        "apps.accounts.management.commands.bootstrap_admin.getpass", lambda _prompt: PASSWORD
    )

    run()

    assert get_user_model().objects.filter(email=EMAIL.lower(), is_superuser=True).exists()
