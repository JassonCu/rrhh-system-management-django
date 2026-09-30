from django.urls import path

from apps.contracts import views

app_name = "contracts"

# Contratos por `public_id`. Las asignaciones se direccionan SIEMPRE dentro de su
# contrato: la vista las busca en el conjunto ya autorizado.
urlpatterns = [
    path("", views.contract_list, name="list"),
    path("nuevo/<uuid:employee_public_id>/", views.contract_create, name="create"),
    path("<uuid:public_id>/", views.contract_detail, name="detail"),
    path("<uuid:public_id>/asistente/", views.contract_wizard, name="wizard"),
    path("<uuid:public_id>/salario/", views.salary_set, name="salary_set"),
    path("<uuid:public_id>/asignaciones/nueva/", views.assignment_add, name="assignment_add"),
    path(
        "<uuid:public_id>/asignaciones/<int:pk>/finalizar/",
        views.assignment_end,
        name="assignment_end",
    ),
    path("<uuid:public_id>/activar/", views.contract_activate, name="activate"),
    path("<uuid:public_id>/suspender/", views.contract_suspend, name="suspend"),
    path("<uuid:public_id>/reanudar/", views.contract_resume, name="resume"),
    path("<uuid:public_id>/terminar/", views.contract_terminate, name="terminate"),
]
