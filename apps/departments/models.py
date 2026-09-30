"""Estructura organizacional.

Ver docs/database/02-modelo-relacional.md §B.4.

Incluye `DepartmentHeadship`, la jefatura **con vigencia**: la cadena de
aprobación debe poder reconstruirse tal como era en la fecha de una decisión, y
una columna `manager_id` mutable reescribiría la historia en cada cambio (§A.2.3).
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Department(TimeStampedModel):
    """Nodo del organigrama.

    Jerarquía por lista de adyacencia (`parent`). Se descartan *materialized
    path*, *nested set* y `django-mptt` por YAGNI: la profundidad esperada es ≤ 5
    y las consultas de subárbol se resuelven con una expansión iterativa acotada
    (§B.4).
    """

    company = models.ForeignKey(
        "core.Company",
        on_delete=models.PROTECT,
        related_name="departments",
        verbose_name=_("company"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("parent department"),
        help_text=_("Leave empty for the root of the organization chart."),
    )
    code = models.CharField(_("code"), max_length=20, help_text=_("Unique within the company."))
    name = models.CharField(_("name"), max_length=120)
    cost_center = models.CharField(
        _("cost center"), max_length=30, blank=True, help_text=_("Link with accounting.")
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_("Deactivate instead of deleting: the history refers to it."),
    )

    class Meta:
        verbose_name = _("department")
        verbose_name_plural = _("departments")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="uniq_department_code_per_company",
                violation_error_message=_("That company already has a department with this code."),
            ),
            # La autorreferencia directa sí es expresable; la aciclicidad completa
            # (RN-31) no lo es sin un trigger recursivo, y se valida en el
            # servicio con su prueba.
            models.CheckConstraint(
                condition=~models.Q(parent=models.F("id")),
                name="department_is_not_its_own_parent",
                violation_error_message=_("A department cannot be its own parent."),
            ),
        ]
        indexes = [
            models.Index(fields=["parent"], name="department_parent_idx"),
            models.Index(fields=["company", "is_active"], name="department_active_idx"),
        ]

    def __str__(self) -> str:
        # Sin traducir: alimenta logs y AuditEvent.object_repr.
        return f"{self.code} - {self.name}"

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    def ancestors(self) -> list[Department]:
        """Cadena de mando hacia arriba, de padre a raíz.

        El bucle lleva un tope explícito: si una corrupción de datos creara un
        ciclo, esto debe terminar igualmente en lugar de colgar el proceso.
        """
        chain: list[Department] = []
        seen: set[int] = {self.pk}
        node = self.parent
        while node is not None and node.pk not in seen:
            chain.append(node)
            seen.add(node.pk)
            node = node.parent
        return chain


class DepartmentHeadship(TimeStampedModel):
    """Jefatura de un departamento durante un período.

    Es una entidad y no una columna `Department.manager_id` porque la pregunta
    que el sistema debe poder responder no es "quién manda aquí" sino "quién
    mandaba aquí **el día que se aprobó aquello**".
    """

    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="headships",
        verbose_name=_("department"),
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="headships",
        verbose_name=_("head"),
    )
    start_date = models.DateField(_("start date"))
    end_date = models.DateField(
        _("end date"), null=True, blank=True, help_text=_("Empty means currently in charge.")
    )
    appointment_note = models.CharField(_("appointment note"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("department headship")
        verbose_name_plural = _("department headships")
        ordering = ("-start_date",)
        constraints = [
            models.UniqueConstraint(
                fields=["department", "start_date"],
                name="uniq_headship_per_department_and_start",
            ),
            # RN-32: un solo jefe vigente por departamento, garantizado por la base.
            models.UniqueConstraint(
                fields=["department"],
                condition=models.Q(end_date__isnull=True),
                name="uniq_current_head_per_department",
                violation_error_message=_("That department already has a current head."),
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="headship_dates_ordered",
                violation_error_message=_("The end date cannot precede the start date."),
            ),
        ]
        indexes = [
            # "¿Qué departamentos jefea hoy este empleado?": consulta CRÍTICA
            # para la autorización del rol MANAGER (índice I-10).
            models.Index(fields=["employee", "end_date"], name="headship_employee_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.department.code} <- {self.employee.employee_code}"

    @property
    def is_current(self) -> bool:
        return self.end_date is None
