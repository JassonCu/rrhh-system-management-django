from django.urls import path

from apps.accounts import views

app_name = "accounts"

urlpatterns = [
    path("perfil/", views.profile, name="profile"),
    path("usuarios/", views.user_list, name="user_list"),
    path("usuarios/invitar/", views.invite_user, name="invite_user"),
    path("usuarios/<int:pk>/desactivar/", views.deactivate_user, name="deactivate_user"),
]
