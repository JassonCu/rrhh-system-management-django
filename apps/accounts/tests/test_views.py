"""Matriz de autorización de las vistas de cuentas.

Se prueba **rol × vista × método × código esperado**. Es la suite que hace
imposible publicar una vista sin decidir explícitamente quién puede usarla
(§J.7).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.accounts.roles import Role
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent

User = get_user_model()
pytestmark = pytest.mark.django_db

ANONYMOUS_REDIRECT = 302


def role_client(client, make_user, *roles: str):
    account = make_user(f"{'-'.join(roles) or 'sinrol'}@example.com", *roles)
    client.force_login(account)
    return client, account


# --- Listado de cuentas ---------------------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.HR_MANAGER,), 403),  # no tiene view_user
        ((Role.AUDITOR,), 200),
        ((Role.MANAGER,), 403),
        ((Role.EMPLOYEE,), 403),
        ((), 403),
    ],
    ids=["hr_admin", "hr_manager", "auditor", "manager", "employee", "sin_rol"],
)
def test_user_list_permissions(client, make_user, roles, expected) -> None:
    authenticated, _account = role_client(client, make_user, *roles)
    assert authenticated.get(reverse("accounts:user_list")).status_code == expected


@pytest.mark.security
def test_user_list_rejects_anonymous(client) -> None:
    assert client.get(reverse("accounts:user_list")).status_code == ANONYMOUS_REDIRECT


# --- Invitación ------------------------------------------------------------ #


@pytest.mark.security
@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ((Role.HR_ADMIN,), 200),
        ((Role.HR_MANAGER,), 403),
        ((Role.AUDITOR,), 403),  # el auditor NO escribe nada
        ((Role.EMPLOYEE,), 403),
    ],
    ids=["hr_admin", "hr_manager", "auditor", "employee"],
)
def test_invite_permissions(client, make_user, roles, expected) -> None:
    authenticated, _account = role_client(client, make_user, *roles)
    assert authenticated.get(reverse("accounts:invite_user")).status_code == expected


@pytest.mark.security
def test_auditor_cannot_invite_by_post(client, make_user) -> None:
    """Un 403 en GET no basta: hay que comprobar también el POST."""
    authenticated, _account = role_client(client, make_user, Role.AUDITOR)
    response = authenticated.post(
        reverse("accounts:invite_user"), {"email": "intruso@example.com", "roles": []}
    )
    assert response.status_code == 403
    assert not User.objects.filter(email="intruso@example.com").exists()


def test_hr_admin_can_invite(client, make_user) -> None:
    authenticated, _account = role_client(client, make_user, Role.HR_ADMIN)
    response = authenticated.post(
        reverse("accounts:invite_user"),
        {"email": "nuevo@example.com", "roles": [Role.EMPLOYEE]},
    )
    assert response.status_code == 302
    assert User.objects.filter(email="nuevo@example.com").exists()


# --- Baja ------------------------------------------------------------------ #


@pytest.mark.security
def test_deactivate_by_get_only_confirms(client, make_user, employee) -> None:
    """Un cambio de estado por GET sería vulnerable a CSRF por enlace: el GET
    muestra la confirmación y no toca la cuenta (plan UX/UI §5)."""
    authenticated, _account = role_client(client, make_user, Role.HR_ADMIN)

    response = authenticated.get(reverse("accounts:deactivate_user", args=[employee.pk]))

    assert response.status_code == 200
    assert b"csrfmiddlewaretoken" in response.content
    employee.refresh_from_db()
    assert employee.is_active is True


@pytest.mark.security
def test_employee_cannot_deactivate_anyone(client, make_user, employee) -> None:
    authenticated, _account = role_client(client, make_user, Role.EMPLOYEE)
    response = authenticated.post(reverse("accounts:deactivate_user", args=[employee.pk]))
    assert response.status_code == 403
    employee.refresh_from_db()
    assert employee.is_active is True


# --- Perfil y alcance ------------------------------------------------------ #


def test_profile_is_reachable_by_any_authenticated_user(client, make_user) -> None:
    authenticated, _account = role_client(client, make_user, Role.EMPLOYEE)
    assert authenticated.get(reverse("accounts:profile")).status_code == 200


def test_profile_saves_preferences(client, make_user) -> None:
    authenticated, account = role_client(client, make_user, Role.EMPLOYEE)
    authenticated.post(reverse("accounts:profile"), {"language": "en"})
    account.refresh_from_db()
    assert account.language == "en"


@pytest.mark.security
def test_scope_limits_what_hr_manager_sees(client, make_user, employee) -> None:
    """El selector acota el queryset; la vista nunca consulta el modelo directo."""
    from apps.accounts import selectors

    hr = make_user("hr2@example.com", Role.HR_MANAGER)
    assert employee in selectors.users_visible_for(hr)

    plain = make_user("plano@example.com", Role.EMPLOYEE)
    visible = selectors.users_visible_for(plain)
    assert list(visible) == [plain]
    assert employee not in visible


@pytest.mark.security
def test_out_of_scope_account_is_404_not_403(client, make_user, employee) -> None:
    """Un 403 confirmaría que la cuenta existe."""
    from django.http import Http404

    from apps.accounts import selectors

    plain = make_user("plano@example.com", Role.EMPLOYEE)
    with pytest.raises(Http404):
        selectors.get_user_or_404(plain, pk=employee.pk)


# --- CSRF ------------------------------------------------------------------ #


@pytest.mark.security
def test_post_without_csrf_token_is_rejected(client, make_user) -> None:
    from django.test import Client

    account = make_user("hr3@example.com", Role.HR_ADMIN)
    enforcing = Client(enforce_csrf_checks=True)
    enforcing.force_login(account)

    response = enforcing.post(
        reverse("accounts:invite_user"), {"email": "sincsrf@example.com", "roles": []}
    )

    assert response.status_code == 403
    assert not User.objects.filter(email="sincsrf@example.com").exists()


# --- Auditoría desde la vista ---------------------------------------------- #


def test_invitation_through_the_view_is_audited(client, make_user) -> None:
    authenticated, actor = role_client(client, make_user, Role.HR_ADMIN)
    authenticated.post(
        reverse("accounts:invite_user"), {"email": "auditado@example.com", "roles": []}
    )
    event = AuditEvent.objects.get(action=AuditAction.USER_CREATE)
    assert event.actor == actor
    assert event.request_id is not None
