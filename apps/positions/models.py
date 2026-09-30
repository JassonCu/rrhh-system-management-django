"""Catálogo de puestos y bandas salariales.

Ver docs/database/02-modelo-relacional.md §B.5 y
[ADR-011](../../docs/decisions/ADR-011-position-pertenece-a-departamento.md).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.constants import CURRENCY_CODE_LENGTH
from apps.core.models import TimeStampedModel
from apps.core.validators import validate_currency_code


class JobGrade(TimeStampedModel):
    """Banda salarial.

    El rango de sueldo depende del **grado**, no del puesto. Si viviera en
    `Position`, un ajuste de banda obligaría a actualizar N puestos y permitiría
    valores contradictorios entre puestos del mismo grado: la dependencia
    transitiva `position → job_grade → min_salary` de manual (§D.5.2).
    """

    code = models.CharField(_("code"), max_length=10, unique=True, help_text=_("For example G05."))
    name = models.CharField(_("name"), max_length=80)
    level = models.PositiveSmallIntegerField(
        _("level"), help_text=_("Hierarchical order; higher means more senior.")
    )
    min_salary = models.DecimalField(_("minimum salary"), max_digits=12, decimal_places=2)
    max_salary = models.DecimalField(_("maximum salary"), max_digits=12, decimal_places=2)
    currency = models.CharField(
        _("currency"),
        max_length=CURRENCY_CODE_LENGTH,
        default="GTQ",
        validators=[validate_currency_code],
        help_text=_("ISO 4217 code."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("job grade")
        verbose_name_plural = _("job grades")
        ordering = ("level", "code")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(min_salary__gt=0),
                name="jobgrade_min_salary_positive",
                violation_error_message=_("The minimum salary must be greater than zero."),
            ),
            models.CheckConstraint(
                condition=models.Q(max_salary__gte=models.F("min_salary")),
                name="jobgrade_range_is_ordered",
                violation_error_message=_(
                    "The maximum salary cannot be lower than the minimum salary."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(level__gte=1),
                name="jobgrade_level_positive",
            ),
        ]

    def __str__(self) -> str:
        # Sin traducir: alimenta logs y AuditEvent.object_repr (§O.3.1).
        return f"{self.code} - {self.name}"

    def contains(self, amount) -> bool:
        """Si un salario cae dentro de la banda (RN-23)."""
        return self.min_salary <= amount <= self.max_salary


class Position(TimeStampedModel):
    """Puesto de trabajo, **perteneciente a un departamento**.

    El negocio confirmó que ningún título es transversal y que el perfil se
    define por área, de modo que la dependencia funcional
    `position → department` se cumple. La consecuencia es que `Assignment`
    **no** almacena el departamento: sería transitivo (ADR-011, §D.5.4).
    """

    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="positions",
        verbose_name=_("department"),
        help_text=_("The area this position belongs to."),
    )
    job_grade = models.ForeignKey(
        "positions.JobGrade",
        on_delete=models.PROTECT,
        related_name="positions",
        verbose_name=_("job grade"),
        help_text=_("Determines the salary band. It is not stored here."),
    )
    code = models.CharField(
        _("code"),
        max_length=20,
        unique=True,
        help_text=_("Unique across the whole organization."),
    )
    title = models.CharField(
        _("title"),
        max_length=120,
        help_text=_("Unique within the department."),
    )
    description = models.TextField(
        _("description"),
        blank=True,
        help_text=_("Role profile. Specific to this department."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        verbose_name = _("position")
        verbose_name_plural = _("positions")
        ordering = ("department__name", "title")
        constraints = [
            models.UniqueConstraint(
                fields=["department", "title"],
                name="uniq_position_title_per_department",
                violation_error_message=_(
                    "That department already has a position with this title."
                ),
            ),
        ]
        indexes = [
            # Resuelve "puestos del departamento X", base del alcance de MANAGER
            # una vez exista `Assignment` (índice I-09, ADR-011).
            models.Index(fields=["department", "is_active"], name="position_dept_active_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.title}"
