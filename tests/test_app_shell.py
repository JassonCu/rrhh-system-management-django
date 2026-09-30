"""Estructura común de la aplicación y sus componentes (entrega UX-1).

Verificaciones automáticas del plan UX/UI §13: si una pantalla nueva no usa la
base, deja una tabla inaccesible o referencia un icono inexistente, la suite
falla en lugar de esperar a una revisión visual.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.core.paginator import Paginator
from django.template import Context, RequestContext, Template
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.constants import Role

BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_ROOTS = (BASE_DIR / "templates", BASE_DIR / "apps")
SPRITE = BASE_DIR / "static" / "img" / "icons.svg"

#: Fragmentos y documentos autónomos: no son páginas.
NOT_PAGES = {"base.html", "500.html"}


def _templates() -> list[Path]:
    found: list[Path] = []
    for root in TEMPLATE_ROOTS:
        found += [p for p in root.rglob("*.html") if ".venv" not in p.parts]
    return sorted(found)


ALL_TEMPLATES = _templates()
PAGE_TEMPLATES = [p for p in ALL_TEMPLATES if "includes" not in p.parts and p.name not in NOT_PAGES]


def relative(path: Path) -> str:
    return path.relative_to(BASE_DIR).as_posix()


# --- Todas las páginas comparten la estructura ------------------------------ #


@pytest.mark.parametrize("template", PAGE_TEMPLATES, ids=relative)
def test_every_page_extends_a_base(template: Path) -> None:
    content = template.read_text(encoding="utf-8").lstrip()
    assert content.startswith("{% extends"), f"{relative(template)} no extiende ninguna base"


@pytest.mark.parametrize("template", ALL_TEMPLATES, ids=relative)
def test_tables_are_accessible(template: Path) -> None:
    """Cada tabla con <caption> y cada <th> con scope (WCAG 1.3.1)."""
    content = template.read_text(encoding="utf-8")
    tables = content.count("<table")
    if not tables:
        pytest.skip("sin tablas")
    assert content.count("<caption") >= tables, "tabla sin <caption>"
    assert not re.search(r"<th(?![^>]*\bscope=)[\s>]", content), "<th> sin scope"


def test_every_icon_used_exists_in_the_sprite() -> None:
    used = {
        name
        for path in ALL_TEMPLATES
        for name in re.findall(
            r'includes/icon\.html"\s+with\s+name="([\w-]+)"', path.read_text(encoding="utf-8")
        )
    }
    available = set(re.findall(r'<symbol id="([\w-]+)"', SPRITE.read_text(encoding="utf-8")))

    assert used, "no se detectó ningún icono: el patrón de búsqueda está roto"
    assert used <= available, f"iconos inexistentes: {sorted(used - available)}"


# --- Insignias de estado ------------------------------------------------------ #


@pytest.mark.parametrize(
    ("status", "variant"),
    [
        ("ACTIVE", "badge--success"),
        ("SUSPENDED", "badge--warning"),
        ("DRAFT", "badge--info"),
        ("ON_LEAVE", "badge--info"),
        ("TERMINATED", "badge--neutral"),
        ("EXPIRED", "badge--neutral"),
        ("INACTIVE", "badge--neutral"),
    ],
)
def test_status_badge_variant_and_text(status: str, variant: str) -> None:
    html = Template('{% include "includes/status_badge.html" with status=s label=l %}').render(
        Context({"s": status, "l": "Etiqueta visible"})
    )
    assert variant in html
    assert "Etiqueta visible" in html, "el color nunca es la única señal"


# --- Navegación ---------------------------------------------------------------- #


@pytest.mark.django_db
def test_sidebar_marks_the_current_section(client, make_user) -> None:
    client.force_login(make_user("nav.rrhh@example.com", Role.HR_ADMIN))

    content = client.get(reverse("employees:list")).content.decode()

    assert re.search(rf'href="{reverse("employees:list")}"\s*aria-current="page"', content)
    assert not re.search(rf'href="{reverse("contracts:list")}"\s*aria-current="page"', content)


@pytest.mark.django_db
def test_sidebar_hides_sections_the_role_cannot_use(client, make_user) -> None:
    """Comodidad, no seguridad: la vista sigue comprobando el permiso."""
    client.force_login(make_user("nav.empleado@example.com", Role.EMPLOYEE))

    content = client.get(reverse("accounts:profile")).content.decode()

    assert f'href="{reverse("accounts:user_list")}"' not in content
    assert f'href="{reverse("admin:index")}"' not in content


@pytest.mark.django_db
def test_authenticated_pages_have_landmarks_and_branded_title(client, make_user) -> None:
    client.force_login(make_user("landmarks@example.com", Role.EMPLOYEE))

    content = client.get(reverse("accounts:profile")).content.decode()

    assert 'class="skip-link"' in content
    assert '<main id="main"' in content
    assert 'class="app-sidebar"' in content
    assert re.search(r"<title>[^<]+ · Ceiba RH</title>", content)


@pytest.mark.django_db
def test_public_error_page_has_no_sidebar(client) -> None:
    response = client.get("/esta-ruta-no-existe/")

    assert response.status_code == 404
    content = response.content.decode()
    assert "app--public" in content
    assert 'class="app-sidebar"' not in content


# --- Paginación ------------------------------------------------------------------ #


def test_pagination_keeps_active_filters() -> None:
    """Antes solo conservaba la búsqueda: el filtro de estado se perdía al paginar."""
    request = RequestFactory().get("/empleados/", {"q": "ana", "status": "ACTIVE"})
    page = Paginator(list(range(60)), 25).page(1)

    html = Template('{% include "includes/pagination.html" %}').render(
        RequestContext(request, {"page": page})
    )

    assert "page=2" in html
    assert "status=ACTIVE" in html
    assert "q=ana" in html
