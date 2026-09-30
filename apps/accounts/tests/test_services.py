"""Casos de uso de cuentas: invitación, roles y baja."""

from __future__ import annotations

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import RequestFactory

from apps.accounts import services
from apps.accounts.roles import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent
from apps.core.exceptions import ConflictError, ValidationError

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def request_with_user(hr_admin):
    request = RequestFactory().post("/cuentas/usuarios/invitar/")
    request.user = hr_admin
    return request


# --- Invitación ------------------------------------------------------------ #


def test_invite_creates_an_account_without_a_usable_password(request_with_user, hr_admin) -> None:
    user = services.invite_user(
        email="Nuevo@Example.com", roles=[Role.EMPLOYEE], actor=hr_admin, request=request_with_user
    )

    assert user.email == "nuevo@example.com"  # normalizado
    assert not user.has_usable_password()
    assert user.is_active
    assert set(user.groups.values_list("name", flat=True)) == {Role.EMPLOYEE}


def test_invite_registers_the_email_as_unverified(request_with_user, hr_admin) -> None:
    user = services.invite_user(
        email="nuevo@example.com", actor=hr_admin, request=request_with_user
    )
    address = EmailAddress.objects.get(user=user)
    assert address.primary is True
    assert address.verified is False


def test_invite_sends_the_invitation(request_with_user, hr_admin) -> None:
    services.invite_user(email="nuevo@example.com", actor=hr_admin, request=request_with_user)
    assert len(mail.outbox) == 1
    assert "nuevo@example.com" in mail.outbox[0].to


@pytest.mark.security
def test_invite_is_audited(request_with_user, hr_admin) -> None:
    user = services.invite_user(
        email="nuevo@example.com", actor=hr_admin, request=request_with_user
    )

    event = AuditEvent.objects.get(action=AuditAction.USER_CREATE)
    assert event.actor == hr_admin
    assert event.object_id == str(user.pk)


def test_invite_rejects_a_duplicate_email(request_with_user, hr_admin, employee) -> None:
    with pytest.raises(ConflictError) as error:
        services.invite_user(email=employee.email, actor=hr_admin, request=request_with_user)
    assert error.value.code == "user_already_exists"


def test_invite_rejects_an_unknown_role(request_with_user, hr_admin) -> None:
    with pytest.raises(ValidationError) as error:
        services.invite_user(
            email="nuevo@example.com", roles=["ROOT"], actor=hr_admin, request=request_with_user
        )
    assert error.value.code == "unknown_roles"


def test_invite_is_atomic(request_with_user, hr_admin) -> None:
    """Un rol inválido no puede dejar la cuenta creada a medias."""
    with pytest.raises(ValidationError):
        services.invite_user(
            email="fantasma@example.com",
            roles=["ROOT"],
            actor=hr_admin,
            request=request_with_user,
        )
    assert not User.objects.filter(email="fantasma@example.com").exists()


# --- Roles ----------------------------------------------------------------- #


@pytest.mark.security
def test_cannot_change_own_roles(request_with_user, hr_admin) -> None:
    """Escalada de privilegios directa: concederse a uno mismo un rol."""
    with pytest.raises(ConflictError) as error:
        services.set_user_roles(
            user=hr_admin, roles=[Role.SUPERADMIN], actor=hr_admin, request=request_with_user
        )
    assert error.value.code == "cannot_change_own_roles"


@pytest.mark.security
def test_auditor_cannot_be_combined_with_write_roles(request_with_user, hr_admin, employee) -> None:
    """Separación de funciones: quien audita no opera."""
    with pytest.raises(ConflictError) as error:
        services.set_user_roles(
            user=employee,
            roles=[Role.AUDITOR, Role.HR_ADMIN],
            actor=hr_admin,
            request=request_with_user,
        )
    assert error.value.code == "incompatible_roles"


def test_set_roles_replaces_instead_of_adding(request_with_user, hr_admin, employee) -> None:
    services.set_user_roles(
        user=employee, roles=[Role.MANAGER], actor=hr_admin, request=request_with_user
    )
    assert set(employee.groups.values_list("name", flat=True)) == {Role.MANAGER}


@pytest.mark.security
def test_role_change_is_audited_with_before_and_after(
    request_with_user, hr_admin, employee
) -> None:
    services.set_user_roles(
        user=employee, roles=[Role.MANAGER], actor=hr_admin, request=request_with_user
    )
    event = AuditEvent.objects.get(action=AuditAction.ROLE_CHANGE)
    assert event.metadata["from"] == [Role.EMPLOYEE]
    assert event.metadata["to"] == [Role.MANAGER]


@pytest.mark.security
def test_role_change_closes_active_sessions(client, request_with_user, hr_admin, employee) -> None:
    """Sin esto, quien pierde un rol conserva el acceso hasta que expire la cookie."""
    client.force_login(employee)
    assert client.session.get("_auth_user_id") == str(employee.pk)

    services.set_user_roles(
        user=employee, roles=[Role.EMPLOYEE], actor=hr_admin, request=request_with_user
    )

    assert client.get("/").status_code == 302  # la sesión ya no vale


# --- Baja ------------------------------------------------------------------ #


@pytest.mark.security
def test_deactivate_does_not_delete(request_with_user, hr_admin, employee) -> None:
    services.deactivate_user(user=employee, actor=hr_admin, request=request_with_user)

    employee.refresh_from_db()
    assert employee.is_active is False
    assert User.objects.filter(pk=employee.pk).exists()


@pytest.mark.security
def test_cannot_deactivate_self(request_with_user, hr_admin) -> None:
    with pytest.raises(ConflictError) as error:
        services.deactivate_user(user=hr_admin, actor=hr_admin, request=request_with_user)
    assert error.value.code == "cannot_deactivate_self"


@pytest.mark.security
def test_deactivation_closes_sessions(client, request_with_user, hr_admin, employee) -> None:
    client.force_login(employee)
    services.deactivate_user(user=employee, actor=hr_admin, request=request_with_user)
    assert client.get("/").status_code == 302


@pytest.mark.security
def test_deactivation_is_audited(request_with_user, hr_admin, employee) -> None:
    services.deactivate_user(
        user=employee, actor=hr_admin, request=request_with_user, reason="fin de contrato"
    )
    event = AuditEvent.objects.get(action=AuditAction.USER_DEACTIVATE)
    assert event.metadata["reason"] == "fin de contrato"
