from django.urls import path

from apps.employees import views

app_name = "employees"

# El identificador de la URL es el `public_id` (UUID) y no la clave primaria:
# los empleados no exponen identificadores enumerables (§B). Esto NO sustituye a
# la autorización, que aplica igualmente el selector con alcance.
urlpatterns = [
    path("", views.employee_list, name="list"),
    path("nuevo/", views.employee_create, name="create"),
    path("<uuid:public_id>/", views.employee_detail, name="detail"),
    path("<uuid:public_id>/editar/", views.employee_update, name="update"),
    path("<uuid:public_id>/documentos/nuevo/", views.document_add, name="document_add"),
]
