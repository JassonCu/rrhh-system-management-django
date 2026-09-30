"""Identidad de acceso.

``User`` es **solo** una credencial: no contiene datos de recursos humanos. La
identidad civil vive en ``employees.Person`` y la laboral en
``employees.Employee``, que se añaden en la Fase 3. Acoplarlos obligaría a crear
cuentas fantasma para el personal sin acceso al sistema y ampliaría la superficie
de ataque (§A.2.6).

Ver docs/database/06-diccionario-de-datos.md §G.3.
"""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounts.managers import UserManager
from apps.core.constants import default_language, language_choices
from apps.core.models import TimeStampedModel


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """Cuenta de acceso al sistema.

    Se define desde la Fase 1 aunque la autenticación llegue en la Fase 2:
    sustituir el modelo de usuario después de la primera migración es
    notoriamente costoso.
    """

    email = models.EmailField(
        _("email address"),
        max_length=254,
        unique=True,
        help_text=_("Used as the login identifier. Stored in lowercase."),
        error_messages={"unique": _("An account with that email address already exists.")},
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Deactivate instead of deleting, so the audit trail survives."),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Grants access to the Django admin. Reserved for SUPERADMIN."),
    )
    must_change_password = models.BooleanField(
        _("must change password"),
        default=False,
        help_text=_("Forces a password change on the next sign-in."),
    )
    language = models.CharField(
        _("preferred language"),
        max_length=10,
        choices=language_choices,
        default=default_language,
        help_text=_("Interface language. Follows the person across devices."),
    )
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ("email",)
        permissions = [("manage_users", _("Can invite and deactivate accounts"))]

    def __str__(self) -> str:
        # Sin traducir: se usa en logs y en AuditEvent.actor_repr.
        return self.email

    def save(self, *args: object, **kwargs: object) -> None:
        # La unicidad del correo debe ser insensible a mayúsculas. Al normalizar
        # aquí, el UNIQUE de la base es suficiente y no hace falta un índice
        # funcional que SQLite y PostgreSQL expresan de forma distinta.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    def get_short_name(self) -> str:
        return self.email.split("@")[0]

    def get_full_name(self) -> str:
        """El nombre real vive en ``employees.Person`` (Fase 3).

        Django espera este método; devolver el correo evita duplicar la identidad
        civil en dos tablas sin una fuente de verdad clara (§C.3).
        """
        return self.email
