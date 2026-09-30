"""Casos de uso de escritura sobre cuentas.

Todos son transaccionales y emiten su `AuditEvent` en la misma transacción: no
puede existir un cambio de acceso sin su rastro (ADR-008, ADR-009).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from allauth.account.forms import ResetPasswordForm
from allauth.account.models import EmailAddress
from allauth.core.context import request_context
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from apps.accounts.roles import INCOMPATIBLE_ROLES, Role
from apps.audit.constants import AuditAction, AuditOutcome
from apps.audit.services import record
from apps.core.exceptions import ConflictError, ValidationError

if TYPE_CHECKING:  # pragma: no cover
    from apps.accounts.models import User

logger = logging.getLogger(__name__)
UserModel = get_user_model()


def invalidate_sessions_for(user: User) -> int:
    """Cierra todas las sesiones activas del usuario. Devuelve cuántas cerró.

    Se usa al revocar privilegios o desactivar una cuenta. Sin esto, un usuario
    al que se le retira un rol conserva el acceso hasta que expire su cookie —un
    hallazgo clásico de auditoría—, porque los permisos se leen de la sesión.

    Recorre las sesiones vigentes y decodifica cada una. Es O(sesiones activas),
    aceptable a la escala de este sistema; si algún día dejara de serlo, la
    alternativa es un contador de versión por usuario comprobado en middleware.
    """
    target = str(user.pk)
    closed = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == target:
            session.delete()
            closed += 1
    return closed


@transaction.atomic
def invite_user(
    *,
    email: str,
    roles: list[str] | None = None,
    actor: User,
    request: HttpRequest,
) -> User:
    """Crea una cuenta e invita a su titular a fijar su contraseña.

    Es el **único** mecanismo de alta de la Fase 2 (ADR-004). La cuenta nace con
    contraseña inutilizable: la persona la fija a través de un enlace firmado, de
    un solo uso y con expiración, lo que verifica de paso que controla el buzón.

    ``request`` se recibe **solo** para que allauth construya la URL absoluta del
    correo, no como dependencia de dominio.
    """
    email = email.strip().lower()
    if UserModel.objects.filter(email=email).exists():
        raise ConflictError("user_already_exists", email=email)

    user = UserModel(email=email, is_active=True)
    user.set_unusable_password()
    user.full_clean(exclude=["password"])
    user.save()

    # allauth necesita el registro de correo para el flujo de verificación.
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)

    if roles:
        _apply_roles(user, roles)

    record(
        action=AuditAction.USER_CREATE,
        actor=actor,
        obj=user,
        request=request,
        metadata={"email": email, "roles": sorted(roles or [])},
    )

    # Reutiliza el flujo de restablecimiento de allauth en lugar de inventar un
    # mecanismo propio: token firmado, un solo uso, expiración (regla 30).
    #
    # `request_context` es necesario porque allauth resuelve el dominio del
    # enlace desde una variable de contexto que normalmente fija su middleware.
    # Entrar explícitamente permite invocar este servicio también desde un
    # comando de gestión o una prueba, sin depender del ciclo HTTP.
    with request_context(request):
        form = ResetPasswordForm(data={"email": email})
        if form.is_valid():
            form.save(request)
        else:  # pragma: no cover - solo si allauth cambia su validación
            logger.error("No se pudo enviar la invitación a %s: %s", email, form.errors)

    return user


@transaction.atomic
def set_user_roles(*, user: User, roles: list[str], actor: User, request: HttpRequest) -> User:
    """Sustituye los roles de un usuario.

    Reglas de seguridad que aplica (§J.5):

    * Un actor **no puede modificar sus propios roles**: es la vía directa de
      escalada de privilegios.
    * `AUDITOR` no se combina con roles de escritura (separación de funciones).
    * Un cambio de privilegios **invalida las sesiones** del afectado.
    """
    if actor.pk == user.pk:
        raise ConflictError("cannot_change_own_roles", user=str(user))

    previous = sorted(user.groups.values_list("name", flat=True))
    _apply_roles(user, roles)
    closed = invalidate_sessions_for(user)

    record(
        action=AuditAction.ROLE_CHANGE,
        actor=actor,
        obj=user,
        request=request,
        metadata={"from": previous, "to": sorted(roles), "sessions_closed": closed},
    )
    return user


@transaction.atomic
def deactivate_user(
    *, user: User, actor: User | None, request: HttpRequest | None, reason: str = ""
) -> User:
    """Desactiva una cuenta. **Nunca se borra**, para no perder su rastro."""
    # `actor=None` es el sistema (p. ej. el vencimiento de un contrato).
    if actor is not None and actor.pk == user.pk:
        raise ConflictError("cannot_deactivate_self", user=str(user))

    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    closed = invalidate_sessions_for(user)

    record(
        action=AuditAction.USER_DEACTIVATE,
        actor=actor,
        obj=user,
        request=request,
        metadata={"reason": reason, "sessions_closed": closed},
    )
    return user


def _apply_roles(user: User, roles: list[str]) -> None:
    """Valida y asigna el conjunto de roles."""
    valid = set(Role.values)
    unknown = sorted(set(roles) - valid)
    if unknown:
        raise ValidationError("unknown_roles", roles=unknown)

    for role, incompatible in INCOMPATIBLE_ROLES.items():
        if role in roles and incompatible & set(roles):
            raise ConflictError(
                "incompatible_roles",
                role=role,
                conflicts=sorted(incompatible & set(roles)),
            )

    user.groups.set(Group.objects.filter(name__in=roles))


def record_permission_denied(*, request: HttpRequest, detail: str = "") -> None:
    """Registra un acceso denegado.

    Los intentos denegados son la señal más útil para detectar tanto un error de
    configuración de permisos como un sondeo deliberado.
    """
    record(
        action=AuditAction.PERMISSION_DENIED,
        request=request,
        outcome=AuditOutcome.DENIED,
        metadata={"path": request.path, "detail": detail},
    )
