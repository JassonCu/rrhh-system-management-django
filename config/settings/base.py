"""Configuración común a todos los entornos.

Reglas de este módulo:

* **Nunca** contiene secretos. Todo valor sensible se lee del entorno.
* Los valores por defecto son los **seguros**; los entornos relajan, no endurecen.
* No importa nada de ``apps.*`` (las apps aún no están cargadas).

Ver ``docs/architecture/08-arquitectura-django.md`` §H.7.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# Lectura del entorno
# --------------------------------------------------------------------------- #
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - python-dotenv es opcional en producción
    pass

_UNSET = object()


def env(name: str, default: object = _UNSET) -> str:
    """Devuelve una variable de entorno; falla ruidosamente si es obligatoria."""
    value = os.environ.get(name, default)
    if value is _UNSET:
        raise ImproperlyConfigured(f"Falta la variable de entorno obligatoria: {name}")
    return value  # type: ignore[return-value]


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


# --------------------------------------------------------------------------- #
# Núcleo
# --------------------------------------------------------------------------- #
SECRET_KEY = os.environ.get("SECRET_KEY")  # cada entorno decide si es obligatoria
DEBUG = False
ALLOWED_HOSTS: list[str] = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS: list[str] = env_list("CSRF_TRUSTED_ORIGINS")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Autenticación (ADR-004). NO se instala allauth.socialaccount: sería
    # superficie de ataque sin uso hasta que exista un IdP (ADR-017).
    "allauth",
    "allauth.account",
    # Dominio (monolito modular) — ver docs/architecture/01-analisis-de-dominio.md §A.1
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.departments",
    "apps.positions",
    "apps.employees",
    "apps.contracts",
    "apps.attendance",
    "apps.leave",
    "apps.documents",
    "apps.reports",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # LocaleMiddleware necesita la sesión y debe preceder a CommonMiddleware.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.core.middleware.RequestIDMiddleware",
    "apps.accounts.middleware.MustChangePasswordMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.i18n",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.brand",
            ],
        },
    },
]


# --------------------------------------------------------------------------- #
# Base de datos
#
# SQLite por defecto; DATABASE_URL permite apuntar a PostgreSQL sin tocar código
# (ADR-002 / ADR-003). Se evita una dependencia extra parseando la URL aquí.
# --------------------------------------------------------------------------- #
def _database_from_url(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username or "",
            "PASSWORD": parsed.password or "",
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or ""),
            "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
            "ATOMIC_REQUESTS": False,
        }
    if parsed.scheme == "sqlite":
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": parsed.path.lstrip("/")}
    raise ImproperlyConfigured(f"Esquema de DATABASE_URL no soportado: {parsed.scheme}")


_database_url = os.environ.get("DATABASE_URL")
DATABASES = {
    "default": (
        _database_from_url(_database_url)
        if _database_url
        else {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                # Integridad referencial activa: sin esto SQLite ignora las FK y
                # las políticas PROTECT/CASCADE del diseño no se aplicarían.
                "init_command": "PRAGMA foreign_keys=ON;",
            },
        }
    )
}

# --------------------------------------------------------------------------- #
# Autenticación
# --------------------------------------------------------------------------- #
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},  # por encima del 8 por defecto
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "/"

# Marca del producto (docs/ux/16-identidad-de-marca.md). No se traduce.
PRODUCT_NAME = "Ceiba RH"
LOGOUT_REDIRECT_URL = "/"

# --------------------------------------------------------------------------- #
# django-allauth  (ADR-004, docs/security/09-autenticacion.md)
#
# El registro público está CERRADO por dos mecanismos redundantes: este adaptador
# y la retirada de la ruta en config/urls.py. Ninguno basta solo.
# --------------------------------------------------------------------------- #
ACCOUNT_ADAPTER = "apps.accounts.adapters.NoPublicSignupAdapter"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# Nuestro modelo de usuario no tiene `username` (se descartó por ser un dato sin
# valor de dominio, §B.2). Sin declararlo, allauth lo busca igualmente y falla.
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_USER_MODEL_EMAIL_FIELD = "email"
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_PREVENT_ENUMERATION = True  # no revela si un correo existe

# Un GET no puede cerrar sesión: sería un CSRF de logout trivial.
ACCOUNT_LOGOUT_ON_GET = False
# Cambiar la contraseña invalida las demás sesiones.
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True
# Sesión de RRHH: no se recuerda por defecto en equipos compartidos.
ACCOUNT_SESSION_REMEMBER = False

ACCOUNT_EMAIL_SUBJECT_PREFIX = "[Ceiba RH] "
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "http"  # producción lo eleva a https

# Límites de tasa: fuerza bruta y abuso del envío de correo.
ACCOUNT_RATE_LIMITS = {
    "login_failed": "5/5m/key,20/5m/ip",
    "reset_password": "5/h/ip,3/h/key",
    "reset_password_from_key": "20/m/ip",
    "confirm_email": "3/h/key",
    "change_password": "5/m/user",
}

# --------------------------------------------------------------------------- #
# Sesiones y cookies  (§K.1)
# --------------------------------------------------------------------------- #
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "rrhh_sessionid"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8  # una jornada laboral
SESSION_COOKIE_SECURE = False  # producción lo activa
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

CSRF_COOKIE_NAME = "rrhh_csrftoken"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = False  # producción lo activa
# CSRF_COOKIE_HTTPONLY se deja en False a propósito: el JS necesita leer el token.
# La protección real la dan SameSite y la validación en el servidor.
CSRF_COOKIE_HTTPONLY = False

# --------------------------------------------------------------------------- #
# Cabeceras de seguridad  (§K.1)
# --------------------------------------------------------------------------- #
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = False
# Solo con un proxy de confianza delante se lee X-Forwarded-For para registrar la
# IP del cliente en la auditoría; sin él, cualquiera podría falsificarla.
TRUST_PROXY_HEADERS = env_bool("BEHIND_TRUSTED_PROXY", False)
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Límites anti-DoS de formularios y subidas
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_621_440  # 2.5 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1_000
FILE_UPLOAD_PERMISSIONS = 0o600

# --------------------------------------------------------------------------- #
# Content Security Policy  (ADR-007, §K.2)
#
# Política estricta: sin unsafe-inline ni unsafe-eval. El nonce por petición lo
# genera django-csp y se consume en las plantillas con {{ request.csp_nonce }}.
# --------------------------------------------------------------------------- #
from csp.constants import NONCE, NONE, SELF  # noqa: E402

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        "script-src": [SELF, NONCE],
        "style-src": [SELF, NONCE],
        "img-src": [SELF, "data:"],
        "font-src": [SELF],
        "connect-src": [SELF],
        "form-action": [SELF],  # impide que un XSS reenvíe el formulario fuera
        "frame-ancestors": [NONE],
        "base-uri": [NONE],
        "object-src": [NONE],
        "frame-src": [NONE],
    }
}

# --------------------------------------------------------------------------- #
# Internacionalización  (ADR-018, docs/architecture/14-internacionalizacion.md)
# --------------------------------------------------------------------------- #
LANGUAGE_CODE = "es-gt"
LANGUAGES = [
    ("es-gt", _("Spanish (Guatemala)")),
    ("en", _("English")),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_I18N = True
USE_THOUSAND_SEPARATOR = True
# Sin este módulo, el catálogo «es» de Django formatearía 1500 como «1.500,00»
# (convención de España) en lugar de «1,500.00». Ver §O.2.2.
FORMAT_MODULE_PATH = ["config.formats"]

TIME_ZONE = "America/Guatemala"
USE_TZ = True  # almacenamiento en UTC

# --------------------------------------------------------------------------- #
# Archivos estáticos y media
# --------------------------------------------------------------------------- #
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# MEDIA_ROOT queda fuera del árbol servido: los documentos se entregan siempre a
# través de una vista que autoriza primero (§K.4).
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# --------------------------------------------------------------------------- #
# Correo
# --------------------------------------------------------------------------- #
# Django 6.1 dejó obsoleto el bloque EMAIL_* en favor de MAILERS, que se elimina
# en Django 7.0. Se adopta ya el ajuste nuevo para no acumular deuda desde el
# primer commit. Cada entorno define su propio mailer «default».
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@example.com")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
MAILERS: dict[str, dict[str, object]] = {
    "default": {"BACKEND": "django.core.mail.backends.console.EmailBackend"}
}

# --------------------------------------------------------------------------- #
# Logging  (§K.5)
#
# El filtro de redacción es obligatorio en todos los handlers: ninguna
# contraseña, token ni cookie puede llegar a un archivo de log.
# --------------------------------------------------------------------------- #
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_sensitive": {"()": "apps.core.logging.SensitiveDataFilter"},
        "request_id": {"()": "apps.core.logging.RequestIDFilter"},
    },
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name} req={request_id} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            "filters": ["redact_sensitive", "request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# --------------------------------------------------------------------------- #
# Relación laboral (Fase 4)
# --------------------------------------------------------------------------- #
# RN-22: salario mínimo mensual en GTQ. `None` desactiva la comprobación.
# NO se fija un importe en el código: el mínimo legal cambia por acuerdo
# gubernativo y por actividad económica, y una cifra desactualizada bloquearía
# contratos legítimos o dejaría pasar ilegales sin que nadie lo notara.
_minimum_salary = os.environ.get("MINIMUM_MONTHLY_SALARY")
CONTRACTS_MINIMUM_MONTHLY_SALARY = Decimal(_minimum_salary) if _minimum_salary else None
