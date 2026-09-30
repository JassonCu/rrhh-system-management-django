from django.urls import path

from apps.positions import views

app_name = "positions"

urlpatterns = [
    path("", views.position_list, name="list"),
    path("nuevo/", views.position_create, name="create"),
    path("<int:pk>/", views.position_detail, name="detail"),
    path("<int:pk>/editar/", views.position_update, name="update"),
    path("<int:pk>/desactivar/", views.position_deactivate, name="deactivate"),
    path("bandas/", views.job_grade_list, name="job_grade_list"),
    path("bandas/nueva/", views.job_grade_create, name="job_grade_create"),
]
