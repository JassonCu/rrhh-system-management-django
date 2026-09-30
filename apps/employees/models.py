"""Identidad civil e identidad laboral.

Separadas a propósito (§A.2.1, regla 13): `Person` es quién es alguien y
`Employee` es desde cuándo trabaja aquí. Los atributos multivaluados —documentos,
teléfonos, direcciones— viven en sus propias relaciones, no como columnas
(§D.3).

**Clasificación:** todo este módulo es PII. `IdentityDocument.number` y
`Person.birth_date` son PII **sensible** y se enmascaran salvo para RRHH y la
propia persona (§G.19).
"""

from __future__ import annotations

import datetime as dt
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.constants import COUNTRY_CODE_LENGTH
from apps.core.models import TimeStampedModel
from apps.core.validators import validate_country_code
from apps.employees.constants import (
    EARLIEST_BIRTH_YEAR,
    AddressType,
    ContactType,
    DocumentType,
    EmploymentStatus,
    Gender,
    MaritalStatus,
    Relationship,
)
from apps.employees.validators import (
    mask_document_number,
    normalize_document_number,
    validate_document_number,
)


class Person(TimeStampedModel):
    """Identidad civil de una persona física."""

    first_name = models.CharField(_("first name"), max_length=60)
    middle_name = models.CharField(_("middle name"), max_length=60, blank=True)
    last_name = models.CharField(_("last name"), max_length=60)
    second_last_name = models.CharField(
        _("second last name"),
        max_length=60,
        blank=True,
        help_text=_("Common in Spanish-speaking naming conventions."),
    )
    birth_date = models.DateField(_("date of birth"))
    gender = models.CharField(
        _("gender"), max_length=20, choices=Gender, default=Gender.UNDISCLOSED
    )
    marital_status = models.CharField(
        _("marital status"),
        max_length=20,
        choices=MaritalStatus,
        default=MaritalStatus.UNDISCLOSED,
    )
    nationality = models.CharField(
        _("nationality"),
        max_length=COUNTRY_CODE_LENGTH,
        default="GT",
        validators=[validate_country_code],
        help_text=_("ISO 3166-1 alpha-2 code."),
    )

    class Meta:
        verbose_name = _("person")
        verbose_name_plural = _("people")
        ordering = ("last_name", "second_last_name", "first_name")
        constraints = [
            # `birth_date < CURRENT_DATE` NO es expresable: PostgreSQL rechaza
            # funciones no inmutables en un CHECK. El límite inferior sí lo es y
            # atrapa el error de captura evidente; que la fecha sea pasada lo
            # valida `clean()`.
            models.CheckConstraint(
                condition=models.Q(birth_date__gte=dt.date(EARLIEST_BIRTH_YEAR, 1, 1)),
                name="person_birth_date_is_plausible",
                violation_error_message=_("The date of birth is not plausible."),
            ),
            models.CheckConstraint(
                condition=models.Q(gender__in=Gender.values),
                name="person_gender_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(marital_status__in=MaritalStatus.values),
                name="person_marital_status_valid",
            ),
        ]
        indexes = [
            # Búsqueda y orden alfabético del listado principal (índice I-04).
            models.Index(fields=["last_name", "first_name"], name="person_name_idx"),
        ]

    def __str__(self) -> str:
        # Sin traducir: alimenta logs y AuditEvent.object_repr (§O.3.1).
        return self.full_name

    def clean(self) -> None:
        super().clean()
        if self.birth_date and self.birth_date >= timezone.localdate():
            raise ValidationError({"birth_date": _("The date of birth must be in the past.")})

    @property
    def full_name(self) -> str:
        """Nombre completo. **Derivado, nunca almacenado.**

        Guardarlo crearía la dependencia `{nombres} → full_name`, cuyo
        determinante no es clave candidata: violación de BCNF y fuente directa
        de anomalías de actualización (§C.4).
        """
        parts = [self.first_name, self.middle_name, self.last_name, self.second_last_name]
        return " ".join(part for part in parts if part)

    @property
    def short_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def age_at(self, reference: dt.date) -> int:
        """Edad cumplida en una fecha dada. Se usa para RN-04."""
        born = self.birth_date
        return (
            reference.year - born.year - ((reference.month, reference.day) < (born.month, born.day))
        )


class IdentityDocument(TimeStampedModel):
    """Documento de identificación: DPI, NIT, IGSS, pasaporte, licencia.

    Existe como relación —y no como columnas de `Person`— porque es un atributo
    **multivaluado**: cada tipo nuevo sería si no una migración de esquema, y la
    tabla se llenaría de nulos (§D.3).
    """

    person = models.ForeignKey(
        "employees.Person",
        on_delete=models.CASCADE,
        related_name="identity_documents",
        verbose_name=_("person"),
    )
    document_type = models.CharField(_("document type"), max_length=20, choices=DocumentType)
    number = models.CharField(
        _("number"), max_length=40, help_text=_("Stored without spaces or dashes.")
    )
    issuing_country = models.CharField(
        _("issuing country"),
        max_length=COUNTRY_CODE_LENGTH,
        default="GT",
        validators=[validate_country_code],
    )
    issued_on = models.DateField(_("issued on"), null=True, blank=True)
    expires_on = models.DateField(
        _("expires on"), null=True, blank=True, help_text=_("Empty means it does not expire.")
    )
    is_primary = models.BooleanField(_("primary identification"), default=False)

    class Meta:
        verbose_name = _("identity document")
        verbose_name_plural = _("identity documents")
        ordering = ("document_type",)
        constraints = [
            models.UniqueConstraint(
                fields=["document_type", "number", "issuing_country"],
                name="uniq_identity_document",
                violation_error_message=_("That document is already registered."),
            ),
            # RN-03: un documento **permanente** por tipo y país. La condición no
            # puede referirse a la fecha de hoy —no es inmutable en un índice—,
            # así que cubre el caso de los documentos sin vencimiento y la
            # vigencia por fecha se valida en el servicio (§3.2 de integridad).
            models.UniqueConstraint(
                fields=["person", "document_type", "issuing_country"],
                condition=models.Q(expires_on__isnull=True),
                name="uniq_permanent_document_per_person",
                violation_error_message=_(
                    "That person already has a permanent document of this type."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(issued_on__isnull=True)
                | models.Q(expires_on__isnull=True)
                | models.Q(expires_on__gte=models.F("issued_on")),
                name="identity_document_dates_ordered",
                violation_error_message=_("The expiry date cannot precede the issue date."),
            ),
            models.CheckConstraint(
                condition=models.Q(document_type__in=DocumentType.values),
                name="identity_document_type_valid",
            ),
        ]

    def __str__(self) -> str:
        # **Enmascarado a propósito**: `__str__` alimenta `AuditEvent.object_repr`
        # y los logs, y un identificador personal no debe acabar ahí (RN-72).
        return f"{self.document_type} {self.masked_number}"

    def clean(self) -> None:
        super().clean()
        self.number = normalize_document_number(self.number)
        validate_document_number(self.document_type, self.number)

    def save(self, *args, **kwargs) -> None:
        self.number = normalize_document_number(self.number)
        super().save(*args, **kwargs)

    @property
    def masked_number(self) -> str:
        return mask_document_number(self.number)

    @property
    def is_expired(self) -> bool:
        return self.expires_on is not None and self.expires_on < timezone.localdate()


class ContactMethod(TimeStampedModel):
    """Teléfono o correo. Multivaluado: prohíbe `phones = "555,556"` (§D.3)."""

    person = models.ForeignKey(
        "employees.Person",
        on_delete=models.CASCADE,
        related_name="contact_methods",
        verbose_name=_("person"),
    )
    contact_type = models.CharField(_("type"), max_length=20, choices=ContactType)
    value = models.CharField(_("value"), max_length=150)
    is_primary = models.BooleanField(_("primary"), default=False)
    notes = models.CharField(_("notes"), max_length=200, blank=True)

    class Meta:
        verbose_name = _("contact method")
        verbose_name_plural = _("contact methods")
        ordering = ("contact_type", "-is_primary")
        constraints = [
            models.UniqueConstraint(
                fields=["person", "contact_type", "value"],
                name="uniq_contact_method",
                violation_error_message=_("That contact detail is already registered."),
            ),
            # RN-05: a lo sumo un principal por tipo.
            models.UniqueConstraint(
                fields=["person", "contact_type"],
                condition=models.Q(is_primary=True),
                name="uniq_primary_contact_per_type",
                violation_error_message=_("There is already a primary contact of this type."),
            ),
            models.CheckConstraint(
                condition=models.Q(contact_type__in=ContactType.values),
                name="contact_method_type_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.contact_type}: {self.value}"

    def save(self, *args, **kwargs) -> None:
        if self.contact_type in {ContactType.PERSONAL_EMAIL, ContactType.WORK_EMAIL}:
            self.value = self.value.strip().lower()
        else:
            self.value = self.value.strip().replace(" ", "")
        super().save(*args, **kwargs)


class Address(TimeStampedModel):
    """Dirección. `locality`/`region` son texto libre por decisión explícita (§A.6)."""

    person = models.ForeignKey(
        "employees.Person",
        on_delete=models.CASCADE,
        related_name="addresses",
        verbose_name=_("person"),
    )
    address_type = models.CharField(
        _("type"), max_length=20, choices=AddressType, default=AddressType.HOME
    )
    line1 = models.CharField(_("address line 1"), max_length=200)
    line2 = models.CharField(_("address line 2"), max_length=200, blank=True)
    locality = models.CharField(_("locality"), max_length=100)
    region = models.CharField(_("region"), max_length=100)
    postal_code = models.CharField(_("postal code"), max_length=20, blank=True)
    country = models.CharField(
        _("country"),
        max_length=COUNTRY_CODE_LENGTH,
        default="GT",
        validators=[validate_country_code],
    )
    is_primary = models.BooleanField(_("primary"), default=False)

    class Meta:
        verbose_name = _("address")
        verbose_name_plural = _("addresses")
        ordering = ("-is_primary", "address_type")
        constraints = [
            # RN-06: una sola dirección principal por persona.
            models.UniqueConstraint(
                fields=["person"],
                condition=models.Q(is_primary=True),
                name="uniq_primary_address_per_person",
                violation_error_message=_("That person already has a primary address."),
            ),
            models.CheckConstraint(
                condition=models.Q(address_type__in=AddressType.values),
                name="address_type_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.line1}, {self.locality}"


class Employee(TimeStampedModel):
    """Identidad laboral. Nodo de relaciones, **no** depósito de datos (regla 13).

    No tiene `department_id`, `position_id`, `salary` ni `manager_id`: todos son
    hechos con vigencia y viven en `contracts` (§C.4).
    """

    public_id = models.UUIDField(
        _("public ID"),
        default=uuid.uuid4,
        editable=False,
        unique=True,
        help_text=_("Used in URLs. It does not replace authorization."),
    )
    person = models.OneToOneField(
        "employees.Person",
        on_delete=models.PROTECT,
        related_name="employee",
        verbose_name=_("person"),
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee",
        verbose_name=_("account"),
        help_text=_("Empty when the employee has no access to the system."),
    )
    employee_code = models.CharField(
        _("employee code"),
        max_length=20,
        unique=True,
        help_text=_("Never reused after a termination."),
    )
    hire_date = models.DateField(_("hire date"))
    employment_status = models.CharField(
        _("employment status"),
        max_length=20,
        choices=EmploymentStatus,
        default=EmploymentStatus.ACTIVE,
    )
    termination_date = models.DateField(_("termination date"), null=True, blank=True)

    class Meta:
        verbose_name = _("employee")
        verbose_name_plural = _("employees")
        ordering = ("employee_code",)
        permissions = [
            ("view_sensitive_pii", _("Can view sensitive personal data")),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(termination_date__isnull=True)
                | models.Q(termination_date__gte=models.F("hire_date")),
                name="employee_termination_after_hire",
                violation_error_message=_("The termination date cannot precede the hire date."),
            ),
            # El estado TERMINATED y la fecha de baja van siempre juntos: uno sin
            # el otro es un dato incoherente que la base debe rechazar.
            models.CheckConstraint(
                condition=(
                    models.Q(
                        employment_status=EmploymentStatus.TERMINATED,
                        termination_date__isnull=False,
                    )
                    | (
                        ~models.Q(employment_status=EmploymentStatus.TERMINATED)
                        & models.Q(termination_date__isnull=True)
                    )
                ),
                name="employee_termination_is_consistent",
                violation_error_message=_(
                    "A terminated employee needs a termination date, and only a terminated one."
                ),
            ),
            models.CheckConstraint(
                condition=models.Q(employment_status__in=EmploymentStatus.values),
                name="employee_status_valid",
            ),
        ]
        indexes = [
            # Filtro dominante del listado principal (índice I-01).
            models.Index(fields=["employment_status"], name="employee_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_code} - {self.person.full_name}"

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return reverse("employees:detail", args=[self.public_id])

    @property
    def is_terminated(self) -> bool:
        return self.employment_status == EmploymentStatus.TERMINATED


class EmergencyContact(TimeStampedModel):
    """Contacto de emergencia.

    `full_name` aquí **no** viola 3NF: es una persona externa que no existe como
    `Person` en el sistema, así que el atributo depende solo de la clave (§B.3).
    """

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.CASCADE,
        related_name="emergency_contacts",
        verbose_name=_("employee"),
    )
    full_name = models.CharField(_("full name"), max_length=150)
    relationship = models.CharField(_("relationship"), max_length=30, choices=Relationship)
    phone = models.CharField(_("phone"), max_length=30)
    alternate_phone = models.CharField(_("alternate phone"), max_length=30, blank=True)
    priority = models.PositiveSmallIntegerField(
        _("priority"), default=1, help_text=_("1 means the first person to call.")
    )

    class Meta:
        verbose_name = _("emergency contact")
        verbose_name_plural = _("emergency contacts")
        ordering = ("priority",)
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "priority"],
                name="uniq_emergency_contact_priority",
                violation_error_message=_("That priority is already assigned."),
            ),
            models.CheckConstraint(
                condition=models.Q(priority__gte=1),
                name="emergency_contact_priority_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(relationship__in=Relationship.values),
                name="emergency_contact_relationship_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.relationship})"
