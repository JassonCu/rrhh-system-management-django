"""Inicio por rol.

Cada rol entra a lo que hace todos los días: RRHH a sus pendientes, una jefatura
a su equipo, cualquier persona a su propia ficha y su contrato.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.constants import Role
from apps.dashboard import selectors

#: Roles que ven el panel de RRHH. El permiso sigue comprobándose en cada vista
#: de destino: aquí solo se decide qué se muestra (comodidad, no seguridad).
HR_ROLES = frozenset({Role.SUPERADMIN, Role.HR_ADMIN, Role.HR_MANAGER})


@login_required
def home(request: HttpRequest) -> HttpResponse:
    user = request.user
    roles = set(user.groups.values_list("name", flat=True))
    shows_hr_panel = user.is_superuser or bool(roles & HR_ROLES)

    context = {
        "shows_hr_panel": shows_hr_panel,
        "shows_team_panel": Role.MANAGER in roles,
        "own_employee": selectors.own_employee(user),
        "own_contract": selectors.own_live_contract(user),
    }
    if shows_hr_panel:
        context["hr"] = selectors.hr_overview(user)
    if context["shows_team_panel"]:
        context["team"] = selectors.team_for(user)

    return render(request, "dashboard/home.html", context)
