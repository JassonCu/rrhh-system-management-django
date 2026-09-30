"""Enrutamiento raíz.

Sin ``i18n_patterns``: el idioma es una preferencia de la persona, no una
propiedad del recurso (§O.1.3).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path

from apps.accounts import views as account_views

# El admin no tiene login propio: su formulario no pasa por allauth, así que no
# tendría límite de intentos ni verificación de correo, justo en la puerta hacia
# las cuentas con más privilegios. Sin sesión, se redirige al login de allauth;
# con sesión, la vista del admin lleva al índice (revisión de la Fase 4, H-7).
admin.site.login = login_required(admin.site.login)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),  # set_language (POST + CSRF)
    # El registro público no existe. Esta ruta precede a las de allauth para
    # ganar la resolución y responder 404 (ADR-004). Es redundante con
    # `NoPublicSignupAdapter` a propósito: ninguno de los dos basta solo.
    path("accounts/signup/", account_views.signup_closed, name="account_signup_closed"),
    path("accounts/", include("allauth.urls")),
    path("cuentas/", include("apps.accounts.urls")),
    path("empleados/", include("apps.employees.urls")),
    path("contratos/", include("apps.contracts.urls")),
    path("asistencia/", include("apps.attendance.urls")),
    path("ausencias/", include("apps.leave.urls")),
    path("documentos/", include("apps.documents.urls")),
    path("reportes/", include("apps.reports.urls")),
    path("departamentos/", include("apps.departments.urls")),
    path("puestos/", include("apps.positions.urls")),
    # El inicio vive en `dashboard` y no en `core`: muestra datos de empleados y
    # contratos, y `core` no puede depender de ningún dominio (ADR-001).
    path("", include("apps.dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    try:
        import debug_toolbar  # noqa: F401

        urlpatterns += [path("__debug__/", include("debug_toolbar.urls"))]
    except ImportError:  # pragma: no cover
        pass

# MEDIA_URL NO se sirve aquí a propósito: los documentos se entregan siempre
# desde una vista que autoriza primero (§K.4).

handler400 = "apps.core.views.bad_request"
handler403 = "apps.core.views.permission_denied"
handler404 = "apps.core.views.page_not_found"
handler500 = "apps.core.views.server_error"
