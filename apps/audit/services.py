"""Servicio de registro de auditoría.

Punto de entrada único: :func:`record`. Ninguna otra capa construye un
``AuditEvent`` a mano, para que la depuración de datos sensibles y el *snapshot*
del actor ocurran siempre.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import models
from django.http import HttpRequest

from apps.audit.constants import AuditAction, AuditOutcome
from apps.audit.models import AuditEvent
from apps.core.logging import REDACTED, SENSITIVE_KEYS

logger = logging.getLogger(__name__)

MAX_ACTOR_REPR = 150
MAX_OBJECT_REPR = 200
MAX_USER_AGENT = 255
SYSTEM_ACTOR = "system"
ANONYMOUS_ACTOR = "anonymous"


def sanitize_metadata(value: Any, _depth: int = 0) -> Any:
    """Elimina recursivamente los valores de claves sensibles (RN-72).

    Se aplica **antes** de persistir: la bitácora no puede convertirse en el
    lugar donde acaban las contraseñas que el resto del sistema protege.
    """
    if _depth > 10:  # corta estructuras cíclicas o absurdamente anidadas
        return REDACTED
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if any(sensitive in str(key).lower() for sensitive in SENSITIVE_KEYS)
                else sanitize_metadata(item, _depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_metadata(item, _depth + 1) for item in value]
    return value


def _client_ip(request: HttpRequest) -> str | None:
    """IP del cliente.

    ``X-Forwarded-For`` solo se consulta si hay un proxy de confianza declarado:
    de lo contrario cualquiera podría falsificar la IP que queda registrada.
    """
    from django.conf import settings

    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def _describe(obj: models.Model | None) -> tuple[str, str, str]:
    if obj is None:
        return "", "", ""
    object_type = f"{obj._meta.app_label}.{obj._meta.object_name}"
    object_id = str(getattr(obj, "public_id", None) or obj.pk or "")
    return object_type, object_id, str(obj)[:MAX_OBJECT_REPR]


def record(
    *,
    action: AuditAction | str,
    actor: Any = None,
    obj: models.Model | None = None,
    outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
    request: HttpRequest | None = None,
    metadata: dict[str, Any] | None = None,
    actor_repr: str | None = None,
) -> AuditEvent:
    """Registra un evento auditable.

    Se llama **dentro** de la misma transacción que efectúa el cambio, para que
    no pueda existir un cambio sin su rastro ni un rastro sin su cambio.
    """
    if actor is None and request is not None:
        candidate = getattr(request, "user", None)
        if candidate is not None and getattr(candidate, "is_authenticated", False):
            actor = candidate

    if actor_repr is None:
        if actor is not None:
            actor_repr = str(actor)[:MAX_ACTOR_REPR]
        elif request is not None:
            actor_repr = ANONYMOUS_ACTOR
        else:
            actor_repr = SYSTEM_ACTOR

    object_type, object_id, object_repr = _describe(obj)

    event = AuditEvent(
        actor=actor if actor is not None and getattr(actor, "pk", None) else None,
        actor_repr=actor_repr,
        action=str(action),
        object_type=object_type,
        object_id=object_id,
        object_repr=object_repr,
        outcome=str(outcome),
        metadata=sanitize_metadata(metadata or {}),
    )

    if request is not None:
        event.ip_address = _client_ip(request)
        event.user_agent = request.META.get("HTTP_USER_AGENT", "")[:MAX_USER_AGENT]
        request_id = getattr(request, "request_id", None)
        if request_id is not None:
            event.request_id = request_id

    event.save()
    logger.info(
        "audit action=%s outcome=%s object=%s",
        event.action,
        event.outcome,
        f"{object_type}:{object_id}" if object_type else "-",
    )
    return event
