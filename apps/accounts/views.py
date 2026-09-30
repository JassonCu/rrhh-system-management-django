"""Vistas de cuentas.

Cada vista aplica las tres capas en orden: autenticación, permiso y alcance
(§J.6). `raise_exception=True` es obligatorio en `permission_required`: sin él,
un usuario autenticado pero sin permiso sería redirigido al login y quedaría en
un bucle en lugar de recibir un 403.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.accounts import selectors, services
from apps.accounts.forms import DeactivateUserForm, InviteUserForm, ProfileForm
from apps.core.exceptions import ConflictError, ValidationError

User = get_user_model()

#: Mensajes de error de dominio. Los servicios devuelven un `code` estable y es
#: la capa de presentación quien lo traduce (§O.5.1): así el usuario lee su
#: idioma y el log conserva un identificador buscable.
ERROR_MESSAGES = {
    "user_already_exists": _("An account with that email address already exists."),
    "cannot_change_own_roles": _("You cannot change your own roles."),
    "cannot_deactivate_self": _("You cannot deactivate your own account."),
    "incompatible_roles": _("Those roles cannot be combined."),
    "unknown_roles": _("One of the selected roles does not exist."),
}


def _message_for(error: ConflictError | ValidationError) -> str:
    return ERROR_MESSAGES.get(error.code, _("The operation could not be completed."))


def signup_closed(request: HttpRequest) -> HttpResponse:  # noqa: ARG001
    """El registro público no existe (ADR-004).

    Esta ruta se declara **antes** que las de allauth para que gane la
    resolución. Es el segundo de los dos mecanismos que cierran el registro; el
    primero es `NoPublicSignupAdapter`. Se responde 404 y no 403 porque el
    recurso realmente no existe en esta aplicación.
    """
    raise Http404


@login_required
@require_http_methods(["GET", "POST"])
def profile(request: HttpRequest) -> HttpResponse:
    """Perfil propio. El alcance es trivial: siempre `request.user`."""
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("Your preferences were saved."))
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@login_required
@permission_required("accounts.view_user", raise_exception=True)
def user_list(request: HttpRequest) -> HttpResponse:
    """Listado de cuentas. Paginado siempre: ningún listado devuelve todo."""
    users: QuerySet = selectors.users_visible_for(request.user)
    query = request.GET.get("q", "").strip()
    if query:
        users = users.filter(email__icontains=query)

    page = Paginator(users, 25).get_page(request.GET.get("page"))
    return render(request, "accounts/user_list.html", {"page": page, "query": query})


@login_required
@permission_required("accounts.manage_users", raise_exception=True)
@require_http_methods(["GET", "POST"])
def invite_user(request: HttpRequest) -> HttpResponse:
    """Alta de una cuenta. Único mecanismo de la Fase 2 (ADR-004)."""
    form = InviteUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            user = services.invite_user(
                email=form.cleaned_data["email"],
                roles=form.cleaned_data["roles"],
                actor=request.user,
                request=request,
            )
        except (ConflictError, ValidationError) as error:
            messages.error(request, _message_for(error))
        else:
            messages.success(
                request,
                _("Invitation sent to %(email)s.") % {"email": user.email},
            )
            return redirect("accounts:user_list")
    return render(request, "accounts/invite_user.html", {"form": form})


@login_required
@permission_required("accounts.manage_users", raise_exception=True)
@require_http_methods(["GET", "POST"])
def deactivate_user(request: HttpRequest, pk: int) -> HttpResponse:
    """Baja de una cuenta.

    El `GET` solo muestra la confirmación; la baja se ejecuta con `POST` y CSRF,
    de modo que un enlace no puede dispararla (plan UX/UI §5).
    """
    user = selectors.get_user_or_404(request.user, pk=pk)
    form = DeactivateUserForm(request.POST or None)

    if request.method == "GET":
        return render(
            request,
            "confirm_action.html",
            {
                "title": _("Deactivate account"),
                "subject": user.email,
                "consequences": [
                    _("The person will no longer be able to sign in."),
                    _("Their open sessions will be closed immediately."),
                    _("The account is not deleted: the audit log refers to it."),
                    _("You can invite them again later with a new invitation."),
                ],
                "confirm_label": _("Deactivate account"),
                "cancel_url": reverse("accounts:user_list"),
                "danger": True,
                "form": form,
            },
        )

    try:
        services.deactivate_user(
            user=user,
            actor=request.user,
            request=request,
            reason=form.cleaned_data["reason"] if form.is_valid() else "",
        )
    except ConflictError as error:
        messages.error(request, _message_for(error))
    else:
        messages.success(
            request,
            _("Account %(email)s was deactivated.") % {"email": user.email},
        )
    return redirect("accounts:user_list")
