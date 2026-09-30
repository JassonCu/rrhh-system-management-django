# ADR-008 — Auditoría append-only con punteros débiles y snapshots

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1

---

## Contexto

Un sistema de RRHH necesita responder «quién cambió este salario y cuándo» años
después, incluso si el empleado ya no está, el usuario que lo hizo fue dado de
baja y el contrato fue terminado.

La bitácora tiene además una propiedad incómoda: **es el registro que vigila a
quienes administran el sistema**. Si un administrador puede editarla o borrarla,
no sirve para lo que existe.

## Alternativas consideradas

### A. Una librería de historial (`django-simple-history`, `django-auditlog`)
Versiona automáticamente cada modelo registrado.

- **A favor:** cero esfuerzo por modelo; historial campo a campo.
- **En contra:** registra **cambios de fila**, no **hechos de negocio**. No sabe
  distinguir «se aprobó una ausencia» de «cambió una columna de estado», ni
  puede registrar un `DOCUMENT_DOWNLOAD`, un `PERMISSION_DENIED` o un
  `LOGIN_FAILED`, que no modifican ninguna fila y son justamente los eventos de
  seguridad que importan. Además duplica el esquema con una tabla espejo por
  modelo.

### B. `GenericForeignKey` hacia el objeto auditado
- **En contra:** una FK real a `ContentType` no impide que el objeto desaparezca
  —el evento quedaría apuntando al vacío o arrastrado por un `CASCADE`—, acopla
  la bitácora al ciclo de vida de lo auditado y complica el particionado futuro.

### C. Puntero débil + snapshots textuales *(elegida)*
`object_type` (`"app.Model"`) y `object_id` como texto, más `object_repr` y
`actor_repr` congelados en el momento del evento.

- **A favor:** el evento sobrevive al borrado de cualquier cosa; sigue siendo
  legible sin `JOIN`; no impone integridad referencial donde no debe haberla.
- **En contra:** se renuncia a la garantía de que el objeto referenciado exista.
  Es deliberado: **la auditoría registra hechos pasados, no referencias vivas.**

### D. Inmutabilidad por triggers de base de datos
- **Rechazada por ahora.** SQLite y PostgreSQL exigen sintaxis distinta, y los
  triggers quedan fuera de las migraciones de Django. Se reconsiderará al migrar
  a PostgreSQL, como refuerzo —no sustituto— del control de aplicación.

## Decisión

Se adopta **C**, con estos elementos:

1. **Append-only en el modelo.** `save()` rechaza cualquier actualización,
   `delete()` lanza, y el `QuerySet` propio bloquea `update()` y `delete()`
   masivos — el camino que saltaría por encima de `Model.save`.
2. **Los permisos `change` y `delete` no se generan.**
   `default_permissions = ("add", "view")`: no basta con no concederlos, es que
   no existen para poder concederlos por descuido.
3. **`actor` con `SET_NULL`.** Con `CASCADE`, borrar un usuario borraría su
   rastro: exactamente lo que buscaría un atacante con acceso al admin.
4. **Snapshots de actor y objeto**, para que el evento siga siendo legible.
5. **Catálogo cerrado de acciones** con `CheckConstraint`, no texto libre.
6. **Depuración obligatoria de `metadata`** antes de persistir: la bitácora no
   puede convertirse en el lugar donde acaban las contraseñas que el resto del
   sistema protege (RN-72).
7. **Un único punto de entrada**, `audit.services.record()`, para que la
   depuración y el snapshot ocurran siempre.
8. **El admin es de solo lectura**, reforzando en la interfaz lo que el modelo
   ya impide.

## Consecuencias

### Positivas
- La bitácora registra hechos de negocio y de seguridad, no diffs de filas.
- Sobrevive al borrado de usuarios, objetos y contratos.
- Un administrador no puede alterarla desde la aplicación.

### Negativas aceptadas
- Cada evento hay que emitirlo explícitamente desde el servicio correspondiente:
  no hay automatismo, y **olvidarlo es posible**. Se compensa exigiendo la
  emisión en el checklist de seguridad de cada fase y probándola por caso de uso.
- Sin integridad referencial hacia el objeto, un `object_id` puede apuntar a algo
  que ya no existe. Es el precio de que el evento sobreviva, y `object_repr` lo
  mitiga.
- Un superusuario con acceso a la consola de base de datos sigue pudiendo
  manipularla. Ninguna medida de aplicación resuelve eso; se aborda con control
  de acceso a la infraestructura.
- La tabla solo crece. El particionado queda para cuando el volumen lo pida.

### Qué habría que hacer para revertirla
Cambiar a una librería de historial obligaría a reinterpretar los eventos ya
registrados, que no tienen equivalente en un modelo de diffs. En la práctica, no
es reversible sin perder información.

## Cómo se verifica

`apps/audit/tests/` cubre cada punto de la decisión:

| Verificación | Prueba |
|---|---|
| Un evento existente no se puede modificar | `test_existing_event_cannot_be_modified` |
| Un evento no se puede borrar | `test_event_cannot_be_deleted` |
| `update()` masivo bloqueado | `test_queryset_update_is_blocked` |
| `delete()` masivo bloqueado | `test_queryset_delete_is_blocked` |
| Los permisos `change`/`delete` **no existen** | `test_change_and_delete_permissions_do_not_exist` |
| El evento sobrevive al borrado del actor | `test_event_survives_actor_deletion` |
| Ningún secreto se persiste en `metadata` | `test_record_never_persists_a_secret` |
| La depuración es recursiva | `test_redaction_is_recursive` |
| La IP no se puede falsificar sin proxy declarado | `test_forwarded_for_is_ignored_without_a_trusted_proxy` |
| `__str__` no cambia con el idioma (la bitácora debe ser buscable) | `test_str_is_not_translated` |
