"""Entorno de pruebas.

El hasher rápido está **prohibido en cualquier otro entorno**: MD5 se usa aquí
solo para que la suite no gaste segundos derivando Argon2 en cada fixture.
"""

import os

from .base import *

DEBUG = False

SECRET_KEY = "testing-only-not-a-real-secret"  # noqa: S105

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}

# Sin latencia de red ni de disco durante las pruebas... salvo que el entorno
# apunte explícitamente a otro motor. El job de PostgreSQL del CI existe para
# detectar divergencias entre motores (ADR-003); si esta línea sobrescribiera
# DATABASES sin condición, ese job correría en SQLite y no probaría nada.
if not os.environ.get("DATABASE_URL"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
            "OPTIONS": {"init_command": "PRAGMA foreign_keys=ON;"},
        }
    }

LANGUAGE_CODE = "es-gt"

# Silencia el ruido de logs durante la suite sin desactivar el filtro de
# redacción, que tiene pruebas propias.
LOGGING["root"]["level"] = "CRITICAL"

# La app de herramientas se instala también aquí para poder **probar** su
# comando de datos de demostración. El comando sigue negándose a ejecutarse con
# `DEBUG = False`, que es como corre la suite salvo en la prueba que lo activa.
INSTALLED_APPS = [*INSTALLED_APPS, "apps.demo"]
