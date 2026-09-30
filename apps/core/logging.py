"""Filtros de logging.

Este módulo se importa durante la configuración del logging, **antes** de que las
apps estén cargadas: no puede importar modelos ni nada de ``django.db``.

Ver docs/security/11-seguridad.md §K.5.
"""

from __future__ import annotations

import contextvars
import logging
import re

#: Identificador de la petición en curso. Lo fija ``RequestIDMiddleware`` y
#: permite correlacionar una línea de log con un ``AuditEvent``.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

#: Claves cuyo valor jamás debe aparecer en un log (regla RN-72).
SENSITIVE_KEYS: tuple[str, ...] = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "csrf",
    "csrftoken",
    "sessionid",
    "session_key",
    "cookie",
    "dpi",
    "cui",
    "nit",
    "activation_code",
)

REDACTED = "***REDACTED***"

# Captura «clave=valor», «clave: valor» y «"clave": "valor"» en cualquier
# combinación de comillas, que es como aparecen en repr() de dicts y en querystrings.
_ASSIGNMENT_RE = re.compile(
    r"(?i)(['\"]?\b(?:" + "|".join(SENSITIVE_KEYS) + r")\b['\"]?\s*[=:]\s*)"
    r"(\"[^\"]*\"|'[^']*'|[^\s,;&)}\]]+)"
)


def redact(text: str) -> str:
    """Sustituye el valor de cualquier clave sensible por un marcador."""
    return _ASSIGNMENT_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)


class SensitiveDataFilter(logging.Filter):
    """Depura datos sensibles del mensaje antes de que llegue a cualquier handler.

    Se aplica sobre el mensaje ya interpolado, de modo que da igual si el dato
    llegó en ``msg`` o en ``args``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except (TypeError, ValueError):  # pragma: no cover - formato roto del emisor
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


class RequestIDFilter(logging.Filter):
    """Añade ``request_id`` a cada registro para poder correlacionarlo."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True
