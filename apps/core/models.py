"""Modelos transversales.

Ver el diseño en:

* docs/database/02-modelo-relacional.md §B.1
* docs/database/06-diccionario-de-datos.md §G.1 y §G.2
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.constants import COUNTRY_CODE_LENGTH
from apps.core.validators import validate_country_code


class TimeStampedModel(models.Model):
    """Marcas de tiempo técnicas para toda entidad **mutable**.

    Las entidades append-only (``AuditEvent``, asientos, transiciones) **no**
    heredan de aquí: ``updated_at`` sería siempre igual a ``created_at`` y
    mentiría sobre su inmutabilidad (§G.0).
    """

    created_at = models.DateTimeField(_("created at"), auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True, editable=False)

    class Meta:
        abstract = True


class Company(TimeStampedModel):
    """Entidad legal empleadora.

    Existe desde el primer día aunque hoy solo haya una fila: añadir después una
    FK no nula a media docena de tablas con datos cargados es una migración con
    riesgo, y esta es la única decisión del modelo cuyo retrofit sale caro
    (ADR-010, §A.5).
    """

    code = models.CharField(
        _("code"),
        max_length=20,
        unique=True,
        help_text=_("Short internal identifier, e.g. HQ."),
    )
    legal_name = models.CharField(_("legal name"), max_length=200)
    trade_name = models.CharField(_("trade name"), max_length=200, blank=True)
    tax_id = models.CharField(
        _("tax ID"),
        max_length=20,
        unique=True,
        help_text=_("Employer tax identification number."),
    )
    country = models.CharField(
        _("country"),
        max_length=COUNTRY_CODE_LENGTH,
        default="GT",
        validators=[validate_country_code],
        help_text=_("ISO 3166-1 alpha-2 code."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("company")
        verbose_name_plural = _("companies")
        ordering = ("legal_name",)

    def __str__(self) -> str:
        # No se traduce: alimenta logs, exportaciones y AuditEvent.object_repr,
        # que deben ser idénticos sea cual sea el idioma del actor (§O.3.1).
        return self.legal_name


class Holiday(TimeStampedModel):
    """Feriado oficial.

    Insumo del cálculo de días hábiles en ``leave`` y ``attendance`` (RN-42). Se
    modela por empresa porque los asuetos locales pueden diferir entre sedes.
    """

    company = models.ForeignKey(
        "core.Company",
        on_delete=models.PROTECT,
        related_name="holidays",
        verbose_name=_("company"),
    )
    date = models.DateField(_("date"))
    name = models.CharField(_("name"), max_length=120)
    is_mandatory = models.BooleanField(
        _("statutory"),
        default=True,
        help_text=_("Whether it is mandated by law rather than granted by the company."),
    )

    class Meta:
        verbose_name = _("holiday")
        verbose_name_plural = _("holidays")
        ordering = ("-date",)
        constraints = [
            models.UniqueConstraint(
                fields=["company", "date"],
                name="uniq_holiday_per_company_and_date",
                violation_error_message=_("This company already has a holiday on that date."),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date.isoformat()} {self.name}"
