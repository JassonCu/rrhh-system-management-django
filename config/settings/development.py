"""Entorno de desarrollo local.

Relaja lo que sería inviable en local (HTTPS, HSTS) y **nada más**. Las
protecciones que no molestan (nosniff, X-Frame-Options, CSP) siguen activas para
que los problemas se vean aquí y no en producción.
"""

from .base import *
from .base import BASE_DIR, INSTALLED_APPS, MIDDLEWARE, env_list

DEBUG = True

# Clave de descarte: solo sirve en local y nunca sale de esta máquina.
SECRET_KEY = "django-insecure-development-only-do-not-use-anywhere-else"  # noqa: S105

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1", "[::1]"])

# El correo se imprime en consola: sin credenciales ni envíos accidentales.
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}}

# La CSP pasó a modo BLOQUEO al cerrar la Fase 2 (ADR-007). Durante las Fases 1-2
# estuvo en modo informe mientras el conjunto de plantillas se estabilizaba; ya
# no hace falta, y dejarla en modo informe habría sido no tener CSP.
# `CONTENT_SECURITY_POLICY` se hereda de `base` sin cambios.

INTERNAL_IPS = ["127.0.0.1"]

try:
    import debug_toolbar  # noqa: F401

    INSTALLED_APPS = [*INSTALLED_APPS, "debug_toolbar"]
    MIDDLEWARE = [
        "debug_toolbar.middleware.DebugToolbarMiddleware",
        *MIDDLEWARE,
    ]
except ImportError:  # pragma: no cover - la toolbar es opcional
    pass

# Herramientas de desarrollo: el comando `seed_demo` vive en esta app, que en
# producción **no se instala**. Así el comando no existe fuera de desarrollo.
INSTALLED_APPS = [*INSTALLED_APPS, "apps.demo"]

MEDIA_ROOT = BASE_DIR / "media"
