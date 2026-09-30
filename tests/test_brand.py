"""Identidad de marca: un solo nombre, recursos seguros bajo la CSP.

Ver docs/ux/16-identidad-de-marca.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

import pytest
from django.conf import settings
from django.urls import reverse

BASE_DIR = Path(__file__).resolve().parents[1]
BRAND_ASSETS = sorted((BASE_DIR / "static" / "img").rglob("*.svg"))
TEMPLATE_ROOTS = (BASE_DIR / "templates", BASE_DIR / "apps")


def test_product_name_is_defined_once() -> None:
    assert settings.PRODUCT_NAME == "Ceiba RH"


@pytest.mark.django_db
def test_login_shows_the_brand(client) -> None:
    content = client.get(reverse("account_login")).content.decode()

    assert "Ceiba RH" in content
    assert "img/brand/ceiba-mark.svg" in content
    assert "<title>" in content and "Ceiba RH</title>" in content


@pytest.mark.django_db
def test_the_navigation_shows_the_brand(client, django_user_model) -> None:
    client.force_login(django_user_model.objects.create_user(email="marca@example.com"))

    content = client.get(reverse("accounts:profile")).content.decode()

    assert 'class="app-brand"' in content
    assert "Ceiba RH" in content


def test_the_old_product_name_is_gone() -> None:
    """El nombre genérico no debe reaparecer en ninguna plantilla."""
    offenders = [
        str(path.relative_to(BASE_DIR))
        for root in TEMPLATE_ROOTS
        for path in root.rglob("*.html")
        if ".venv" not in path.parts
        and re.search(r"HR (Management )?System", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_brand_assets_exist() -> None:
    names = {path.name for path in BRAND_ASSETS}
    assert {"ceiba-mark.svg", "ceiba-logo.svg", "ceiba-logo-inverse.svg", "favicon.svg"} <= names


@pytest.mark.security
@pytest.mark.parametrize("asset", BRAND_ASSETS, ids=lambda p: p.name)
def test_svg_assets_are_inert(asset: Path) -> None:
    """Un SVG puede llevar scripts y cargar recursos externos. Los nuestros no."""
    content = asset.read_text(encoding="utf-8")
    ElementTree.fromstring(content)  # noqa: S314 - recurso propio del repositorio, no entrada externa

    assert "<script" not in content.lower()
    assert not re.search(r"\son[a-z]+\s*=", content, re.IGNORECASE), "manejador de eventos"
    assert not re.search(r"(href|src)\s*=\s*[\"']\s*(https?:|//|data:)", content, re.IGNORECASE)
    assert "<foreignobject" not in content.lower()
