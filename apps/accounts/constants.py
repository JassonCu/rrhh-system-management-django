"""Constantes públicas de `accounts`.

Este módulo es **interfaz pública**: otras apps lo consultan para decidir
alcance de autorización. La política de qué permisos lleva cada rol vive en
``roles.py``, que es interno y nadie más debe importar (§H.4).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    """Nombres de los grupos. El **valor** es la clave y no se traduce."""

    SUPERADMIN = "SUPERADMIN", _("System administrator")
    HR_ADMIN = "HR_ADMIN", _("HR administrator")
    HR_MANAGER = "HR_MANAGER", _("HR analyst")
    MANAGER = "MANAGER", _("Department head")
    EMPLOYEE = "EMPLOYEE", _("Employee")
    AUDITOR = "AUDITOR", _("Auditor")
