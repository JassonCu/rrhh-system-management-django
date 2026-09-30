from django.urls import path

from apps.documents import views

app_name = "documents"

urlpatterns = [
    path("por-vencer/", views.expiring_documents, name="expiring"),
    path("subir/<uuid:employee_public_id>/", views.document_upload, name="upload"),
    path("<uuid:public_id>/descargar/", views.document_download, name="download"),
    path("<uuid:public_id>/archivar/", views.document_archive, name="archive"),
    path("tipos/", views.type_list, name="type_list"),
    path("tipos/nuevo/", views.type_create, name="type_create"),
    path("tipos/<int:pk>/editar/", views.type_update, name="type_update"),
]
