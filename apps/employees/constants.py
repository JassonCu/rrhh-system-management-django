"""Conjuntos cerrados del dominio de personas y empleados.

Los **valores** son ASCII estable y no se traducen: entran en `CheckConstraint`,
consultas y auditoría. Solo se traduce la etiqueta (§O.3.1).
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Gender(models.TextChoices):
    FEMALE = "FEMALE", _("Female")
    MALE = "MALE", _("Male")
    OTHER = "OTHER", _("Other")
    UNDISCLOSED = "UNDISCLOSED", _("Prefer not to say")


class MaritalStatus(models.TextChoices):
    SINGLE = "SINGLE", _("Single")
    MARRIED = "MARRIED", _("Married")
    DIVORCED = "DIVORCED", _("Divorced")
    WIDOWED = "WIDOWED", _("Widowed")
    PARTNERED = "PARTNERED", _("Domestic partnership")
    UNDISCLOSED = "UNDISCLOSED", _("Prefer not to say")


class DocumentType(models.TextChoices):
    """Tipos de documento de identificación.

    El catálogo asume jurisdicción de Guatemala (supuesto S-01). Añadir un tipo
    de otro país es una migración local: por eso los documentos viven en su
    propia relación y no como columnas de `Person` (§D.3).
    """

    DPI = "DPI", _("National ID (DPI/CUI)")
    NIT = "NIT", _("Tax ID (NIT)")
    IGSS = "IGSS", _("Social security number (IGSS)")
    PASSPORT = "PASSPORT", _("Passport")
    DRIVER_LICENSE = "DRIVER_LICENSE", _("Driver's license")


class ContactType(models.TextChoices):
    MOBILE = "MOBILE", _("Mobile phone")
    LANDLINE = "LANDLINE", _("Landline")
    PERSONAL_EMAIL = "PERSONAL_EMAIL", _("Personal email")
    WORK_EMAIL = "WORK_EMAIL", _("Work email")


class AddressType(models.TextChoices):
    HOME = "HOME", _("Home")
    MAILING = "MAILING", _("Mailing")


class Relationship(models.TextChoices):
    SPOUSE = "SPOUSE", _("Spouse or partner")
    PARENT = "PARENT", _("Parent")
    CHILD = "CHILD", _("Child")
    SIBLING = "SIBLING", _("Sibling")
    FRIEND = "FRIEND", _("Friend")
    OTHER = "OTHER", _("Other")


class EmploymentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    ON_LEAVE = "ON_LEAVE", _("On leave")
    SUSPENDED = "SUSPENDED", _("Suspended")
    TERMINATED = "TERMINATED", _("Terminated")


#: Edad mínima para ser contratado (RN-04). Parámetro, no constante mágica: la
#: legislación admite excepciones para menores con autorización.
MINIMUM_WORKING_AGE = 18

#: Fecha de nacimiento más antigua admisible. Existe para que un error de
#: captura evidente (año 1080 en vez de 1980) no entre a la base.
EARLIEST_BIRTH_YEAR = 1900
