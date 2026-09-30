# ADR-002 — SQLite como motor de desarrollo inicial

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1

---

## Contexto

El encargo fija SQLite como motor inicial y PostgreSQL como destino. Todavía no
existe entorno de producción ni decisión de plataforma (Fase 9).

SQLite no es solo «PostgreSQL más pequeño»: le faltan capacidades que este
modelo de datos usa de forma deliberada.

| Capacidad | SQLite | Impacto en este diseño |
|---|---|---|
| `ExclusionConstraint` con rangos | No | Las reglas de **no traslape** (RN-14, RN-21, RN-41, RN-51) quedan en la capa de servicio |
| Validación de precisión en `DECIMAL` | **No valida** | Un importe mal escalado pasaría desapercibido hasta producción |
| Integridad referencial | Desactivada por defecto | Sin `PRAGMA foreign_keys=ON`, `PROTECT` y `CASCADE` **no se aplican** |
| Búsqueda de texto completo portable | FTS5, no portable | La búsqueda usa `icontains` hasta migrar |
| Tipos `uuid`, `jsonb`, `timestamptz` | Emulados | Django lo abstrae; no se usan operadores específicos |
| Concurrencia de escritura | Un escritor | Irrelevante en desarrollo, inviable en producción |

## Alternativas consideradas

### A. PostgreSQL desde el primer día (contenedor local)
- **A favor:** un solo motor, sin divergencias; las reglas de no traslape serían
  declarativas desde el inicio.
- **En contra:** exige Docker o un servicio instalado en cada máquina antes de
  poder ejecutar una prueba. En un equipo mixto Windows/Linux eso es fricción
  real en el arranque, y el encargo pide explícitamente SQLite al principio.

### B. SQLite en desarrollo, PostgreSQL en CI y producción *(elegida)*
- **A favor:** `git clone && pip install && migrate` y a trabajar; suite de
  pruebas en memoria, muy rápida.
- **En contra:** hay dos motores, y con ellos el riesgo de que algo funcione en
  uno y no en el otro.

### C. SQLite también en producción
- **Rechazada.** Un solo escritor concurrente y ninguna de las restricciones
  declarativas que este modelo necesita. No es un motor adecuado para datos
  laborales y de nómina con varios usuarios simultáneos.

## Decisión

Se adopta **B**, con tres mitigaciones que convierten el riesgo en algo
detectable en lugar de latente:

1. **`PRAGMA foreign_keys=ON`** en las `OPTIONS` de la conexión SQLite. Sin él,
   toda la política de borrado del [documento de integridad](../database/07-integridad-e-indices.md)
   sería decorativa.
2. **La suite completa corre también contra PostgreSQL en CI**, en un trabajo
   propio, desde la Fase 1. Es barato ahora y detecta las divergencias el día que
   se introducen.
3. **`DATABASE_URL`** conmuta el motor sin tocar código, de modo que cualquiera
   puede reproducir el entorno de CI en local.

## Consecuencias

### Positivas
- Arranque sin infraestructura; pruebas en memoria muy rápidas.
- El desarrollo no se bloquea por una decisión de plataforma aún no tomada.

### Negativas aceptadas
- Las reglas de no traslape viven en `services.py` y no en la base, así que una
  escritura que esquive el servicio podría violarlas. Se compensa con pruebas de
  frontera y con la promoción a `ExclusionConstraint` prevista en ADR-003.
- SQLite no valida la precisión decimal: **los cálculos monetarios deben
  probarse contra PostgreSQL antes de cualquier despliegue**.

### Qué habría que hacer para revertirla
Cambiar `DATABASE_URL`. Esa es toda la reversión, y es intencional.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| El PRAGMA de claves foráneas está configurado | `tests/test_settings_contract.py::test_sqlite_enforces_foreign_keys` |
| `PROTECT` realmente protege | `apps/core/tests/test_models.py::test_company_cannot_be_deleted_while_referenced` |
| `DATABASE_URL` resuelve PostgreSQL | `tests/test_settings_contract.py::test_database_url_supports_postgresql` |
| Un esquema no soportado falla ruidosamente | `tests/test_settings_contract.py::test_unsupported_database_scheme_fails_loudly` |
| La suite se comporta igual en ambos motores | Trabajo `test-postgres` del CI |
