"""Ajustes que son decisiones, no preferencias.

Cada aserción de este módulo respalda un ADR: si alguien cambia el ajuste, la
prueba obliga a pasar por la decisión en lugar de hacerlo de paso.
"""

from __future__ import annotations

import importlib

import pytest
from django.conf import settings

base = importlib.import_module("config.settings.base")


# --- ADR-013: Argon2 como hasher de contraseñas -------------------------- #


@pytest.mark.security
def test_argon2_is_the_primary_hasher() -> None:
    assert base.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")


@pytest.mark.security
def test_argon2_is_actually_installed(settings) -> None:
    """El hasher configurado debe poder cargarse, no solo estar escrito.

    Se activa la lista de `base` porque el entorno de pruebas usa MD5 a
    propósito: sin esta prueba, un `argon2-cffi` ausente pasaría inadvertido
    hasta el primer despliegue.
    """
    from django.contrib.auth.hashers import get_hasher

    settings.PASSWORD_HASHERS = base.PASSWORD_HASHERS
    hasher = get_hasher("argon2")
    assert hasher.algorithm == "argon2"


@pytest.mark.security
def test_fallback_hashers_allow_transparent_rehashing() -> None:
    """PBKDF2 detrás permite migrar hashes antiguos sin pedir contraseña nueva."""
    assert any("PBKDF2PasswordHasher" in path for path in base.PASSWORD_HASHERS)


@pytest.mark.security
def test_minimum_password_length_is_twelve() -> None:
    validators = {v["NAME"]: v.get("OPTIONS", {}) for v in base.AUTH_PASSWORD_VALIDATORS}
    minimum = validators["django.contrib.auth.password_validation.MinimumLengthValidator"]
    assert minimum["min_length"] == 12


@pytest.mark.security
def test_fast_hasher_is_confined_to_the_test_environment() -> None:
    """MD5 acelera la suite; verlo fuera de `testing` sería un incidente."""
    assert settings.PASSWORD_HASHERS == ["django.contrib.auth.hashers.MD5PasswordHasher"]
    assert "MD5" not in " ".join(base.PASSWORD_HASHERS)


# --- ADR-007: CSP estricta ----------------------------------------------- #


@pytest.mark.security
def test_csp_has_no_unsafe_sources() -> None:
    directives = base.CONTENT_SECURITY_POLICY["DIRECTIVES"]
    flattened = " ".join(str(value) for values in directives.values() for value in values)
    assert "unsafe-inline" not in flattened
    assert "unsafe-eval" not in flattened


@pytest.mark.security
@pytest.mark.parametrize(
    "directive",
    ["default-src", "script-src", "style-src", "form-action", "frame-ancestors", "base-uri"],
)
def test_csp_declares_the_critical_directives(directive: str) -> None:
    assert directive in base.CONTENT_SECURITY_POLICY["DIRECTIVES"]


# --- ADR-002 / ADR-003: SQLite hoy, PostgreSQL después ------------------- #


@pytest.mark.unit
def test_sqlite_enforces_foreign_keys() -> None:
    """Sin este PRAGMA, SQLite ignora las FK y PROTECT/CASCADE no se aplican."""
    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite" not in engine:
        pytest.skip("solo aplica al motor SQLite")
    options = settings.DATABASES["default"].get("OPTIONS", {})
    assert "foreign_keys=ON" in options.get("init_command", "").replace(" ", "")


@pytest.mark.unit
def test_database_url_supports_postgresql() -> None:
    config = base._database_from_url("postgres://u:p@localhost:5432/rrhh")
    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["NAME"] == "rrhh"
    assert config["USER"] == "u"
    assert config["HOST"] == "localhost"
    assert config["PORT"] == "5432"


@pytest.mark.unit
def test_unsupported_database_scheme_fails_loudly() -> None:
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured):
        base._database_from_url("mysql://u:p@localhost/rrhh")


# --- ADR-018: internacionalización --------------------------------------- #


@pytest.mark.unit
def test_localized_formats_module_is_configured() -> None:
    """Sin esto, los importes se mostrarían con la coma decimal de España."""
    assert "config.formats" in base.FORMAT_MODULE_PATH


@pytest.mark.unit
def test_timezone_support_is_enabled() -> None:
    assert base.USE_TZ is True
    assert base.USE_I18N is True
    assert base.TIME_ZONE == "America/Guatemala"


@pytest.mark.unit
def test_supported_languages_are_limited_to_what_is_maintained() -> None:
    codes = {code for code, _name in base.LANGUAGES}
    assert codes == {"es-gt", "en"}
    assert base.LANGUAGE_CODE == "es-gt"


@pytest.mark.unit
def test_locale_middleware_sits_between_session_and_common() -> None:
    """Necesita la sesión para resolver el idioma, y CommonMiddleware depende de él."""
    order = base.MIDDLEWARE
    session = order.index("django.contrib.sessions.middleware.SessionMiddleware")
    locale = order.index("django.middleware.locale.LocaleMiddleware")
    common = order.index("django.middleware.common.CommonMiddleware")
    assert session < locale < common


# --- Ajustes de seguridad transversales ---------------------------------- #


@pytest.mark.security
def test_session_cookie_is_not_readable_from_javascript() -> None:
    assert base.SESSION_COOKIE_HTTPONLY is True
    assert base.SESSION_COOKIE_SAMESITE == "Lax"


@pytest.mark.security
def test_media_is_not_served_by_the_application() -> None:
    """Los documentos se entregan desde una vista que autoriza primero (§K.4)."""
    from config import urls

    assert not any(
        str(getattr(pattern, "pattern", "")).startswith("media") for pattern in urls.urlpatterns
    )


# --- ADR-004: alta de cuentas -------------------------------------------- #


@pytest.mark.security
def test_signup_adapter_is_the_restrictive_one() -> None:
    assert base.ACCOUNT_ADAPTER == "apps.accounts.adapters.NoPublicSignupAdapter"


@pytest.mark.security
def test_email_verification_is_mandatory() -> None:
    assert base.ACCOUNT_EMAIL_VERIFICATION == "mandatory"


@pytest.mark.security
def test_user_enumeration_is_prevented() -> None:
    assert base.ACCOUNT_PREVENT_ENUMERATION is True


@pytest.mark.security
def test_logout_requires_post() -> None:
    """Con `LOGOUT_ON_GET`, un `<img src=.../logout/>` cerraría la sesión."""
    assert base.ACCOUNT_LOGOUT_ON_GET is False


@pytest.mark.security
def test_password_change_invalidates_sessions() -> None:
    assert base.ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE is True


@pytest.mark.security
def test_allauth_knows_the_user_model_has_no_username() -> None:
    assert base.ACCOUNT_USER_MODEL_USERNAME_FIELD is None


@pytest.mark.security
def test_production_sends_https_links_in_emails() -> None:
    """Un enlace `http` en un correo de invitación viaja en claro."""
    import importlib
    import os

    os.environ.setdefault("SECRET_KEY", "x" * 80)
    os.environ.setdefault("ALLOWED_HOSTS", "rrhh.example.com")
    os.environ.setdefault("EMAIL_HOST", "smtp.example.com")
    production = importlib.import_module("config.settings.production")

    assert production.ACCOUNT_DEFAULT_HTTP_PROTOCOL == "https"
    assert production.SESSION_COOKIE_SECURE is True
    assert production.CSRF_COOKIE_SECURE is True
    assert production.SECURE_HSTS_SECONDS >= 31_536_000
