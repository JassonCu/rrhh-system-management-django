"""Manager del modelo de usuario."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:  # pragma: no cover
    from apps.accounts.models import User


class UserManager(BaseUserManager):
    """Crea usuarios identificados por correo, sin ``username``."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError(_("An email address is required."))
        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, **extra)
        # set_password aplica el hasher configurado (Argon2). Nunca se almacena
        # ni se registra la contraseña en claro.
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("is_active", True)
        if extra.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))
        return self._create_user(email, password, **extra)
