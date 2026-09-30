"""Consultas de lectura con alcance de autorización (ADR-005).

Toda vista que acceda a cuentas parte de aquí. Ninguna hace
``User.objects.get(pk=...)`` con un identificador de la URL: el filtro se aplica
**antes** de la búsqueda, de modo que cambiar el número en la URL no amplía el
conjunto visible (§J.4).
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404

from apps.accounts.roles import Role

User = get_user_model()


def users_visible_for(user) -> QuerySet:
    """Cuentas que este usuario puede ver.

    En la Fase 2 el alcance es sencillo porque todavía no existen departamentos
    ni empleados: RRHH y auditoría ven todas las cuentas, y el resto solo la
    suya. En la Fase 3, cuando exista la jefatura, se ampliará con el alcance
    departamental.
    """
    if not user.is_authenticated:
        return User.objects.none()
    if user.is_superuser:
        return User.objects.all()

    roles = set(user.groups.values_list("name", flat=True))
    if roles & {Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER, Role.AUDITOR}:
        return User.objects.all()
    return User.objects.filter(pk=user.pk)


def get_user_or_404(actor, *, pk: int):
    """Obtiene una cuenta **dentro del alcance** del actor.

    Fuera de alcance devuelve 404 y no 403: un 403 confirmaría que la cuenta
    existe.
    """
    return get_object_or_404(users_visible_for(actor), pk=pk)
