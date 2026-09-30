"""Crea la primera cuenta de administración del sistema.

`createsuperuser` no sirve para empezar: no registra el correo en allauth, y con
la verificación obligatoria esa cuenta **no puede iniciar sesión**. Este comando
crea el superusuario con su correo verificado y el rol SUPERADMIN, y lo audita.

Solo arranca un sistema vacío: si ya hay un superusuario activo se niega, porque
el resto de cuentas se crean por invitación (ADR-004).

La contraseña **nunca** se acepta como argumento (quedaría en el historial de la
shell). En modo interactivo se pide con `getpass`; con `--noinput` se lee de
`DJANGO_SUPERUSER_PASSWORD`, igual que en `createsuperuser`.
"""

from __future__ import annotations

import os
from getpass import getpass
from typing import Any

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.core.validators import validate_email
from django.db import transaction

from apps.accounts.constants import Role
from apps.audit.constants import AuditAction
from apps.audit.services import record

EMAIL_ENV = "DJANGO_SUPERUSER_EMAIL"
# Nombre de la variable de entorno, no un secreto.
PASSWORD_ENV = "DJANGO_SUPERUSER_PASSWORD"  # noqa: S105  # pragma: allowlist secret


class Command(BaseCommand):
    help = "Crea el primer superusuario con correo verificado y rol SUPERADMIN."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--email", help="Correo de la cuenta (si no, se pregunta).")
        parser.add_argument(
            "--noinput",
            action="store_true",
            help=f"No pregunta nada: usa --email o {EMAIL_ENV}, y {PASSWORD_ENV}.",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        user_model = get_user_model()
        if user_model.objects.filter(is_superuser=True, is_active=True).exists():
            raise CommandError(
                "Ya existe un superusuario activo. Las demás cuentas se crean por "
                "invitación desde la aplicación (ADR-004)."
            )

        interactive = not options["noinput"]
        email = self._read_email(options.get("email"), interactive=interactive)
        if user_model.objects.filter(email=email).exists():
            raise CommandError(f"Ya existe una cuenta con el correo {email}.")

        password = self._read_password(user_model(email=email), interactive=interactive)

        try:
            group = Group.objects.get(name=Role.SUPERADMIN)
        except Group.DoesNotExist as error:
            raise CommandError(
                "No existe el grupo SUPERADMIN. "
                "Ejecute `manage.py migrate` o `manage.py sync_roles`."
            ) from error

        with transaction.atomic():
            user = user_model.objects.create_superuser(email=email, password=password)
            EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
            user.groups.add(group)
            record(
                action=AuditAction.USER_CREATE,
                actor=None,
                actor_repr="manage.py bootstrap_admin",
                obj=user,
                metadata={
                    "email": email,
                    "roles": [Role.SUPERADMIN.value],
                    "via": "bootstrap_admin",
                },
            )

        self.stdout.write(
            self.style.SUCCESS(f"Superusuario {email} creado. Ya puede iniciar sesión.")
        )

    def _read_email(self, given: str | None, *, interactive: bool) -> str:
        email = given or os.environ.get(EMAIL_ENV, "")
        if not email and interactive:
            email = input("Correo electrónico: ")
        email = email.strip().lower()
        if not email:
            raise CommandError(f"Falta el correo: use --email o {EMAIL_ENV}.")
        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError(f"Correo no válido: {email}") from error
        return email

    def _read_password(self, candidate, *, interactive: bool) -> str:
        if interactive:
            password = getpass("Contraseña: ")
            if password != getpass("Repita la contraseña: "):
                raise CommandError("Las contraseñas no coinciden.")
        else:
            password = os.environ.get(PASSWORD_ENV, "")
            if not password:
                raise CommandError(f"Con --noinput, la contraseña se lee de {PASSWORD_ENV}.")
        try:
            validate_password(password, user=candidate)
        except ValidationError as error:
            raise CommandError("Contraseña rechazada: " + " ".join(error.messages)) from error
        return password
