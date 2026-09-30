# Revisión de seguridad — Fase 4 (Relación laboral)

- **Fecha:** 2026-09-14
- **Alcance:** `apps/contracts` completo; cambios en `employees` (alcance de equipo, retirada de la baja), `positions` (puestos ocupados) y `audit` (acción nueva)
- **Checklist aplicado:** [§K.9](11-seguridad.md#k9-revisión-de-seguridad-por-fase)
- **Resultado:** **aprobada**, con ocho hallazgos corregidos (tres heredados de fases anteriores y dos detectados al probar la aplicación a mano), la deuda de la Fase 3 cerrada y tres desviaciones aceptadas

---

## Método

Como en la Fase 3, no se marcaron casillas de memoria:

- Se leyó cada servicio preguntando **sobre quién** actúa, además de **quién**
  puede invocarlo. De ahí sale el hallazgo principal: la matriz de permisos era
  correcta y aun así permitía autoconcederse un aumento.
- Se revisó qué llega a cada plantilla según el rol, con importes en todas sus
  formas localizadas (`7,000.00`, `7000.00`, `7000`, `7,000`) para que una
  aserción negativa no pase por el motivo equivocado.
- Se revisaron los caminos que **esquivan los servicios**: admin, comandos de
  gestión y cambios de estado programados.
- Se buscó cualquier asignación a `employment_status` fuera de
  `contracts.services`: solo existe la de `_sync_employee_status`.

---

## Checklist

| # | Punto | Estado | Verificación |
|---|---|---|---|
| 1 | Autenticación explícita en toda vista | ✅ | `test_url_coverage.py` recorre toda la tabla de URLs, incluidas las 10 de `contracts` |
| 2 | Comprobación de permiso en toda vista | ✅ | Matriz rol × vista en `contracts/tests/test_authorization.py` |
| 3 | Todo acceso a objeto pasa por un selector | ✅ | Contratos por `get_contract_or_404`; asignaciones buscadas **dentro** del contrato autorizado; el titular de un contrato nuevo sale de `get_employee_or_404` |
| 4 | Sin `fields = "__all__"` | ✅ | `test_form_safety.py` |
| 5 | Sin campos de privilegio ni FK de propiedad en formularios | ✅ | Ningún formulario expone `employee`, `status`, `effective_to`, `end_date` de asignación ni `created_by` |
| 6 | Sin `\|safe` sobre datos de usuario | ✅ | `test_template_safety.py` |
| 7 | Sin JS ni CSS en línea | ✅ | Ídem |
| 8 | Cambios de estado por `POST` con CSRF | ✅ | Activar, suspender, reanudar y finalizar asignación solo aceptan `POST`; pruebas 405 |
| 9 | Datos sensibles fuera de logs y URLs | ✅ | Auditoría sin importes; `ContractSalary.__str__` sin importe; URLs con `public_id` |
| 10 | Acciones relevantes auditadas | ✅ | `CONTRACT_*`, `SALARY_CHANGE`, `SALARY_VIEW`, `ASSIGNMENT_*`, `USER_DEACTIVATE` en la baja |
| 11 | Tests de acceso no autorizado por vista | ✅ | Matriz + `AUDITOR` intentando terminar por `POST` |
| 12 | Test de IDOR por recurso con identificador | ✅ | UUID de contrato ajeno → 404; clave de asignación de otro contrato → 404 sin efecto |
| 13 | Bandit | ✅ | Sin hallazgos de severidad media o alta. Quedan cinco `B105` de severidad baja en settings (límites de tasa y claves de desarrollo/pruebas): falsos positivos |
| 14 | `pip-audit` | ✅ | Sin vulnerabilidades conocidas |
| 15 | `detect-secrets` | ✅ tras H-6 | La línea base estaba vacía y el CI no bloqueaba; ver H-6 |
| 16 | `check --deploy` | ✅ | Sin advertencias |
| 17 | Errores sin información interna | ✅ | Códigos de dominio estables traducidos en la vista |

**Métricas:** 863 pruebas (453 marcadas `security`), 93,3 % de cobertura.

---

## Hallazgos

### H-1 — Cualquiera con permisos podía modificar su propia relación laboral · **Alta** · corregido

`HR_ADMIN` tiene `change_salary`; `HR_MANAGER`, `add_assignment`. Nada impedía
que una responsable de RRHH con ficha de empleada **se subiera el salario**, que
un analista **se asignara un puesto superior** o que alguien suspendiera o
reactivara su propio contrato. La matriz de permisos no lo detecta porque no es
un problema de **qué** puede hacer alguien, sino de **sobre quién**.

**Corrección:** `_lock_contract`, por el que pasan todos los casos de uso con
actor humano, rechaza la operación cuando el actor es el titular
(`cannot_change_own_employment`). `create_contract` aplica la misma regla.
Afecta también a `SUPERADMIN`. Ponerla en el bloqueo, y no en cada servicio,
evita que un caso de uso futuro la olvide.
**Pruebas:** `test_nobody_raises_their_own_salary`, `test_nobody_promotes_themselves`,
`test_nobody_changes_the_status_of_their_own_contract`,
`test_nobody_creates_a_contract_for_themselves`,
`test_a_colleague_can_still_act_on_that_contract`.

### H-2 — Las consultas de salario de terceros no dejaban rastro · **Media** · corregido

El historial salarial es el dato más sensible del módulo y su consulta no se
registraba, a diferencia de la PII sensible desde la Fase 3. No había forma de
responder «¿quién miró el sueldo de esta persona?».

**Corrección:** acción `SALARY_VIEW` (migración `audit.0003`) registrada al abrir
un contrato cuando se pueden ver sus importes y quien consulta **no** es el
titular, con el mismo criterio de ruido que H-2 de la Fase 3. El evento no lleva
importes.
**Pruebas:** `test_a_third_party_salary_view_is_audited`,
`test_viewing_your_own_salary_is_not_audited`,
`test_opening_a_contract_without_salary_access_is_not_a_salary_view`.

### H-3 — El admin permitía editar contratos esquivando los servicios · **Media** · corregido

`EmploymentContractAdmin` impedía borrar, pero dejaba editar `company`,
`contract_type`, `start_date` y `end_date`. Mover la fecha de inicio de un
contrato con salario rompe RN-21 y RN-26 sin que ningún servicio se entere, y sin
auditoría de dominio.

**Corrección:** admin de contratos y sus dos inlines en solo lectura, incluso para
superusuarios.
**Prueba:** `test_contract_admin_is_read_only`.

### H-4 — Una baja con fecha futura cortaba el acceso de inmediato · **Media** · corregido

Registrar hoy una renuncia efectiva a fin de mes cerraba el contrato, marcaba al
empleado como `TERMINATED`, **desactivaba su cuenta** y lo sacaba del alcance de
su jefe desde ese mismo momento, semanas antes de irse. El estado se adelantaba
a los hechos.

**Corrección:** `termination_in_future`. Las bajas se registran el día en que
ocurren o después; los vencimientos de plazo fijo los procesa `expire_contracts`.
**Pruebas:** `test_a_future_termination_is_rejected`, `test_a_termination_today_is_allowed`.

### H-5 — Se podía asignar un puesto de otra empresa · **Media (integridad)** · corregido

El contrato pertenece a una empresa y el puesto, vía departamento, a otra.
Nada lo impedía: un contrato podía acabar con dos patronos distintos según por
dónde se consultara.

**Corrección:** `position_in_another_company` en `add_assignment`.
**Prueba:** `test_a_position_of_another_company_cannot_be_assigned`.

### H-6 — El control de secretos nunca bloqueó nada · **Media (proceso)** · corregido

Al ejecutar `detect-secrets-hook` sobre el árbol completo, falló con 24
detecciones distintas. Dos defectos, ambos de la Fase 1:

1. **La línea base estaba vacía.** Ninguna detección estaba auditada, así que el
   hook no podía pasar sobre estos archivos.
2. **El paso del CI no podía fallar.** `detect-secrets scan --baseline` **reescribe**
   la línea base con lo que encuentra y sale con 0: acepta cualquier secreto en
   silencio.

**Consecuencia para las revisiones anteriores:** las filas «`detect-secrets`
limpio» de las revisiones de las Fases 2 y 3 **no estaban fundamentadas**. No se
editan (son registro de lo que se afirmó entonces); esta nota las corrige.

**Revisión de las detecciones:** las 24 son falsos positivos: contraseñas de
prueba (`Segura-12345678`, `hunter2` en pruebas de saneado de logs), nombres de
constantes (`PASSWORD_CHANGE`), la configuración de límites de tasa de allauth,
las claves de desarrollo y pruebas etiquetadas como inseguras, una URL de ejemplo
en `.env.example` y las credenciales efímeras del PostgreSQL del CI. **Ningún
secreto real.**

**Corrección:** línea base regenerada con cada detección marcada
`is_secret: false` y rutas POSIX (el CI corre en Linux). El CI usa ahora
`detect-secrets-hook`, que falla ante cualquier secreto no auditado.

### H-7 — El admin tenía un login propio sin límite de intentos · **Alta** · corregido

Detectado al probar la aplicación a mano. `/admin/login/` servía el formulario de
`django.contrib.admin`, que **no pasa por allauth**: sin `ACCOUNT_RATE_LIMITS` y sin
verificación de correo obligatoria. Era una segunda puerta, sin frenos, justo
hacia las cuentas `is_staff`, que son las de más privilegio.

**Corrección:** `admin.site.login` envuelto en `login_required`. Sin sesión, el
admin redirige al login de allauth; un `POST` de credenciales al formulario del
admin no autentica.
**Pruebas:** `tests/security/test_admin_login.py`.

### H-8 — Dos defectos de uso encontrados al probar a mano · **Baja** · corregidos

1. **Las jefaturas no se podían crear.** `DepartmentHeadship` no tenía vista ni
   estaba en el admin, aunque la revisión de la Fase 3 afirmaba que se gestionaba
   desde allí. Sin jefaturas, el alcance de equipo del `MANAGER` era imposible de
   usar fuera de las pruebas. Ahora está en el admin, sin borrado: una jefatura
   termina con `end_date`.
2. **El login invitaba a registrarse** en un registro cerrado, que responde 404.
   Plantilla `account/login.html` propia que explica que las cuentas las crea RRHH.
   **Prueba:** `tests/security/test_signup_closed_ui.py`.

---

## Deuda de la Fase 3, cerrada

| Pendiente | Resolución |
|---|---|
| H-3 de la Fase 3: el estado laboral se modificaba fuera de `contracts` | `terminate_employee`, su vista, su formulario y su plantilla retirados. `contracts.services._sync_employee_status` es el único escritor ([ADR-012](../decisions/ADR-012-estado-laboral-materializado.md)) |
| Alcance de equipo del `MANAGER` | `employees.selectors._team_of` usa `contracts.selectors.employee_ids_assigned_to`: asignación vigente, contrato vivo y puesto en un departamento jefeado, **en la misma fila**. Las pruebas usan contratos reales en lugar de simularlo |
| `deactivate_position` con asignaciones vigentes | `position_is_occupied`, que cuenta también borradores y asignaciones futuras. `deactivate_department` queda cubierto por transitividad: exige no tener puestos activos |

---

## Desviaciones aceptadas

### D-1 — Activar un contrato con fecha de inicio futura marca al empleado como activo hoy

`employment_status` refleja que existe un vínculo vivo, no que haya empezado. **Se
acepta** porque lo que tiene efectos de seguridad sí respeta las fechas: el
alcance del jefe exige una asignación **vigente**, y la cuenta ya existía. Se
revisará si asistencia o nómina necesitan distinguir «contratado, aún no
incorporado».

### D-2 — El empleado ve la justificación de su propio salario fuera de banda

Es información sobre su propia compensación. **Se acepta**, con una consecuencia
de proceso: RRHH debe redactar la justificación sabiendo que la leerá la persona.
Si el negocio necesita notas internas, será un campo separado con su propio
permiso, no una restricción sobre este.

### D-3 — En SQLite, RN-14 y RN-25 no tienen respaldo en la base

`select_for_update` no bloquea en SQLite. RN-13 y la unicidad de períodos
abiertos siguen garantizadas por índices parciales, pero el **no traslape** de
contratos y la **suma de FTE** solo las garantizan los servicios. Dos operaciones
realmente simultáneas sobre la misma persona podrían violarlas. **Se acepta** en
desarrollo (ADR-002); en PostgreSQL el bloqueo es real y RN-14 podrá reforzarse
con `ExclusionConstraint` (ADR-003).

---

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| Salario mínimo sin configurar: `MINIMUM_MONTHLY_SALARY` vacío desactiva RN-22 | **Bloqueante para producción**: debe fijarse por entorno y revisarse con cada acuerdo gubernativo |
| `expire_contracts` no está programado | **Bloqueante para producción**: sin una tarea diaria, los plazos fijos vencidos siguen vivos y sus cuentas activas |
| `check_employment_status` no se ejecuta automáticamente | Ejecutarlo tras cada despliegue y tras `expire_contracts`; falla con código distinto de cero |
| Algoritmo del NIT sin contrastar con NIT reales | Heredado de la Fase 3; sigue siendo bloqueante para producción |
| Corrección de un período salarial ya cerrado | Sin interfaz, a propósito ([ADR-014](../decisions/ADR-014-historial-temporal.md)) |
