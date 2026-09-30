# Revisión de seguridad — Fase 5 (Asistencia)

- **Fecha:** 2026-09-17
- **Alcance:** `apps/attendance` completo; permisos nuevos en `accounts.roles`; selectores añadidos en `contracts`
- **Checklist aplicado:** [§K.9](11-seguridad.md#k9-revisión-de-seguridad-por-fase)
- **Resultado:** **aprobada**, con dos hallazgos corregidos, tres desviaciones aceptadas y un límite documentado

---

## Método

- Se leyó cada vista preguntando **de dónde sale el sujeto**: quién marca, a
  quién se ajusta, qué incidencia se resuelve. En asistencia el riesgo típico no
  es leer de más, sino **escribir en el registro de otra persona**.
- Se revisó qué datos entran en la bitácora y cuáles no, y por qué.
- Se comprobó el alcance reutilizado: los selectores de asistencia se apoyan en
  `employees_visible_for`, así que se verificó que un `EMPLOYEE` no vea a nadie
  más y un `MANAGER` solo a su equipo.
- Se buscaron datos sensibles nuevos: la asistencia dice a qué hora entra y sale
  cada persona. **No** se guarda ubicación (ADR-021).

---

## Checklist

| # | Punto | Estado | Verificación |
|---|---|---|---|
| 1 | Autenticación explícita en toda vista | ✅ | `tests/security/test_url_coverage.py` cubre las 9 URLs nuevas |
| 2 | Comprobación de permiso en toda vista | ✅ | Matriz rol × vista en `attendance/tests/test_authorization.py` |
| 3 | Todo acceso a objeto pasa por un selector | ✅ | `get_entry_or_404` y `get_incident_or_404` sobre el alcance; el marcaje resuelve la ficha **desde la sesión** |
| 4 | Sin `fields = "__all__"` | ✅ | `test_form_safety.py` |
| 5 | Sin campos de privilegio ni FK de propiedad en formularios | ✅ | Ningún formulario expone `employee`, `source` ni `registered_by` |
| 6 | Sin `\|safe` sobre datos de usuario | ✅ | `test_template_safety.py` |
| 7 | Sin JS ni CSS en línea | ✅ | Ídem |
| 8 | Cambios de estado por `POST` con CSRF | ✅ | El marcaje solo acepta `POST` (prueba 405); ajustes y resoluciones, formulario con CSRF |
| 9 | Datos sensibles fuera de logs y URLs | ✅ | Sin coordenadas; la bitácora del ajuste lleva horas y motivo, no datos personales |
| 10 | Acciones relevantes auditadas | ✅ con desviación | Ajuste, resolución de incidencia, alta y asignación de jornada. El marcaje **no** se audita: ver D-1 |
| 11 | Tests de acceso no autorizado por vista | ✅ | Incluye `AUDITOR` intentando resolver por `POST` |
| 12 | Test de IDOR por recurso con identificador | ✅ | Marcaje ajeno → 403/404 según el permiso que falte primero |
| 13-16 | Bandit, `pip-audit`, `detect-secrets`, `check --deploy` | ✅ | Sin hallazgos |
| 17 | Errores sin información interna | ✅ | Códigos de dominio traducidos en la vista |

**Métricas:** 1260 pruebas, 93,0 % de cobertura. La app de asistencia aporta 80.

---

## Hallazgos

### H-1 — La salida temprana se marcaba al volver del almuerzo · **Media (corrección de datos)** · corregido

El primer diseño evaluaba el día al cerrar **cada** segmento. En una jornada
partida, cerrar a las 12:00 abría una incidencia de «salida temprana» de cuatro
horas: un dato falso que además alimentaría la planilla.

**Lo detectó una prueba**, no una revisión visual.

**Corrección:** el exceso se detecta al instante, porque se sabe; el defecto solo
al cerrar el día, con `close_day` y el comando `close_attendance_day`. Una
jornada partida ya no genera nada raro.
**Pruebas:** `test_leaving_early_is_only_known_once_the_day_closes`,
`test_the_day_is_not_judged_while_a_segment_stays_open`,
`test_not_showing_up_opens_an_absence_when_the_day_closes`.

### H-2 — Los feriados producían ausencias falsas · **Media** · corregido

`expected_minutes` no consultaba `core.Holiday`: en un día feriado el sistema
esperaba trabajo, así que no presentarse abría una ausencia y trabajar no contaba
como extra. Era un requisito explícito de la fase («cálculo con feriados») que se
había quedado fuera.

**Corrección:** en feriado de la empresa no se espera trabajo; lo trabajado es
tiempo extra.
**Pruebas:** `test_a_public_holiday_expects_no_work`,
`test_working_on_a_public_holiday_is_all_overtime`.

### Corregido de paso

La vista de asistencia del equipo consultaba por persona **sin límite**: con una
organización grande habría disparado cientos de consultas. Ahora pagina.

---

## Desviaciones aceptadas

### D-1 — El marcaje no se audita uno a uno

Se auditan el ajuste y la resolución de incidencias; el marcaje no. Son miles de
eventos al mes y ahogarían una bitácora cuya utilidad es detectar lo excepcional.
**La trazabilidad no se pierde:** cada marcaje guarda `registered_by` y `source`,
y el registro en sí es el dato. Se revisará si aparece un requisito legal que
exija rastro separado (ADR-021).

### D-2 — Solo autoservicio

El negocio decidió que cada persona marca lo suyo. La matriz §J.2 contempla que
la jefatura y RRHH registren marcajes de terceros: **los permisos existen, la
pantalla no**. Se añadirá cuando exista el caso (personal sin dispositivo), con
`source = SUPERVISOR` o `HR`, que el modelo ya admite.

### D-3 — La asistencia no crea una clasificación nueva de datos

Las horas de entrada y salida son dato **interno**, con el mismo alcance que la
ficha: propio, equipo u organización. No se reclasifican como sensibles porque no
revelan salud, ideología ni ubicación. Si algún día se registra ubicación,
cambia esta conclusión y exige su propio ADR.

---

## Límite documentado

**Turnos que cruzan la medianoche.** Un segmento se imputa al día de la entrada,
así que una jornada nocturna quedaría partida entre dos fechas. No hay ninguna
jornada así hoy; soportarla exige decidir a qué día pertenece la noche, y eso es
diseño, no un parche.

---

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| `close_attendance_day` sin programar: no aparecen ausencias ni salidas tempranas | **Bloqueante para producción**, junto con `expire_contracts` |
| Reportes por período: existe el selector (`period_summary`), no la pantalla de reporte ni la exportación | Pendiente; P-11 del plan UX pregunta si hace falta Excel |
| Jornadas con horario distinto por día | Se crean con horario común; afinar día a día exige el admin hasta que haya caso real |
| `MINIMUM_MONTHLY_SALARY` y el algoritmo del NIT | Heredados de fases anteriores; siguen siendo bloqueantes |
