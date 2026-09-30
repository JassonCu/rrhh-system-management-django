"""Conexión de los eventos de autenticación con la bitácora.

Cubre la tabla §I.6 del documento de autenticación. El registro se hace por
señales y no dentro de las vistas de allauth porque así funciona igual sea cual
sea el camino de entrada (formulario, comando de gestión, futura API).
"""

from __future__ import annotations

import logging

from allauth.account.signals import email_confirmed, password_changed, password_reset
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from apps.audit.constants import AuditAction, AuditOutcome
from apps.audit.services import record

logger = logging.getLogger(__name__)


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs) -> None:  # noqa: ARG001
    record(action=AuditAction.LOGIN, actor=user, request=request)


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs) -> None:  # noqa: ARG001
    if user is not None:
        record(action=AuditAction.LOGOUT, actor=user, request=request)


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request=None, **kwargs) -> None:  # noqa: ARG001
    """Registra el intento fallido.

    Guardar el correo intentado es deliberado: es la señal que permite detectar
    fuerza bruta y *credential stuffing* (índice I-22). **Nunca** se registra la
    contraseña: `sanitize_metadata` la depuraría igualmente, pero ni siquiera se
    pasa.
    """
    record(
        action=AuditAction.LOGIN_FAILED,
        outcome=AuditOutcome.FAILURE,
        request=request,
        actor_repr="anonymous",
        metadata={"attempted_email": (credentials or {}).get("email", "")},
    )


@receiver(password_changed)
def on_password_changed(sender, request, user, **kwargs) -> None:  # noqa: ARG001
    _clear_must_change_password(user)
    record(action=AuditAction.PASSWORD_CHANGE, actor=user, request=request)


@receiver(password_reset)
def on_password_reset(sender, request, user, **kwargs) -> None:  # noqa: ARG001
    _clear_must_change_password(user)
    record(action=AuditAction.PASSWORD_RESET_COMPLETE, actor=user, request=request)


@receiver(email_confirmed)
def on_email_confirmed(sender, request, email_address, **kwargs) -> None:  # noqa: ARG001
    record(
        action=AuditAction.EMAIL_VERIFIED,
        actor=email_address.user,
        request=request,
        metadata={"email": email_address.email},
    )


def _clear_must_change_password(user) -> None:
    """Levanta la obligación en cuanto la persona fija una contraseña propia."""
    if getattr(user, "must_change_password", False):
        user.must_change_password = False
        user.save(update_fields=["must_change_password", "updated_at"])


@receiver(post_migrate)
def sync_roles(sender, **kwargs) -> None:  # noqa: ARG001
    """Converge los grupos y sus permisos a lo declarado en ``roles.py``.

    Se ejecuta en el `post_migrate` de **todas** las apps, no solo el de esta, y
    a propósito: Django crea los permisos de cada app en su propio `post_migrate`,
    así que filtrar por ``sender == "accounts"`` sincronizaba antes de que
    existieran los permisos de `audit` y dejaba al auditor sin `view_audit_log`
    en silencio. Como la operación es idempotente, repetirla converge al estado
    correcto en la última pasada; el costo de las intermedias es despreciable.
    """
    from apps.accounts.roles import ROLE_PERMISSIONS

    from .roles_sync import apply_roles

    created, updated = apply_roles(ROLE_PERMISSIONS)
    if created or updated:
        logger.debug("Roles sincronizados: %s creados, %s actualizados", created, updated)
