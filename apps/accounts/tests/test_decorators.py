"""Decoradores de rol (§J.6)."""

from __future__ import annotations

import pytest
from django.contrib.auth.decorators import permission_required
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory

from apps.accounts.constants import Role
from apps.accounts.decorators import (
    has_role,
    is_admin,
    is_auditor,
    is_employee,
    is_hr,
    is_manager,
    is_superadmin,
    role_required,
)
from apps.audit.constants import AuditAction
from apps.audit.models import AuditEvent

pytestmark = pytest.mark.django_db


def view(request) -> HttpResponse:
    return HttpResponse("ok")


@pytest.fixture
def call(rf: RequestFactory):
    """Ejecuta una vista decorada como un usuario dado."""

    def _call(decorator, user, path: str = "/prueba/"):
        request = rf.get(path)
        request.user = user
        return decorator(view)(request)

    return _call


# --- Lo que deja pasar -------------------------------------------------------- #


@pytest.mark.parametrize(
    ("decorator", "role"),
    [
        pytest.param(is_superadmin, Role.SUPERADMIN, id="superadmin"),
        pytest.param(is_admin, Role.HR_ADMIN, id="admin"),
        pytest.param(is_hr, Role.HR_MANAGER, id="hr"),
        pytest.param(is_manager, Role.MANAGER, id="manager"),
        pytest.param(is_employee, Role.EMPLOYEE, id="employee"),
        pytest.param(is_auditor, Role.AUDITOR, id="auditor"),
    ],
)
def test_the_role_it_names_gets_in(call, make_user, decorator, role) -> None:
    response = call(decorator, make_user(f"pasa.{role.lower()}@example.com", role))

    assert response.status_code == 200


def test_hr_reaches_the_screens_of_the_roles_below(call, make_user) -> None:
    """RRHH ve toda la organización: su alcance ya incluye lo de la jefatura."""
    hr = make_user("rrhh.decorador@example.com", Role.HR_ADMIN)

    assert call(is_manager, hr).status_code == 200
    assert call(is_employee, hr).status_code == 200


def test_the_superuser_passes_without_groups(call, superuser) -> None:
    assert call(is_admin, superuser).status_code == 200


def test_the_superuser_can_be_excluded(call, superuser) -> None:
    """Para una pantalla que exige el rol de verdad, no la bandera."""
    strict = role_required(Role.AUDITOR, allow_superuser=False)

    with pytest.raises(PermissionDenied):
        call(strict, superuser)


# --- Lo que no --------------------------------------------------------------- #


@pytest.mark.security
@pytest.mark.parametrize(
    ("decorator", "role"),
    [
        pytest.param(is_superadmin, Role.HR_ADMIN, id="hr-admin-is-not-superadmin"),
        pytest.param(is_admin, Role.HR_MANAGER, id="analyst-is-not-admin"),
        pytest.param(is_hr, Role.MANAGER, id="head-is-not-hr"),
        pytest.param(is_manager, Role.EMPLOYEE, id="employee-is-not-a-head"),
        pytest.param(is_auditor, Role.HR_ADMIN, id="hr-is-not-the-auditor"),
        pytest.param(is_employee, Role.AUDITOR, id="the-auditor-is-not-staff"),
    ],
)
def test_the_wrong_role_is_refused(call, make_user, decorator, role) -> None:
    with pytest.raises(PermissionDenied):
        call(decorator, make_user(f"falla.{role.lower()}.{id(decorator)}@example.com", role))


@pytest.mark.security
def test_a_user_without_roles_is_refused(call, user) -> None:
    with pytest.raises(PermissionDenied):
        call(is_employee, user)


@pytest.mark.security
def test_without_a_session_it_redirects_to_sign_in(call) -> None:
    """Sin sesión no es 403: es «inicie sesión», como en el resto del sistema."""
    response = call(is_admin, AnonymousUser())

    assert response.status_code == 302
    assert "/accounts/login/" in response.url


@pytest.mark.security
def test_a_refusal_leaves_a_trace(call, make_user) -> None:
    """Un intento denegado es la mejor señal de un sondeo o de un permiso mal puesto."""
    account = make_user("sondea@example.com", Role.EMPLOYEE)

    with pytest.raises(PermissionDenied):
        call(is_admin, account, path="/administracion/")

    event = AuditEvent.objects.get(action=AuditAction.PERMISSION_DENIED)
    assert event.metadata["path"] == "/administracion/"
    assert "HR_ADMIN" in event.metadata["detail"]


# --- Composición -------------------------------------------------------------- #


@pytest.mark.security
def test_stacking_with_a_permission_requires_both(call, make_user) -> None:
    """Apilarlos es «y», no «o»: el rol **y** el permiso."""
    guarded = is_admin(permission_required("employees.view_employee", raise_exception=True)(view))
    hr_admin = make_user("rrhh.apila@example.com", Role.HR_ADMIN)
    auditor = make_user("auditora.apila@example.com", Role.AUDITOR)

    request = RequestFactory().get("/")
    request.user = hr_admin
    assert guarded(request).status_code == 200

    request.user = auditor  # tiene el permiso de ver, pero no el rol
    with pytest.raises(PermissionDenied):
        guarded(request)


def test_the_decorator_keeps_the_view_identity() -> None:
    """`@wraps`: sin esto, `resolver_match.url_name` y el admin se confunden."""
    decorated = is_admin(view)

    assert decorated.__name__ == "view"
    assert decorated.__doc__ == view.__doc__


# --- La pregunta sin decorador ------------------------------------------------- #


def test_has_role_answers_without_raising(make_user, user, superuser) -> None:
    manager = make_user("jefa.consulta@example.com", Role.MANAGER)

    assert has_role(manager, Role.MANAGER)
    assert not has_role(manager, Role.HR_ADMIN)
    assert not has_role(user, Role.EMPLOYEE)
    assert has_role(superuser, Role.HR_ADMIN)
    assert not has_role(superuser, Role.HR_ADMIN, allow_superuser=False)
    assert not has_role(AnonymousUser(), Role.EMPLOYEE)
