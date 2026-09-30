"""Excepciones de dominio.

Los servicios lanzan estas excepciones; las vistas las traducen a respuestas
HTTP. **Los servicios no traducen**: llevan un ``code`` estable que va al log y
que la capa de presentación convierte en un mensaje localizado (§O.5.1). Así el
usuario lee su idioma y el log sigue siendo buscable.
"""

from __future__ import annotations


class DomainError(Exception):
    """Raíz de los errores de dominio."""

    default_code = "domain_error"

    def __init__(self, code: str | None = None, **context: object) -> None:
        self.code = code or self.default_code
        self.context = context
        super().__init__(self.code)

    def __str__(self) -> str:
        if self.context:
            details = ", ".join(f"{k}={v!r}" for k, v in sorted(self.context.items()))
            return f"{self.code} ({details})"
        return self.code


class ValidationError(DomainError):
    """Dato inválido: se vuelve a mostrar el formulario."""

    default_code = "validation_error"


class ConflictError(DomainError):
    """Invariante de negocio violada: traslape, saldo insuficiente, FTE excedido."""

    default_code = "conflict"


class PermissionDeniedError(DomainError):
    """El actor no puede ejecutar la operación. Se traduce a 403."""

    default_code = "permission_denied"


class NotFoundError(DomainError):
    """El objeto no existe o está fuera del alcance del actor. Se traduce a 404."""

    default_code = "not_found"
