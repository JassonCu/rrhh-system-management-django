from django.urls import path

from apps.leave import views

app_name = "leave"

urlpatterns = [
    path("", views.my_leave, name="my_leave"),
    path("solicitar/", views.request_start, name="request_start"),
    path("solicitar/fechas/", views.request_dates, name="request_dates"),
    path("solicitudes/<uuid:public_id>/", views.request_detail, name="request_detail"),
    path("solicitudes/<uuid:public_id>/revisar/", views.request_review, name="request_review"),
    path("solicitudes/<uuid:public_id>/aprobar/", views.request_approve, name="request_approve"),
    path("solicitudes/<uuid:public_id>/rechazar/", views.request_reject, name="request_reject"),
    path("solicitudes/<uuid:public_id>/cancelar/", views.request_cancel, name="request_cancel"),
    path("bandeja/", views.inbox, name="inbox"),
    path("calendario/", views.team_calendar, name="team_calendar"),
    path("tipos/", views.type_list, name="type_list"),
    path("tipos/nuevo/", views.type_create, name="type_create"),
    path("tipos/<int:pk>/editar/", views.type_update, name="type_update"),
    path("tipos/<int:pk>/tramos/", views.tier_add, name="tier_add"),
    path("tipos/<int:pk>/tramos/<int:tier_pk>/quitar/", views.tier_remove, name="tier_remove"),
    path("saldos/ajustar/", views.balance_adjust, name="balance_adjust"),
    path("saldos/<str:employee_code>/", views.employee_balance, name="employee_balance"),
]
