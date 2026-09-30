"""Criterio de cierre de la Fase 2.

**Ninguna URL del proyecto es accesible sin autenticación salvo las de acceso.**

La prueba recorre la tabla de URLs completa, no una muestra: añadir una vista
nueva sin protegerla —o sin declararla conscientemente como pública— hace fallar
la suite. Esa es la diferencia entre una regla documentada y una garantizada.
"""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import NoReverseMatch, get_resolver, reverse

#: Rutas accesibles sin sesión, **una por una y con su motivo**. Esta lista es la
#: superficie anónima del sistema: cada entrada nueva es una decisión de
#: seguridad que alguien debe justificar en la revisión del PR.
PUBLIC_URL_NAMES: dict[str, str] = {
    "account_login": "pantalla de acceso",
    "account_logout": "cerrar sesión debe funcionar aunque la sesión haya expirado",
    "account_signup_closed": "responde 404: el registro público no existe (ADR-004)",
    "account_inactive": "informa de que la cuenta está desactivada",
    "account_reset_password": "recuperar el acceso exige no tener sesión",
    "account_reset_password_done": "confirmación del envío",
    "account_reset_password_from_key": "el enlace del correo llega sin sesión",
    "account_reset_password_from_key_done": "confirmación del cambio",
    "account_confirm_email": "el enlace de verificación llega sin sesión",
    "account_email_verification_sent": "confirmación del envío",
    "account_confirm_login_code": "acceso por código, sin sesión previa",
    "account_signup": "la ruta la intercepta `signup_closed` y responde 404 (ADR-004)",
    "set_language": "cambiar de idioma antes de entrar",
}

#: El admin de Django trae su propia autenticación y no es el CRUD del negocio;
#: sus vistas quedan fuera del alcance de esta comprobación.
IGNORED_NAMESPACES = frozenset({"admin"})

#: Argumentos de relleno para las rutas con parámetros. Se prueban igual que las
#: demás: una vista con parámetro es justamente donde vive el riesgo de IDOR.
#: El UUID es imprescindible: las rutas de empleados usan `public_id` y sin él
#: quedaban fuera de la comprobación sin que nada fallara.
_SAMPLE_UUID = "00000000-0000-4000-8000-000000000000"
FALLBACK_ARGS: tuple[tuple, ...] = (
    (),
    (1,),
    (_SAMPLE_UUID,),
    (_SAMPLE_UUID, 1),
    (1, 1),
    ("a",),
    ("a", "b"),
    ("abc", "def-ghi"),
)


def collect_named_urls() -> list[str]:
    """Nombres de **todas** las URLs del proyecto, con su espacio de nombres.

    Se lee del `reverse_dict` del resolvedor y no recorriendo los patrones: así
    los nombres llegan ya cualificados (`accounts:profile`). Recorrer patrones a
    mano perdía el espacio de nombres y hacía que las vistas de `accounts` se
    saltaran en silencio.
    """
    resolver = get_resolver()
    names = [name for name in resolver.reverse_dict if isinstance(name, str)]
    for namespace, (_prefix, sub_resolver) in resolver.namespace_dict.items():
        if namespace in IGNORED_NAMESPACES:
            continue
        names += [
            f"{namespace}:{name}" for name in sub_resolver.reverse_dict if isinstance(name, str)
        ]
    return sorted(set(names))


ALL_NAMED_URLS = collect_named_urls()
PROTECTED_URLS = [
    name for name in ALL_NAMED_URLS if name.rsplit(":", 1)[-1] not in PUBLIC_URL_NAMES
]


def _reverse_or_none(name: str) -> str | None:
    """Resuelve la URL probando varias formas de argumento."""
    for args in FALLBACK_ARGS:
        try:
            return reverse(name, args=args)
        except NoReverseMatch:
            continue
    return None


@pytest.mark.security
def test_the_url_table_is_not_empty() -> None:
    """Si esta prueba falla, las demás estarían pasando en vacío."""
    assert len(ALL_NAMED_URLS) > 10


@pytest.mark.security
def test_every_public_url_actually_exists() -> None:
    """Una entrada obsoleta en la lista blanca es una exención sin dueño."""
    declared = set(PUBLIC_URL_NAMES)
    existing = {name.rsplit(":", 1)[-1] for name in ALL_NAMED_URLS}
    assert declared <= existing, (
        f"Rutas públicas declaradas que ya no existen: {sorted(declared - existing)}"
    )


@pytest.mark.security
def test_the_project_views_are_included() -> None:
    """Red de seguridad del propio recolector.

    Si el espacio de nombres se perdiera —como ocurrió al recorrer los patrones
    a mano—, las vistas propias desaparecerían de la parametrización sin que
    ninguna prueba fallara.
    """
    assert {
        "accounts:profile",
        "accounts:user_list",
        "dashboard:home",
        "employees:list",
        "employees:detail",
    } <= set(PROTECTED_URLS)


@pytest.mark.security
def test_every_protected_url_can_be_reversed() -> None:
    """Ninguna ruta puede quedarse fuera por no saber fabricar sus argumentos.

    Sin esta comprobación, añadir un tipo de parámetro nuevo (como el UUID de
    `public_id`) sacaba rutas de la parametrización en silencio.
    """
    unreachable = [name for name in PROTECTED_URLS if _reverse_or_none(name) is None]
    assert not unreachable, f"Añade sus argumentos a FALLBACK_ARGS: {unreachable}"


@pytest.mark.security
@pytest.mark.django_db
@pytest.mark.parametrize("name", PROTECTED_URLS)
def test_protected_urls_reject_anonymous_users(name: str) -> None:
    url = _reverse_or_none(name)
    assert url is not None, f"No se pudo resolver {name}; añade sus argumentos a FALLBACK_ARGS"

    response = Client().get(url)

    assert response.status_code in {302, 403, 404}, (
        f"{name} ({url}) respondió {response.status_code} a un usuario anónimo. "
        f"Si debe ser pública, añádela a PUBLIC_URL_NAMES con su motivo."
    )
    if response.status_code == 302:
        assert "/accounts/login/" in response.url, (
            f"{name} redirige a {response.url} en lugar de al acceso"
        )


@pytest.mark.security
@pytest.mark.django_db
def test_signup_route_is_closed(client) -> None:
    """El registro público no existe: ni la ruta ni el adaptador lo permiten."""
    response = client.get("/accounts/signup/")
    assert response.status_code == 404


@pytest.mark.security
@pytest.mark.django_db
def test_signup_post_creates_nothing(client) -> None:
    """Un POST directo al endpoint tampoco crea cuenta."""
    from django.contrib.auth import get_user_model

    before = get_user_model().objects.count()
    response = client.post(
        "/accounts/signup/",
        {
            "email": "intruso@example.com",
            "password1": "Segura-12345678",
            "password2": "Segura-12345678",
        },
    )
    assert response.status_code == 404
    assert get_user_model().objects.count() == before


@pytest.mark.security
def test_adapter_reports_signup_as_closed(rf) -> None:
    from apps.accounts.adapters import NoPublicSignupAdapter

    assert NoPublicSignupAdapter().is_open_for_signup(rf.get("/")) is False
