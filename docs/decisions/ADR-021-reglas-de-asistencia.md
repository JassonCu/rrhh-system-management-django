# ADR-021 — Reglas de asistencia: tolerancia, horas extra y ubicación

- **Estado:** Aceptado
- **Fecha:** 2026-09-17
- **Decide:** Negocio, con análisis del equipo técnico
- **Fase:** 5

---

## Contexto

El roadmap condicionaba la Fase 5 a afinar con el negocio dos reglas —tolerancia
y horas extra— porque **cambian el esquema**, no solo el código. A eso se sumó
la pregunta P-7 del plan UX/UI: si el marcaje registra la ubicación.

## Decisiones

### 1. La tolerancia vive en la jornada, no en el código

`WorkSchedule.grace_minutes`, con 10 minutos por defecto.

- **Por qué:** producción y oficina no tienen por qué compartir criterio, y
  cambiarlo no debe exigir un despliegue. Una constante global habría obligado a
  migrar el día que un área pida otra cosa.
- **Alternativa descartada:** un ajuste de entorno único. Es más simple, pero
  convierte una regla de negocio por área en una decisión de infraestructura.

### 2. Las horas extra nacen como incidencia abierta

El exceso sobre la jornada abre una incidencia `OVERTIME` en estado `OPEN`.
**Solo cuenta para pago cuando alguien la justifica.**

- **Por qué:** pagar automáticamente todo exceso convierte «me quedé un rato» en
  planilla. Exigir autorización previa, en el otro extremo, impide registrar lo
  que de hecho ocurrió.
- **Consecuencia:** la Fase 8 leerá incidencias **justificadas**, no minutos
  sueltos.

### 3. El marcaje no registra ubicación

- **Por qué:** la geolocalización convierte la asistencia en dato sensible, exige
  base legal, aviso previo y una política de retención. Nada de eso aporta al
  caso de uso actual, que es personal en sitio.
- **Si cambia:** exige ADR propio, aviso explícito antes del primer marcaje y
  reclasificación del dato en §G.19.

### 4. El total diario se calcula, no se almacena

`selectors.worked_minutes` agrega los segmentos.

- **Por qué:** un total almacenado puede divergir del detalle, y el detalle es la
  fuente. Si el volumen lo exige, se materializará **después de medir** (§B.7).

### 5. El marcaje no se audita uno a uno

Se auditan el **ajuste** y la **resolución de incidencias**; el marcaje en sí no.

- **Por qué:** son miles de eventos al mes y ahogarían la bitácora, cuya utilidad
  es detectar lo excepcional. El propio registro ya guarda quién marcó
  (`registered_by`) y desde qué origen (`source`).

### 6. La salida temprana y la ausencia solo se saben al cerrar el día

El exceso se detecta al instante; el defecto, no: que alguien lleve cuatro horas
al mediodía significa que se fue a almorzar, no que se fue temprano. El comando
`close_attendance_day` cierra el día y abre esas incidencias.

- **Lo descubrió una prueba**, no una revisión: el primer diseño abría «salida
  temprana» al cerrar el primer segmento de una jornada partida.

## Consecuencias

### Positivas
- Cada área ajusta su tolerancia sin tocar código.
- Nadie paga horas extra que nadie autorizó, y queda constancia de quién decidió.
- Menos datos sensibles que proteger.

### Negativas aceptadas
- **Las incidencias de ausencia dependen de un comando diario.** Si no se
  programa, no aparecen. Es un bloqueante de puesta en producción, igual que
  `expire_contracts`.
- **Turnos que cruzan la medianoche** no están soportados: el segmento se imputa
  al día de la entrada. Una jornada nocturna real necesitará su propio diseño.
- Calcular el total en cada consulta cuesta más que leer una columna.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| La tolerancia sale de la jornada, no de una constante | `test_the_grace_period_comes_from_the_schedule` |
| Volver de almorzar no es llegar tarde | `test_returning_from_lunch_is_not_a_late_arrival` |
| Las horas extra nacen abiertas | `test_working_longer_opens_an_overtime_incident_that_nobody_approved_yet` |
| La salida temprana solo se sabe al cerrar el día | `test_leaving_early_is_only_known_once_the_day_closes` |
| El cierre diario es idempotente | `test_closing_a_day_twice_changes_nothing` |
| En feriado no se espera trabajo | `test_a_public_holiday_expects_no_work` |
| Ningún modelo guarda coordenadas | Revisión de `apps/attendance/models.py` |
