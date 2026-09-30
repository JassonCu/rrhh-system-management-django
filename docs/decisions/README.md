# N. Architecture Decision Records (ADR)

Se documenta como ADR toda decisión que sea **costosa de revertir**, que cierre
alternativas razonables o que alguien vaya a cuestionar en seis meses. **No** se
escribe un ADR para decisiones triviales (regla 54).

Los ADR son inmutables: no se editan para cambiar de opinión. Se marcan como
`Superseded by ADR-NNN` y se escribe uno nuevo.

---

## Índice propuesto

Estado: `Propuesto` · `Aceptado` · `Diferido` · `Rechazado` · `Sustituido`.

**Veintiuno aceptados.** Los `Propuesto` corresponden a
decisiones que se tomarán al abrir su fase: escribirlos antes sería inventar el
contexto.

| ADR | Título | Estado | Fase | Por qué merece un ADR |
|---|---|---|---|---|
| **[001](ADR-001-monolito-modular.md)** | Monolito modular en lugar de microservicios | **Aceptado** | 1 | Determina la topología del sistema y el costo de todo cambio futuro |
| **[002](ADR-002-sqlite-inicial.md)** | SQLite en desarrollo inicial | **Aceptado** | 1 | Se acepta perder `ExclusionConstraint` y búsqueda de texto completo a cambio de arrancar sin infraestructura |
| **[003](ADR-003-migracion-a-postgresql.md)** | Estrategia de migración a PostgreSQL | **Aceptado** | 1 | Fija qué se prohíbe hoy (SQL específico de motor) para que la migración sea barata mañana |
| **[004](ADR-004-alta-de-cuentas-y-registro-cerrado.md)** | Alta de cuentas: invitación + código de activación, **registro público cerrado** | **Aceptado** | 2 y 6 | Decisión de seguridad estructural: sin ella, la superficie de ataque cambia por completo |
| **[005](ADR-005-autorizacion-por-selectores.md)** | Autorización por selectores con alcance, sin django-guardian | **Aceptado** | 1 y 3 | Es el mecanismo antiIDOR del sistema entero; la alternativa (ACL por fila) es difícil de revertir |
| **[006](ADR-006-normalizacion-objetivo-bcnf.md)** | Normalización objetivo: BCNF, con excepciones documentadas | **Aceptado** | 0 | Fija el criterio con el que se evalúa cada modelo futuro |
| **[007](ADR-007-csp-estricta-con-nonce.md)** | CSP estricta con nonce (django-csp), sin `unsafe-inline` | **Aceptado** | 1 | Condiciona cómo se escribe **todo** el frontend desde el primer commit |
| **[008](ADR-008-auditoria-append-only.md)** | Auditoría append-only con punteros débiles | **Aceptado** | 1 | Se renuncia deliberadamente a la integridad referencial en `AuditEvent`; hay que explicar por qué |
| **[009](ADR-009-capas-services-y-selectors.md)** | Capas `services` / `selectors` sin repositorios ni DI | **Aceptado** | 1 | Justifica por qué se añade estructura y, sobre todo, **dónde se para** |
| **[010](ADR-010-entidad-company-desde-el-inicio.md)** | Entidad `Company` desde el inicio (multi-empresa anticipada) | **Aceptado** | 1 | Es la única decisión de esquema cuyo retrofit resulta desproporcionadamente caro |
| **[011](ADR-011-position-pertenece-a-departamento.md)** | `Position` **pertenece a un departamento** | **Aceptado** | 3 | Determinaba si `Assignment.department_id` era correcto o una violación de 3NF. Lo resolvió un hecho del dominio, no una preferencia |
| **[012](ADR-012-estado-laboral-materializado.md)** | `Employee.employment_status` como estado derivado materializado | **Aceptado** | 4 | Excepción consciente al principio de no duplicar: un único escritor (`contracts.services`) y una invariante verificable por comando |
| **[013](ADR-013-argon2-como-hasher.md)** | Argon2 como hasher de contraseñas | **Aceptado** | 1 | Añade una dependencia; debe justificarse frente al PBKDF2 por defecto |
| **[014](ADR-014-historial-temporal.md)** | Historial temporal (jefaturas, salarios, asignaciones) frente a columnas mutables | **Aceptado** | 3 y 4 | Multiplica las tablas y las consultas; la continuidad y el no traslape viven en servicios porque SQLite no tiene `ExclusionConstraint` |
| **[015](ADR-015-ledger-de-ausencias.md)** | Libro de ausencias (ledger) en lugar de campo `balance` | **Aceptado** | 6 | Elección de modelo contable frente a estado mutable; el libro es append-only incluso ante escrituras masivas |
| **016** | Snapshots en nómina y auditoría como redundancia justificada | Propuesto | 8 | Define el criterio que autoriza duplicar y evita que se abuse de él |
| **017** | SSO corporativo (OIDC/SAML) como evolución de ADR-004 | Diferido | 9 | Alternativa F de ADR-004: se difiere sin bloquearla. Reabrir cuando exista un IdP corporativo confirmado |
| **[018](ADR-018-estrategia-de-internacionalizacion.md)** | Estrategia de internacionalización | **Aceptado** | 1 | Fija `msgid` en inglés, datos en un solo idioma y formatos propios de Guatemala. Cambiar cualquiera de las tres después obliga a tocar todo el código visible |
| **[019](ADR-019-acceso-movil.md)** | Acceso móvil: web responsive ahora, API con `allauth.headless` para app nativa después | **Aceptado** | UX y 10 | Fija las reglas de seguridad de una API futura antes de que exista, y obliga a no sacar lógica de `services` desde hoy |
| **[020](ADR-020-css-propio.md)** | Sistema de diseño con CSS propio en capas, sin framework CSS | **Aceptado** | UX-1 | Condiciona cómo se escribe todo el frontend; adoptar un framework después obliga a reescribir las plantillas |
| **[021](ADR-021-reglas-de-asistencia.md)** | Asistencia: tolerancia por jornada, horas extra por aprobación y sin geolocalización | **Aceptado** | 5 | Reglas de negocio con impacto en el esquema y en la clasificación de los datos; el roadmap las exigía antes de construir la fase |
| **[022](ADR-022-reglas-de-ausencias.md)** | Ausencias: devengo proporcional, aprobación que sube por el organigrama y tipos sensibles ocultos | **Aceptado** | 6 | Fija quién decide sobre quién y qué ve el equipo de una ausencia médica |
| **[023](ADR-023-expediente-documental.md)** | Expediente: archivo privado, nombre generado y archivado en vez de borrado | **Aceptado** | 7 | Decide dónde viven los archivos y quién puede hacerlos desaparecer; cambiar cualquiera de las dos cosas después es caro |

### Candidatos que **no** llevan ADR

Por triviales o por ser consecuencia directa de otra decisión: uso de Ruff en
lugar de black+flake8, elección de `pytest` sobre el runner de Django, nombres de
directorios, `line-length = 100`, uso de `BigAutoField`.

---

## Plantilla

Archivo: `docs/decisions/ADR-NNN-titulo-en-kebab-case.md`

```markdown
# ADR-NNN — Título

- **Estado:** Propuesto | Aceptado | Rechazado | Sustituido por ADR-MMM
- **Fecha:** AAAA-MM-DD
- **Decide:** rol o persona
- **Fase:** N

## Contexto

Qué problema existe, qué restricciones aplican y qué se sabe hoy.
Sin justificar todavía nada.

## Alternativas consideradas

### A. <nombre>
Ventajas / inconvenientes / costo de revertir.

### B. <nombre>
Ventajas / inconvenientes / costo de revertir.

## Decisión

Qué se elige y **por qué esa y no las otras**.

## Consecuencias

### Positivas
### Negativas (las que se aceptan a sabiendas)
### Qué habría que hacer para revertirla

## Cómo se verifica

Test, chequeo de CI o revisión que demuestra que la decisión sigue vigente.
```

El apartado **"Cómo se verifica"** es obligatorio y es lo que distingue estos ADR
de un acta: una decisión sin mecanismo de verificación se erosiona en silencio.
