from django.urls import path

from apps.departments import views

app_name = "departments"

urlpatterns = [
    path("", views.department_list, name="list"),
    path("nuevo/", views.department_create, name="create"),
    path("<int:pk>/", views.department_detail, name="detail"),
    path("<int:pk>/editar/", views.department_update, name="update"),
    path("<int:pk>/desactivar/", views.department_deactivate, name="deactivate"),
    # Jefaturas y empresas salen del admin de Django (UX-3, D-07).
    path("<int:pk>/jefatura/", views.headship_assign, name="headship_assign"),
    path(
        "<int:pk>/jefatura/<int:headship_pk>/finalizar/",
        views.headship_end,
        name="headship_end",
    ),
    path("empresas/", views.company_list, name="company_list"),
    path("empresas/nueva/", views.company_create, name="company_create"),
    path("empresas/<int:pk>/editar/", views.company_update, name="company_update"),
]
