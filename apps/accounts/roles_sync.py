"""Aplicación de la declaración de roles sobre la base de datos.

Separado de ``signals.py`` para poder probarlo y ejecutarlo a mano
(``manage.py sync_roles``) sin depender de una migración.
"""

from __future__ import annotations

import logging

from django.contrib.auth.models import Group, Permission

logger = logging.getLogger(__name__)


def resolve_permissions(
    codenames: tuple[str, ...] | list[str],
) -> tuple[list[Permission], list[str]]:
    """Traduce ``"app_label.codename"`` a objetos ``Permission``.

    Devuelve también los que no existen, en lugar de fallar: al añadir una app en
    una fase posterior, sus permisos aparecerán en el siguiente `migrate`, y
    mientras tanto un rol declarado de más no debe impedir el arranque.
    """
    resolved: list[Permission] = []
    missing: list[str] = []
    for dotted in codenames:
        app_label, _, codename = dotted.partition(".")
        permission = Permission.objects.filter(
            content_type__app_label=app_label, codename=codename
        ).first()
        if permission is None:
            missing.append(dotted)
        else:
            resolved.append(permission)
    return resolved, missing


def _record_permission_change(role: str, *, before: set[int], after: set[int]) -> None:
    """Deja constancia de que un rol cambió de permisos.

    Ocurre en un despliegue, no por acción de una persona, y precisamente por
    eso conviene que quede: «¿desde cuándo RRHH puede archivar documentos?» es
    una pregunta que alguien va a hacer.
    """
    from apps.audit.constants import AuditAction
    from apps.audit.services import record

    record(
        action=AuditAction.PERMISSION_CHANGE,
        actor=None,
        request=None,
        metadata={
            "role": role,
            "granted": len(after - before),
            "revoked": len(before - after),
            "total": len(after),
        },
    )


def apply_roles(role_permissions: dict[str, tuple[str, ...]]) -> tuple[int, int]:
    """Crea los grupos que falten y fija sus permisos. Idempotente.

    Usa ``set()``, no ``add()``: así **retirar** un permiso de la declaración lo
    retira también de la base. Una declaración que solo sabe añadir no es una
    fuente de verdad.
    """
    created_count = 0
    updated_count = 0

    for role, codenames in role_permissions.items():
        group, created = Group.objects.get_or_create(name=role)
        created_count += int(created)

        permissions, missing = resolve_permissions(codenames)
        if missing:
            # `debug` y no `warning`: durante `migrate` esta función se ejecuta
            # varias veces, y en las primeras pasadas faltan permisos de apps que
            # aún no han creado los suyos. Una errata real la detecta
            # `test_declared_permissions_all_exist`, no un log.
            logger.debug("Rol %s: permisos aún inexistentes %s", role, missing)

        current = set(group.permissions.values_list("pk", flat=True))
        desired = {permission.pk for permission in permissions}
        if current != desired:
            group.permissions.set(permissions)
            updated_count += 1
            _record_permission_change(role, before=current, after=desired)

    return created_count, updated_count
