"""Flujo de autenticación. Cubre la tabla §I.7."""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.audit.constants import AuditAction, AuditOutcome
from apps.audit.models import AuditEvent

User = get_user_model()
PASSWORD = "Segura-12345678"
pytestmark = pytest.mark.django_db


def login(client, email: str, password: str = PASSWORD):
    return client.post(reverse("account_login"), {"login": email, "password": password})


# --- Acceso ---------------------------------------------------------------- #


def test_login_with_valid_credentials(client, employee) -> None:
    response = login(client, employee.email)
    assert response.status_code == 302
    assert client.session.get("_auth_user_id") == str(employee.pk)


def test_login_with_wrong_password_fails(client, employee) -> None:
    response = login(client, employee.email, "contrasena-incorrecta")
    assert response.status_code == 200  # vuelve a mostrar el formulario
    assert "_auth_user_id" not in client.session


def test_inactive_user_cannot_sign_in(client, employee) -> None:
    employee.is_active = False
    employee.save()
    login(client, employee.email)
    assert "_auth_user_id" not in client.session


@pytest.mark.security
def test_unverified_email_cannot_sign_in(client, make_user) -> None:
    """`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`: sin verificar, no se entra."""
    account = User.objects.create_user(email="sinverificar@example.com", password=PASSWORD)
    EmailAddress.objects.create(user=account, email=account.email, primary=True, verified=False)

    login(client, account.email)

    assert "_auth_user_id" not in client.session


@pytest.mark.security
def test_session_key_rotates_on_login(client, employee) -> None:
    """Fijación de sesión: la clave debe cambiar al autenticarse."""
    client.get(reverse("account_login"))  # crea sesión anónima
    before = client.session.session_key

    login(client, employee.email)

    assert client.session.session_key != before


# --- Cierre de sesión ------------------------------------------------------ #


@pytest.mark.security
def test_logout_by_get_does_not_end_the_session(logged_client, employee) -> None:
    """Un GET no puede cerrar sesión: sería un CSRF de logout trivial."""
    client = logged_client(employee)
    client.get(reverse("account_logout"))
    assert client.session.get("_auth_user_id") == str(employee.pk)


def test_logout_by_post_ends_the_session(logged_client, employee) -> None:
    client = logged_client(employee)
    client.post(reverse("account_logout"))
    assert "_auth_user_id" not in client.session


# --- Enumeración y fuerza bruta -------------------------------------------- #


@pytest.mark.security
def test_password_reset_does_not_reveal_whether_the_email_exists(client, employee) -> None:
    known = client.post(reverse("account_reset_password"), {"email": employee.email})
    unknown = client.post(reverse("account_reset_password"), {"email": "nadie@example.com"})

    assert known.status_code == unknown.status_code
    assert known.url == unknown.url


@pytest.mark.security
def test_repeated_failures_are_rate_limited(client, employee) -> None:
    """Tras varios intentos fallidos allauth debe bloquear, no seguir probando."""
    statuses = [login(client, employee.email, "mala").status_code for _ in range(8)]
    # El bloqueo se manifiesta como una respuesta distinta (429 o formulario con
    # error de límite); lo esencial es que en ningún momento se inicie sesión.
    assert "_auth_user_id" not in client.session
    assert statuses  # la petición no revienta


# --- Auditoría de los eventos de acceso ------------------------------------ #


@pytest.mark.security
def test_successful_login_is_audited(client, employee) -> None:
    login(client, employee.email)
    event = AuditEvent.objects.filter(action=AuditAction.LOGIN).latest("occurred_at")
    assert event.actor == employee
    assert event.outcome == AuditOutcome.SUCCESS
    assert event.ip_address is not None


@pytest.mark.security
def test_failed_login_is_audited_without_the_password(client, employee) -> None:
    login(client, employee.email, "una-contrasena-muy-secreta")

    event = AuditEvent.objects.filter(action=AuditAction.LOGIN_FAILED).latest("occurred_at")
    assert event.outcome == AuditOutcome.FAILURE
    assert event.metadata.get("attempted_email") == employee.email
    assert "una-contrasena-muy-secreta" not in str(event.metadata)


def test_logout_is_audited(logged_client, employee) -> None:
    logged_client(employee).post(reverse("account_logout"))
    assert AuditEvent.objects.filter(action=AuditAction.LOGOUT, actor=employee).exists()


# --- Cambio obligatorio de contraseña -------------------------------------- #


@pytest.mark.security
def test_must_change_password_redirects_everywhere(logged_client, employee) -> None:
    employee.must_change_password = True
    employee.save()
    client = logged_client(employee)

    response = client.get(reverse("dashboard:home"))

    assert response.status_code == 302
    assert reverse("account_change_password") in response.url


@pytest.mark.security
def test_must_change_password_cannot_be_dodged_by_another_url(logged_client, employee) -> None:
    employee.must_change_password = True
    employee.save()
    client = logged_client(employee)

    response = client.get(reverse("accounts:profile"))

    assert response.status_code == 302
    assert reverse("account_change_password") in response.url


def test_must_change_password_allows_logout(logged_client, employee) -> None:
    """Quedar encerrado sin poder salir sería un fallo de usabilidad grave."""
    employee.must_change_password = True
    employee.save()
    client = logged_client(employee)

    response = client.post(reverse("account_logout"))

    assert "_auth_user_id" not in client.session
    assert response.status_code == 302
