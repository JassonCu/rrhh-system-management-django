from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = _("Accounts")

    def ready(self) -> None:
        # Importar por efecto: conecta los receptores de señales.
        from apps.accounts import signals  # noqa: F401
