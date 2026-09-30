"""Decoradores de rol para vistas: `@is_admin`, `@is_manager`, `@is_hr`…

**Qué son y qué no son.** El sistema autoriza por **permiso + alcance**
(ADR-005): el permiso dice qué se puede hacer y el selector, sobre quién. Estos
decoradores no sustituyen ninguna de las dos cosas; responden a otra pregunta,
la de *quién es* quien entra, que en unas pocas pantallas es el criterio real:
un panel de administración, una consola de auditoría, la bandeja de una
jefatura.

**Cómo usarlos sin romper la matriz §J.2:**

- Para «esta acción exige este permiso», siga usando `permission_required`. Un
  rol nuevo con ese permiso debe funcionar sin tocar la vista.
- Use un decorador de rol cuando la pantalla **es de ese rol**, no cuando lo que
  quiere es un permiso con otro nombre. Si al añadir un rol tendría que editar
  la vista, el criterio correcto era el permiso.
- Se pueden apilar con `permission_required`: entonces hacen falta las dos
  cosas.

**Comportamiento:**

- Sin sesión, redirige al acceso, como `login_required`.
- Con sesión y rol insuficiente, responde 403 y **deja constancia**: los
  intentos denegados son la mejor señal de un sondeo o de un permiso mal puesto.
- `is_superuser` pasa siempre, salvo que se pida lo contrario: es la misma regla
  que ya aplica `has_perm` en todo Django.

Ver docs/security/10-autorizacion.md §J.6.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from apps.accounts.constants import Role

__all__ = [
    "has_role",
    "is_admin",
    "is_auditor",
    "is_employee",
    "is_hr",
    "is_manager",
    "is_superadmin",
    "role_required",
]


def has_role(user, *roles: str, allow_superuser: bool = True) -> bool:
    """Si el usuario tiene **alguno** de esos roles. Sin efectos secundarios.

    Sirve también en plantillas a través del contexto, o dentro de una vista
    cuando la decisión no es «entra o no entra», sino qué mostrar.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if allow_superuser and user.is_superuser:
        return True
    return bool(set(user.groups.values_list("name", flat=True)) & set(roles))


def role_required(
    *roles: str, allow_superuser: bool = True
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """Exige **alguno** de los roles indicados.

    Es la base de los decoradores con nombre. Se usa directamente cuando la
    combinación no tiene un nombre propio:

        @role_required(Role.SUPERADMIN, Role.AUDITOR)
        def audit_console(request): ...

    Nótese que el ejemplo **no** incluye `HR_ADMIN`: quien opera el sistema no
    revisa la bitácora que lo vigila (§J.2).
    """
    required: tuple[str, ...] = tuple(roles)

    def decorator(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view)
        @login_required
        def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if has_role(request.user, *required, allow_superuser=allow_superuser):
                return view(request, *args, **kwargs)
            _record_denial(request, required)
            raise PermissionDenied

        return wrapper

    return decorator


def _record_denial(request: HttpRequest, roles: Iterable[str]) -> None:
    """Deja constancia del intento. Importar aquí evita un ciclo con `services`."""
    from apps.accounts.services import record_permission_denied

    record_permission_denied(request=request, detail=f"role_required: {','.join(sorted(roles))}")


#: Administración del sistema: solo quien lo administra de verdad.
is_superadmin = role_required(Role.SUPERADMIN)

#: Administración de RRHH: quien responde por los datos de personal.
is_admin = role_required(Role.SUPERADMIN, Role.HR_ADMIN)

#: Cualquier perfil de RRHH, incluida la analista.
is_hr = role_required(Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER)

#: Jefatura de departamento. RRHH entra también, porque su alcance es toda la
#: organización: una pantalla «de jefatura» que RRHH no pudiera abrir sería una
#: excepción al modelo de alcance, no una regla de rol.
is_manager = role_required(Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER, Role.MANAGER)

#: Cualquier persona con ficha: pantallas de autoservicio.
is_employee = role_required(
    Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER, Role.MANAGER, Role.EMPLOYEE
)

#: Auditoría. **No** entra ningún rol de escritura: son incompatibles (§J.1).
is_auditor = role_required(Role.AUDITOR)
