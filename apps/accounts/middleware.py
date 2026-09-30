"""Middleware de la app de cuentas."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import resolve, reverse


class MustChangePasswordMiddleware:
    """Fuerza el cambio de contraseña cuando RRHH la ha restablecido.

    Sin esto, una contraseña provisional puede quedarse en uso indefinidamente.
    Las rutas exentas son las mínimas para que la persona **pueda** cambiarla y
    salir: si se dejara fuera alguna, el usuario quedaría en un bucle.
    """

    EXEMPT_URL_NAMES = frozenset(
        {
            "account_change_password",
            "account_set_password",
            "account_logout",
            "account_login",
            "account_email_verification_sent",
            "account_confirm_email",
            "set_language",
        }
    )
    EXEMPT_PATH_PREFIXES = ("/static/", "/media/", "/__debug__/")

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
            and not self._is_exempt(request)
        ):
            return redirect("account_change_password")
        return self.get_response(request)

    def _is_exempt(self, request: HttpRequest) -> bool:
        if request.path.startswith(self.EXEMPT_PATH_PREFIXES):
            return True
        try:
            match = resolve(request.path_info)
        except Exception:
            return True
        if match.url_name in self.EXEMPT_URL_NAMES:
            return True
        # El propio destino de la redirección nunca debe interceptarse.
        return request.path == reverse("account_change_password")
