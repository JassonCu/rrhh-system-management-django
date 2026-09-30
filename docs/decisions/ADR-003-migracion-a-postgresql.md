# ADR-003 — Estrategia de migración a PostgreSQL

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1 (restricciones) · 9 (ejecución)

---

## Contexto

ADR-002 fija SQLite en desarrollo y PostgreSQL como destino. Una migración de
motor sale barata o carísima según lo que se haya escrito antes, y esa
diferencia se decide **hoy**, no el día de migrar.

Este ADR define qué se prohíbe ahora para que la migración sea un cambio de
configuración y no una reescritura, y qué mejoras se activarán al llegar.

## Alternativas consideradas

### A. Migrar cuando toque, sin restricciones previas
- **En contra:** es como se acumulan las migraciones imposibles. Consultas con
  SQL específico, dependencias de la laxitud de tipos de SQLite y búsquedas con
  FTS5 aparecen sin que nadie lo note hasta que ya son muchas.

### B. Restricciones explícitas desde el primer commit *(elegida)*
Prohibir hoy lo que no sea portable, y verificar la portabilidad de forma
continua en CI.

### C. Capa de abstracción propia sobre el ORM
- **Rechazada.** El ORM de Django **ya es** esa capa. Envolverlo añadiría una
  indirección que hay que mantener, y la regla 56 desaconseja abstracciones
  prematuras.

## Decisión

Se adopta **B**.

### Lo que se prohíbe desde ahora

| Prohibido | Motivo |
|---|---|
| `raw()`, `extra()`, `RawSQL` sin aprobación en revisión | Es la vía por la que entra SQL específico de motor |
| Funciones propias de SQLite (`strftime`, `julianday`, FTS5) | No existen en PostgreSQL |
| Operadores JSON específicos de un motor | `JSONField` se usa solo para leer y escribir el documento completo |
| Modificar la base a mano | Toda estructura pasa por migraciones de Django (regla 26) |
| Depender de la laxitud de tipos de SQLite | PostgreSQL sí valida: lo que hoy «funciona» puede fallar allí |

### Lo que se activa al migrar

| Área | Hoy (SQLite) | Tras migrar |
|---|---|---|
| No traslape (RN-14, RN-21, RN-41, RN-51) | Validación en `services.py` + pruebas de frontera | `ExclusionConstraint` con `daterange` y `btree_gist`. **La validación de servicio se conserva**: da los mensajes de error legibles y es defensa en profundidad |
| Unicidad de correo insensible a mayúsculas | Normalización a minúsculas en `save()` | Se puede reforzar con `UniqueConstraint` sobre `Lower("email")` o `CITEXT` |
| Búsqueda | `icontains` | `SearchVector` + índice GIN |
| Auditoría de gran volumen | Tabla única | Particionado por fecha si la medición lo exige |
| Conexiones | — | `CONN_MAX_AGE` ya contemplado en el parser de `DATABASE_URL` |

### Procedimiento de migración (Fase 9)

1. Levantar PostgreSQL y apuntar `DATABASE_URL`.
2. `migrate` sobre base vacía — debe funcionar sin intervención manual.
3. Migrar los datos con `dumpdata`/`loaddata` o con una carga directa, según
   volumen.
4. Añadir las `ExclusionConstraint` en una migración propia, **después** de
   verificar que los datos existentes no las violan.
5. Revisar los planes de ejecución de las consultas de los listados principales.

## Consecuencias

### Positivas
- La migración es un cambio de variable de entorno más una migración de datos.
- Las divergencias entre motores aparecen el día que se introducen, no al final.

### Negativas aceptadas
- El CI es más lento y más caro por el trabajo de PostgreSQL.
- Renunciar a `raw()` puede obligar a expresar alguna consulta compleja de forma
  menos directa. Se acepta; si aparece un caso real, se discute en revisión.

### Qué habría que hacer para revertirla
Volver a SQLite en producción no es una opción realista (ver ADR-002, opción C).
Lo reversible es la restricción sobre `raw()`, que se levanta caso por caso.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| La suite pasa en PostgreSQL igual que en SQLite | Trabajo `test-postgres` del CI |
| Las migraciones aplican sobre base vacía | Trabajo `django-checks` del CI |
| No hay modelos sin migración | `makemigrations --check --dry-run`, en CI y en pre-commit |
| `DATABASE_URL` produce la configuración correcta | `tests/test_settings_contract.py` |
| No entra SQL específico de motor | Revisión de PR + Bandit sobre construcción de SQL |
