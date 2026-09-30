"""Cambio y restablecimiento de contraseña, y su rastro de auditoría."""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.core import mail
from django.urls import reverse

from apps.accounts.roles import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent

PASSWORD = "Segura-12345678"
NEW_PASSWORD = "OtraSegura-87654321"
pytestmark = pytest.mark.django_db


def test_password_change_is_audited(logged_client, employee) -> None:
    client = logged_client(employee)

    client.post(
        reverse("account_change_password"),
        {"oldpassword": PASSWORD, "password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
    )

    employee.refresh_from_db()
    assert employee.check_password(NEW_PASSWORD)
    assert AuditEvent.objects.filter(action=AuditAction.PASSWORD_CHANGE, actor=employee).exists()


@pytest.mark.security
def test_password_change_never_records_the_password(logged_client, employee) -> None:
    client = logged_client(employee)
    client.post(
        reverse("account_change_password"),
        {"oldpassword": PASSWORD, "password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
    )

    for event in AuditEvent.objects.all():
        assert NEW_PASSWORD not in str(event.metadata)
        assert PASSWORD not in str(event.metadata)


@pytest.mark.security
def test_password_change_clears_the_forced_flag(logged_client, employee) -> None:
    """En cuanto la persona fija una contraseña propia, deja de estar obligada."""
    employee.must_change_password = True
    employee.save()
    client = logged_client(employee)

    client.post(
        reverse("account_change_password"),
        {"oldpassword": PASSWORD, "password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
    )

    employee.refresh_from_db()
    assert employee.must_change_password is False


@pytest.mark.security
def test_password_change_ends_other_sessions(client, employee) -> None:
    """`ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE`: una contraseña comprometida se corta."""
    from django.test import Client

    other = Client()
    other.force_login(employee)

    client.force_login(employee)
    client.post(
        reverse("account_change_password"),
        {"oldpassword": PASSWORD, "password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
    )

    assert other.get(reverse("dashboard:home")).status_code == 302


@pytest.mark.security
def test_reset_link_is_single_use(client, employee) -> None:
    """Un enlace reutilizable sería una credencial permanente en un buzón."""
    client.post(reverse("account_reset_password"), {"email": employee.email})
    assert len(mail.outbox) == 1
    body = mail.outbox[0].body
    link = next(part for part in body.split() if "/password/reset/key/" in part)

    first = client.get(link, follow=True)
    assert first.status_code == 200

    # allauth redirige al formulario con una clave en sesión; tras completarlo,
    # el enlace original deja de servir.
    client.post(
        first.redirect_chain[-1][0] if first.redirect_chain else link,
        {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
        follow=True,
    )
    employee.refresh_from_db()
    assert employee.check_password(NEW_PASSWORD)

    reused = client.get(link, follow=True)
    assert b"password1" not in reused.content or reused.status_code != 200


def test_email_confirmation_is_audited(client, make_user) -> None:
    from allauth.account.models import EmailConfirmationHMAC

    account = make_user("porverificar@example.com", Role.EMPLOYEE)
    address = EmailAddress.objects.get(user=account)
    address.verified = False
    address.save()

    key = EmailConfirmationHMAC(address).key
    client.post(reverse("account_confirm_email", args=[key]))

    address.refresh_from_db()
    assert address.verified is True
    assert AuditEvent.objects.filter(action=AuditAction.EMAIL_VERIFIED, actor=account).exists()


# --- Baja desde la vista --------------------------------------------------- #


def test_hr_admin_deactivates_through_the_view(client, make_user, employee) -> None:
    hr = make_user("hr.baja@example.com", Role.HR_ADMIN)
    client.force_login(hr)

    response = client.post(
        reverse("accounts:deactivate_user", args=[employee.pk]), {"reason": "renuncia"}
    )

    employee.refresh_from_db()
    assert response.status_code == 302
    assert employee.is_active is False
    assert AuditEvent.objects.filter(action=AuditAction.USER_DEACTIVATE).exists()


@pytest.mark.security
def test_self_deactivation_is_refused_in_the_view(client, make_user) -> None:
    hr = make_user("hr.self@example.com", Role.HR_ADMIN)
    client.force_login(hr)

    client.post(reverse("accounts:deactivate_user", args=[hr.pk]))

    hr.refresh_from_db()
    assert hr.is_active is True


@pytest.mark.security
def test_deactivating_an_unknown_account_is_404(client, make_user) -> None:
    hr = make_user("hr.404@example.com", Role.HR_ADMIN)
    client.force_login(hr)
    assert client.post(reverse("accounts:deactivate_user", args=[99999])).status_code == 404


def test_user_list_search_filters(client, make_user, employee) -> None:
    hr = make_user("hr.busca@example.com", Role.HR_ADMIN)
    client.force_login(hr)

    response = client.get(reverse("accounts:user_list"), {"q": "colaborador"})

    assert response.status_code == 200
    assert employee.email.encode() in response.content


def test_invite_duplicate_shows_an_error(client, make_user, employee) -> None:
    hr = make_user("hr.dup@example.com", Role.HR_ADMIN)
    client.force_login(hr)

    response = client.post(
        reverse("accounts:invite_user"), {"email": employee.email, "roles": []}, follow=True
    )

    assert response.status_code == 200
    content = response.content.lower()
    assert b"already exists" in content or b"ya existe" in content
