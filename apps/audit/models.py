"""Bitácora de auditoría: **append-only**.

Decisiones de diseño (docs/database/02-modelo-relacional.md §B.11):

* ``actor`` usa ``SET_NULL``. Con ``CASCADE``, borrar un usuario borraría su
  rastro — justo lo que buscaría un atacante con acceso al admin.
* ``actor_repr`` y ``object_repr`` son *snapshots*: el evento debe seguir siendo
  legible cuando el objeto ya no existe (RN-71).
* ``object_type``/``object_id`` son punteros **débiles**, no una
  ``GenericForeignKey``: la auditoría registra hechos pasados, no referencias
  vivas, y no debe acoplarse al ciclo de vida de lo auditado.
* ``metadata`` es el único ``JSONField`` legítimo del sistema: un diff cuya forma
  varía según el tipo de objeto y que no se consulta relacionalmente (§D.3).
"""

from __future__ import annotations

from typing import Any, NoReturn

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.audit.constants import AuditAction, AuditOutcome
from apps.core.exceptions import DomainError


class AuditLogImmutableError(DomainError):
    """Se intentó modificar o borrar un evento ya registrado."""

    default_code = "audit_log_is_append_only"


class AuditEventQuerySet(models.QuerySet):
    """Bloquea las escrituras masivas que saltarían ``Model.save``."""

    def update(self, **kwargs: Any) -> NoReturn:
        raise AuditLogImmutableError(fields=sorted(kwargs))

    def delete(self) -> NoReturn:
        raise AuditLogImmutableError(operation="queryset_delete")


class AuditEvent(models.Model):
    """Un hecho registrado. Se escribe una vez y no se toca nunca más."""

    occurred_at = models.DateTimeField(
        _("occurred at"), default=timezone.now, editable=False, db_index=True
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name=_("actor"),
        help_text=_("Null when the action was performed by the system."),
    )
    actor_repr = models.CharField(
        _("actor (snapshot)"),
        max_length=150,
        help_text=_("Textual actor at the time of the event; survives account deletion."),
    )
    action = models.CharField(_("action"), max_length=40, choices=AuditAction)
    object_type = models.CharField(
        _("object type"),
        max_length=60,
        blank=True,
        help_text=_("Weak pointer in app_label.ModelName form. Not a foreign key."),
    )
    object_id = models.CharField(_("object ID"), max_length=40, blank=True)
    object_repr = models.CharField(_("object (snapshot)"), max_length=200, blank=True)
    outcome = models.CharField(
        _("outcome"), max_length=10, choices=AuditOutcome, default=AuditOutcome.SUCCESS
    )
    ip_address = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.CharField(_("user agent"), max_length=255, blank=True)
    request_id = models.UUIDField(
        _("request ID"),
        null=True,
        blank=True,
        help_text=_("Correlates this event with the application logs."),
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        blank=True,
        help_text=_("Filtered diff. Never contains credentials or personal identifiers."),
    )

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        verbose_name = _("audit event")
        verbose_name_plural = _("audit events")
        ordering = ("-occurred_at", "-id")
        # No se generan los permisos change/delete: así no existe ni la
        # posibilidad de concedérselos a un grupo por descuido (§J.3).
        default_permissions = ("add", "view")
        permissions = [("view_audit_log", _("Can browse the audit log"))]
        indexes = [
            models.Index(fields=["actor", "-occurred_at"], name="audit_actor_time_idx"),
            models.Index(fields=["object_type", "object_id"], name="audit_object_idx"),
            models.Index(fields=["action", "-occurred_at"], name="audit_action_time_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(outcome__in=AuditOutcome.values),
                name="audit_outcome_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=AuditAction.values),
                name="audit_action_valid",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.occurred_at.isoformat()} {self.action} {self.outcome}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AuditLogImmutableError(pk=self.pk)
        super().save(*args, **kwargs)

    def delete(self, *_args: Any, **_kwargs: Any) -> NoReturn:
        raise AuditLogImmutableError(pk=self.pk)
