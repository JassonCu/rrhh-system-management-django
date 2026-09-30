"""Entorno de producción.

Todo valor sensible es obligatorio: si falta, el proceso **no arranca**. Es
preferible un fallo ruidoso en el despliegue a un servicio en pie con una clave
por defecto.
"""

from .base import *
from .base import env, env_bool, env_int, env_list

DEBUG = False

SECRET_KEY = env("SECRET_KEY")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

if not ALLOWED_HOSTS:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("ALLOWED_HOSTS no puede estar vacío en producción.")

# --- HTTPS ---------------------------------------------------------------- #
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31_536_000)  # 1 año
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Solo con un proxy de confianza delante: configurarlo sin él permitiría
# falsificar request.is_secure() con una cabecera.
if env_bool("BEHIND_TRUSTED_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Correo --------------------------------------------------------------- #
# Los enlaces de invitación y restablecimiento deben ir por HTTPS: un enlace
# http en un correo es una credencial viajando en claro.
ACCOUNT_DEFAULT_HTTP_PROTOCOL = "https"

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
        "OPTIONS": {
            "host": env("EMAIL_HOST"),
            "port": env_int("EMAIL_PORT", 587),
            "username": env("EMAIL_HOST_USER", ""),
            "password": env("EMAIL_HOST_PASSWORD", ""),
            "use_tls": env_bool("EMAIL_USE_TLS", True),
            "timeout": env_int("EMAIL_TIMEOUT", 10),
        },
    }
}

ADMINS = [("RRHH Ops", email) for email in env_list("ADMIN_EMAILS")]

LOGGING["handlers"]["console"]["formatter"] = "verbose"
LOGGING["root"]["level"] = "WARNING"
