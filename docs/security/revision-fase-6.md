# Revisión de seguridad — Fase 6 (Ausencias)

- **Fecha:** 2026-09-18
- **Alcance:** `apps/leave` completo; permisos nuevos en `accounts.roles`; `justify_for_leave` y la consulta de ausencias en `attendance`; tres acciones de auditoría nuevas
- **Checklist aplicado:** [§K.9](11-seguridad.md#k9-revisión-de-seguridad-por-fase)
- **Resultado:** **aprobada**, con nueve hallazgos corregidos y tres desviaciones aceptadas. Las dos decisiones que quedaron pendientes ya las tomó el negocio y están implementadas

---

## Método

- Se leyó cada servicio preguntando **qué invariante protege y qué pasa si dos
  personas lo ejecutan a la vez**. En ausencias el riesgo típico no es leer de
  más, sino **mover días de saldo** que nadie autorizó.
- Se buscó cada dato de salud posible —tipo sensible, motivo escrito por la
  persona— y se siguió hasta cada lugar donde podía aparecer: calendario,
  bitácora, incidencias de asistencia.
- Se comparó el esquema implementado con el diseño de la Fase 0 (§B.8, §C.3):
  dos restricciones previstas no se habían declarado.
- Se probó la integración con asistencia, que la fase no mencionaba y que habría
  producido faltas falsas.

---

## Checklist

| # | Punto | Estado | Verificación |
|---|---|---|---|
| 1 | Autenticación explícita en toda vista | ✅ | `tests/security/test_url_coverage.py` cubre las 15 URLs nuevas |
| 2 | Comprobación de permiso en toda vista | ✅ | Matrices rol × vista en `leave/tests/test_views.py` |
| 3 | Todo acceso a objeto pasa por un selector | ✅ | `get_request_or_404` sobre el alcance; la solicitud nueva toma la ficha **de la sesión** |
| 4 | Sin `fields = "__all__"` | ✅ | `test_form_safety.py` |
| 5 | Sin campos de privilegio ni FK de propiedad en formularios | ✅ | El formulario de fechas no expone `employee`, `status` ni `working_days`; el de ajuste acota y excluye la propia ficha |
| 6 | Sin `\|safe` sobre datos de usuario | ✅ | `test_template_safety.py` |
| 7 | Sin JS ni CSS en línea | ✅ | Ídem |
| 8 | Cambios de estado por `POST` con CSRF | ✅ | Enviar, aprobar, rechazar y cancelar: GET solo muestra la confirmación (probado) |
| 9 | Datos sensibles fuera de logs y URLs | ✅ | El motivo nunca entra en la bitácora; los tipos sensibles no aparecen en el calendario ni en las incidencias |
| 10 | Acciones relevantes auditadas | ✅ con desviación | Envío, aprobación, rechazo, cancelación, ajuste de saldo y catálogo de tipos. El borrador no: ver D-3 |
| 11 | Tests de acceso no autorizado por vista | ✅ | Incluye `AUDITOR` intentando cancelar por `POST` |
| 12 | Test de IDOR por recurso con identificador | ✅ | Solicitud y saldo ajenos → 404 |
| 13-16 | Bandit, `pip-audit`, `detect-secrets`, `check --deploy` | ✅ | Sin hallazgos; sin dependencias nuevas |
| 17 | Errores sin información interna | ✅ | Códigos de dominio traducidos en la vista; `?type=abc` → 404 |

**Métricas:** 1522 pruebas, 93,23 % de cobertura; la app de ausencias aporta 134, incluidas las decisiones P-1 y P-2.

---

## Hallazgos

### H-1 — RRHH podía ajustar su propio saldo · **Alta** · corregido

`adjust_balance` no comparaba al actor con el titular: un `HR_ADMIN` podía
sumarse días a sí mismo, con su propio motivo como única constancia. Es el mismo
hueco de separación de funciones que la Fase 4 cerró en contratos.

**Corrección:** el servicio lo rechaza (`cannot_adjust_own_balance`) y el
formulario ya no ofrece la propia ficha.
**Pruebas:** `test_nobody_adjusts_their_own_balance`,
`test_the_adjustment_form_does_not_offer_your_own_record`.

### H-2 — Dos borradores traslapados podían enviarse ambos · **Media** · corregido

El traslape (RN-41) se validaba al **crear**, pero los borradores no ocupan
calendario: dos borradores sobre las mismas fechas eran válidos, y enviarlos uno
tras otro dejaba dos solicitudes vigentes superpuestas.

**Corrección:** el envío revalida el traslape.
**Prueba:** `test_two_overlapping_drafts_cannot_both_be_submitted`.

### H-3 — Condiciones de carrera sobre el calendario y el saldo · **Media** · corregido

El envío y la aprobación bloqueaban solo **su** solicitud. Dos aprobaciones
simultáneas de solicitudes distintas de la misma persona leían el mismo saldo y
podían dejarlo negativo (RN-43); dos envíos simultáneos, saltarse H-2.

**Corrección:** `_lock_requests_of` bloquea todas las solicitudes de la persona
antes de leer calendario o saldo. En SQLite es inocuo; en PostgreSQL serializa.

### H-4 — Las escrituras masivas saltaban el libro append-only · **Media** · corregido

`save()` y `delete()` del asiento rechazaban modificar, pero
`LeaveLedgerEntry.objects.filter(...).update()` y `.delete()` no pasan por
ellos.

**Corrección:** `QuerySet` propio que los bloquea, igual que la bitácora
(ADR-008, ADR-015).
**Prueba:** `test_bulk_writes_cannot_bypass_the_guard`.

### H-5 — Una ausencia aprobada generaba faltas de asistencia · **Media (datos)** · corregido

El cierre diario de asistencia no consultaba ausencias: cada día de vacaciones
aprobadas abría una incidencia de **ausencia**, que llegaría a la planilla.

**Corrección:** el cierre no abre faltas en días de ausencia aprobada, y al
aprobar se justifican las que el cierre ya hubiera abierto (incapacidad pedida
el mismo día). La justificación cita el identificador de la solicitud, **nunca
el tipo ni el motivo**, porque la jefatura ve las incidencias.
**Pruebas:** `leave/tests/test_attendance_integration.py`.

### H-6 — Cancelar una solicitud aprobada rompía una restricción · **Media** · corregido

La restricción `leave_decision_is_consistent` exigía que todo estado no decidido
tuviera `decided_at` nulo. Una solicitud aprobada y luego cancelada conserva
—con razón— la constancia de su aprobación, así que **cancelar fallaba siempre**.

**Lo detectó una prueba.** La restricción ahora distingue: pendiente ⇒ sin
decisión; decidida ⇒ con decisión; cancelada ⇒ cualquiera. Migración `0002`.

### H-7 — El catálogo de tipos se editaba sin rastro · **Media** · corregido

Cambiar los días anuales o la marca de «sensible» afecta a toda la organización,
y la vista guardaba el formulario directamente, sin servicio ni bitácora.

**Corrección:** `create_leave_type` y `update_leave_type`, auditados con el antes
y el después (`LEAVE_TYPE_CREATE`, `LEAVE_TYPE_UPDATE`).

### H-8 — Restricciones del diseño que no se habían declarado · **Baja** · corregido

El diseño (§B.8) preveía que el signo de un asiento fuera coherente con su tipo y
que una transición cambiara de estado. Ninguna existía, y la creación se
registraba como `DRAFT → DRAFT`. Migración `0003`; la creación es ahora
`«» → DRAFT`.

### H-9 — Errores menores de la capa web · **Baja** · corregidos

- `?type=abc` en el asistente producía un error 500 en lugar de 404.
- El botón «Cancelar solicitud» se mostraba a quien no podía usarlo, y la vista
  solo exigía permiso de lectura. Ahora exige `add_leaverequest` y el botón
  depende de quién mira y en qué estado está la solicitud.

---

## Desviaciones aceptadas

### D-1 — Quien decide ve el tipo y el motivo

El calendario oculta los tipos sensibles, pero la bandeja y el detalle no: sin el
tipo no se puede decidir. Mitigaciones: el motivo es opcional, el formulario pide
**no incluir detalles médicos**, y la bitácora nunca lo guarda.

### D-2 — El calendario de un `EMPLOYEE` muestra solo sus ausencias

El alcance de ausencias es el de la ficha (`employees_visible_for`), y un
`EMPLOYEE` solo se ve a sí mismo. Mostrarle las ausencias del equipo exigiría un
alcance nuevo, más amplio que el de la ficha. No se abre sin un caso concreto.

### D-3 — El borrador no se audita

No tiene efecto sobre nadie hasta que se envía, y el envío sí se audita. La
transición de creación queda igualmente registrada en la solicitud.

---

## Decisiones del negocio tomadas tras la revisión

| # | Decisión | Controles de seguridad |
|---|---|---|
| P-1 | **Sí se registran ausencias con fecha pasada**, hasta el tope que declare cada tipo (0 a 30 días) — [ADR-022 §5](../decisions/ADR-022-reglas-de-ausencias.md) | La base de datos impide combinar preaviso y retroactivo; el plazo se revalida al enviar; la bitácora registra `backdated_days` en cada envío y decisión |
| P-2 | **Los días crecen con la antigüedad**, con la base del tipo como piso legal — [ADR-022 §6](../decisions/ADR-022-reglas-de-ausencias.md) | Solo `HR_ADMIN` gestiona los tramos; cada alta o baja se audita; un tramo nunca otorga menos que la base ni que uno menor |

**Riesgo nuevo que introduce P-1:** el registro retroactivo permite convertir en
ausencia justificada una falta ya ocurrida. Mitigaciones: sigue exigiendo
aprobación de otra persona (RN-44), el tope lo fija RRHH por tipo, y la bitácora
deja constancia de cuántos días tarde se registró.

---

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| `accrue_leave` sin programar: nadie acumula días | **Bloqueante para producción**, junto con `close_attendance_day` y `expire_contracts` |
| `requires_document` existe en el tipo, pero no hay dónde adjuntar | Llega con la Fase 7 (documentos) |
| Caducidad de saldos (`EXPIRY`) | Prevista en el diseño; ninguna política la exige hoy |
| Códigos de activación y alta por lotes | Separados de esta fase (ADR-022 §4); siguen pendientes |
| `MINIMUM_MONTHLY_SALARY` y el algoritmo del NIT | Heredados; siguen siendo bloqueantes |
