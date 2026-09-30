"""Adaptador de django-allauth.

Cierra el registro público. Ver
[ADR-004](../../docs/decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md).
"""

from __future__ import annotations

from allauth.account.adapter import DefaultAccountAdapter
from django.http import HttpRequest


class NoPublicSignupAdapter(DefaultAccountAdapter):
    """Impide que nadie cree una cuenta por sí mismo.

    Un sistema de RRHH no tiene usuarios anónimos que se registran solos: las
    cuentas las crea RRHH e invita por correo. Este adaptador es **uno de los dos
    mecanismos** que cierran el registro; el otro es la retirada de la ruta en
    ``config/urls.py``. Ninguno basta solo: quitar la URL no protege si una
    actualización de allauth la reintroduce, y el adaptador solo dejaría enlazada
    una ruta que responde error.
    """

    def is_open_for_signup(self, request: HttpRequest) -> bool:  # noqa: ARG002
        return False

    def send_mail(self, template_prefix: str, email: str, context: dict):
        """Registra la **solicitud** de restablecimiento, no solo su final.

        allauth no expone una señal para «alguien pidió restablecer», y es
        justo el evento que delata un intento de tomar una cuenta ajena: el
        restablecimiento que se completa ya se audita aparte.
        """
        if "password_reset" in template_prefix:
            from apps.audit.constants import AuditAction
            from apps.audit.services import record

            record(
                action=AuditAction.PASSWORD_RESET_REQUEST,
                actor=None,
                request=getattr(self, "request", None),
                # El correo no entra en la bitácora: identifica a la persona y
                # la petición aún no está autenticada (§K.5).
                metadata={"requested": True},
            )
        return super().send_mail(template_prefix, email, context)
