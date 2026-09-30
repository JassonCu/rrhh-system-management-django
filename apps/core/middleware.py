"""Middleware transversal."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.core.logging import request_id_var


class RequestIDMiddleware:
    """Asigna un identificador único a cada petición.

    Queda disponible en ``request.request_id``, en cada línea de log y en
    ``AuditEvent.request_id``. Es lo que permite reconstruir qué ocurrió en una
    petición concreta cruzando el rastro técnico con el de negocio (§K.5).
    """

    HEADER = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Nunca se confía en la cabecera entrante como identificador: se acepta
        # solo si es un UUID válido, para no permitir inyección en los logs.
        request_id = uuid.uuid4()
        incoming = request.META.get(self.HEADER)
        if incoming:
            with contextlib.suppress(ValueError, AttributeError, TypeError):
                request_id = uuid.UUID(incoming)

        request.request_id = request_id
        token = request_id_var.set(str(request_id))
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        return response
