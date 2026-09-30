# ADR-022 — Reglas de ausencias: devengo, aprobación y privacidad

- **Estado:** Aceptado
- **Fecha:** 2026-09-18
- **Decide:** Negocio, con análisis del equipo técnico
- **Fase:** 6

---

## Contexto

El roadmap condicionaba la Fase 6 a «parametrizar el devengo». Al abrirla
aparecieron otras tres preguntas que cambian el esquema o la autorización, y que
por lo tanto no se pueden dejar al código: quién aprueba cuando no hay jefatura,
qué ve el equipo de una ausencia médica y qué entra en la fase.

## Decisiones

### 1. Devengo proporcional mensual

Cada mes con contrato vivo suma **una doceava parte** de los días anuales del
tipo (`LeaveType.default_annual_days / 12`). Lo asienta el comando mensual
`accrue_leave`.

- **Por qué:** refleja el derecho que se va ganando y no obliga a nadie a esperar
  un año para tener saldo. Es también lo que se paga en una liquidación.
- **Idempotente:** un índice único por `(empleado, tipo, inicio de período)`
  impide devengar el mismo mes dos veces, aunque el comando se repita.
- **Alternativa descartada:** otorgar el año completo al aniversario. Es más
  simple, pero deja a la persona sin saldo once meses y complica la liquidación.
- **Los días dependen de la antigüedad:** ver la decisión 6.

### 2. La aprobación sube por el organigrama

Puede decidir quien tiene el permiso `approve_leave` **y** autoridad sobre la
persona: RRHH en toda la organización, o una jefatura del departamento de la
persona **o de cualquiera superior**.

- **Por qué:** la jefatura no puede aprobar su propia solicitud (RN-44) y un área
  puede quedarse sin jefatura. Sin escalada, ambos casos congelan el trámite.
- **Una jefatura hermana no decide:** la autoridad se hereda hacia abajo, nunca
  hacia los lados.
- **Nadie aprueba lo suyo**, tampoco RRHH. La bandeja ni siquiera lo muestra.

### 3. Incapacidad y duelo no se muestran al equipo

`LeaveType.is_sensitive` marca los tipos que revelan salud o intimidad. En el
calendario, quien no es RRHH ni la propia persona ve **«Ausente»**, sin el tipo.

- **Por qué:** «Ana está de incapacidad» es un dato de salud (§G.19). El
  calendario se consulta en reuniones y se proyecta; no es el lugar.
- **Quien decide sí ve el tipo**, porque sin él no puede decidir. La bitácora
  **nunca** guarda el motivo escrito por la persona: puede traer un diagnóstico.

### 4. La fase cubre solo ausencias

El roadmap sumaba a esta fase la plantilla general al sistema: códigos de
activación y alta por lotes (ADR-004, vía C). **Se separan** a una entrega
propia.

- **Por qué:** son un cambio de superficie de ataque —un flujo de canje público
  con límite de tasa— que merece su propia revisión de seguridad, no un anexo a
  la de ausencias.

### 5. Las ausencias se pueden registrar después de ocurridas, por tipo

«Se accidenta hoy y lo reportan pasado mañana.» Cada tipo declara cuántos días
hacia atrás admite (`max_backdating_days`, de 0 a 30). Con 0, la ausencia debe
empezar hoy o después, y aplica el preaviso.

- **Un tipo no puede exigir preaviso y admitir retroactivo a la vez:** las dos
  reglas se contradicen. Lo impone la base de datos.
- **El plazo se revalida al enviar**, no solo al crear: un borrador olvidado no
  se cuela fuera de plazo.
- **Queda a la vista:** la bitácora registra con cuántos días de retroactivo se
  registró cada solicitud. Es donde una ausencia más se presta a abuso.
- **Tope de 30 días:** más que eso deja de ser «se reportó tarde» y pasa a ser
  reescribir la asistencia de otro mes, que quizá ya se pagó.
- **Encaja con asistencia:** al aprobarla se justifican las faltas que el cierre
  diario ya hubiera abierto en esos días.

### 6. Los días anuales crecen con la antigüedad, sin bajar nunca del piso legal

«Conforme a la legislación aplicable; tampoco vamos a ser injustos.» El tipo
guarda los días **base** —el piso— y `LeaveAccrualTier` define tramos por años
de servicio cumplidos: «desde 3 años, 18 días; desde 5, 20».

- **Referencia legal:** en Guatemala, el artículo 130 del Código de Trabajo fija
  un mínimo de 15 días hábiles por año de servicio continuo, igual para todos.
  Lo que crece con la antigüedad suele venir de política interna o de pacto
  colectivo. **El sistema no fija la cifra: la carga RRHH**, y debe validarla con
  asesoría legal antes de producción.
- **Nunca menos días por más antigüedad:** un tramo no puede quedar por debajo
  de la base ni de un tramo menor, ni por encima de uno mayor; subir la base por
  encima de un tramo existente se rechaza. Son comparaciones entre filas, así que
  las imponen los servicios, con pruebas.
- **La antigüedad se cuenta desde `Employee.hire_date`** y en años cumplidos al
  inicio del mes que se devenga.
- **Lo ya devengado no cambia** al editar los tramos: está en el libro, y cada
  asiento anota con qué antigüedad y qué días por año se calculó.

## Consecuencias

### Positivas
- Ninguna solicitud se queda sin quien la decida.
- Los datos de salud no circulan por pantallas compartidas.
- El devengo puede repetirse sin miedo.

### Negativas aceptadas
- **El devengo depende de un comando mensual.** Si no se programa, nadie
  acumula días. Es bloqueante para producción, como `close_attendance_day`.
- **La escalada no tiene tope:** la dirección general puede decidir sobre toda
  la organización. Es coherente con el alcance que ya tiene el rol `MANAGER`.
- **Un empleado sin jornada asignada** cuenta de lunes a viernes. Es una
  suposición explícita y documentada en `working_days_between`, no un dato.
