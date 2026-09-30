"""Fixtures compartidas por toda la suite."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from apps.accounts.roles import Role
from apps.core.models import Company

User = get_user_model()

PASSWORD = "Segura-12345678"


@pytest.fixture(autouse=True)
def _isolate_rate_limits():
    """Limpia la caché entre pruebas.

    allauth guarda ahí los contadores de límite de tasa. Con la caché en memoria
    del proceso, una prueba que agota intentos de acceso bloquearía a las
    siguientes, y el fallo aparecería lejos de su causa.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def company(db) -> Company:
    return Company.objects.create(
        code="HQ",
        legal_name="Industrias Ejemplo, S.A.",
        tax_id="1234567-8",
        country="GT",
    )


@pytest.fixture
def user(db) -> User:
    return User.objects.create_user(email="empleado@example.com", password=PASSWORD)


@pytest.fixture
def superuser(db) -> User:
    return User.objects.create_superuser(email="admin@example.com", password=PASSWORD)


@pytest.fixture
def make_user(db):
    """Crea un usuario con los roles indicados y su correo ya verificado.

    La verificación es necesaria porque `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`
    impide iniciar sesión sin ella; las pruebas que la ejercitan la desactivan
    explícitamente en vez de depender de este atajo.
    """
    from allauth.account.models import EmailAddress

    def _make(email: str, *roles: str, **extra) -> User:
        new_user = User.objects.create_user(email=email, password=PASSWORD, **extra)
        EmailAddress.objects.create(
            user=new_user, email=new_user.email, primary=True, verified=True
        )
        if roles:
            new_user.groups.set(Group.objects.filter(name__in=roles))
        return new_user

    return _make


@pytest.fixture
def hr_admin(make_user) -> User:
    return make_user("hr.admin@example.com", Role.HR_ADMIN)


@pytest.fixture
def hr_manager(make_user) -> User:
    return make_user("hr.manager@example.com", Role.HR_MANAGER)


@pytest.fixture
def employee(make_user) -> User:
    return make_user("colaborador@example.com", Role.EMPLOYEE)


@pytest.fixture
def auditor(make_user) -> User:
    return make_user("auditor@example.com", Role.AUDITOR)


@pytest.fixture
def logged_client(client):
    """Devuelve un cliente autenticado como el usuario indicado."""

    def _login(account) -> object:
        client.force_login(account)
        return client

    return _login
