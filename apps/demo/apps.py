from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class DemoConfig(AppConfig):
    """Herramientas de desarrollo. **Solo se instala con `DEBUG=True`.**"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.demo"
    verbose_name = _("Demo data")
