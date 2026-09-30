from django.urls import path

from apps.attendance import views

app_name = "attendance"

urlpatterns = [
    path("", views.my_attendance, name="my_attendance"),
    path("marcar/", views.punch, name="punch"),
    path("equipo/", views.team_attendance, name="team"),
    path("incidencias/", views.incident_list, name="incident_list"),
    path("incidencias/<int:pk>/resolver/", views.incident_resolve, name="incident_resolve"),
    path("marcajes/<int:pk>/ajustar/", views.entry_adjust, name="entry_adjust"),
    path("jornadas/", views.schedule_list, name="schedule_list"),
    path("jornadas/nueva/", views.schedule_create, name="schedule_create"),
    path(
        "jornadas/asignar/<uuid:contract_public_id>/",
        views.schedule_assign,
        name="schedule_assign",
    ),
]
