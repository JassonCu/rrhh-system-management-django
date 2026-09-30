# Revisión de seguridad — Fase 3 (Núcleo de RRHH)

- **Fecha:** 2026-09-14
- **Alcance:** `apps/employees`, `apps/departments`, `apps/positions`, selectores de alcance y enmascarado de PII
- **Checklist aplicado:** [§K.9](11-seguridad.md#k9-revisión-de-seguridad-por-fase)
- **Resultado:** **aprobada**, con dos hallazgos corregidos, uno trasladado a la Fase 4 y una desviación aceptada

---

## Método

No se marcaron casillas de memoria. Se inspeccionó el código:

- Un análisis `ast` de las 18 vistas de las tres apps confirmó que **todas** llevan
  `login_required` + `permission_required(..., raise_exception=True)`, y que las
  que cambian estado restringen el método HTTP.
- Una búsqueda de `objects.get` / `objects.filter` en las vistas no encontró
  **ningún** acceso directo a modelos: todo pasa por selectores con alcance.
- Se revisó qué datos llegan a cada plantilla según quién la pide, que es donde
  apareció el hallazgo principal.

---

## Checklist

| # | Punto | Estado | Verificación |
|---|---|---|---|
| 1 | Autenticación explícita en toda vista | ✅ | Análisis `ast` + `test_url_coverage.py` sobre toda la tabla de URLs |
| 2 | Comprobación de permiso en toda vista | ✅ | Ídem; matrices rol × vista en las tres apps |
| 3 | Todo acceso a objeto pasa por un selector | ✅ | Sin `objects.get` en vistas; `get_employee_or_404` sobre `employees_visible_for` |
| 4 | Sin `fields = "__all__"` | ✅ | `test_form_safety.py` descubre todos los `ModelForm` |
| 5 | Sin campos de privilegio ni FK de propiedad en formularios | ✅ | Ídem; `EmployeeForm` no expone `user` ni `employment_status` |
| 6 | Sin `\|safe` sobre datos de usuario | ✅ | `test_template_safety.py` |
| 7 | Sin JS ni CSS en línea | ✅ | Ídem |
| 8 | Cambios de estado por `POST` con CSRF | ✅ | `require_http_methods` + pruebas 405 |
| 9 | Datos sensibles fuera de logs y URLs | ✅ | URLs con `public_id`; `__str__` de documentos enmascarado; auditoría sin fechas de nacimiento, números de documento ni valores editados |
| 10 | Acciones relevantes auditadas | ✅ | Alta, edición, documentos, acceso sensible |
| 11 | Tests de acceso no autorizado por vista | ✅ | Matrices por app |
| 12 | Test de IDOR por recurso con identificador | ✅ | `test_changing_the_uuid_in_the_url_grants_nothing`, 404 y no 403 |
| 13-16 | Bandit, `pip-audit`, `detect-secrets`, `check --deploy` | ✅ | Limpios |
| 17 | Errores sin información interna | ✅ | Mensajes de dominio por código estable |

**Métricas:** 709 pruebas, 92,6 % de cobertura.

---

## Hallazgos

### H-1 — Contactos personales y de emergencia expuestos a quien tuviera alcance sobre la ficha · **Alta** · corregido

La vista de detalle pasaba a la plantilla **todos** los contactos de la persona
(teléfonos y correos personales) y **todos** sus contactos de emergencia, a
cualquiera que pudiera abrir la ficha. La clasificación §G.19 los reserva a RRHH
y a la propia persona; un `MANAGER` solo debe ver el contacto laboral.

**Por qué no había fuga hoy, y por qué era grave igualmente:** en la Fase 3 el
`MANAGER` todavía no ve a su equipo, así que ningún rol real reunía "ve la ficha"
y "no debe ver PII". **La fuga se habría activado exactamente al construir la
Fase 4**, sin ningún cambio en `employees`: un defecto latente que la matriz de
permisos no detectaba porque el permiso de vista sí era correcto.

**Corrección:** dos selectores nuevos, `contact_methods_for` y
`emergency_contacts_for`, que devuelven solo el correo laboral o nada según
`can_view_personal_data`. Los datos no permitidos **no llegan a la plantilla**;
la plantilla solo decide el texto a mostrar.
**Pruebas:** `test_manager_sees_only_the_work_contact`,
`test_manager_does_not_see_emergency_contacts`, `test_personal_contact_selectors_are_scoped`.

### H-2 — El acceso a la propia ficha se registraba como consulta sensible · **Baja** · corregido

Cada vez que alguien abría su propia ficha se escribía un
`EMPLOYEE_VIEW_SENSITIVE`. No filtra nada, pero **degrada la señal**: la utilidad
de ese evento es detectar a terceros consultando datos ajenos, y el ruido del
autoacceso la enterraría.

**Corrección:** solo se registra cuando quien consulta no es el titular.
**Prueba:** `test_viewing_your_own_record_is_not_logged_as_sensitive_access`.

### H-3 — El estado laboral se modifica fuera de `contracts` · **Media** · trasladado a la Fase 4

`employees.services.terminate_employee` cambia `employment_status` directamente.
En la Fase 3 es el único camino posible, pero contradice RN-18 y ADR-012: el
estado debe modificarse **solo** desde `contracts.services`, en la misma
transacción que el contrato. En cuanto existan contratos, dos caminos de baja
divergirían. **Se corrige al construir la Fase 4**, retirando la baja de
`employees`.

---

## Desviación aceptada

### D-1 — La ficha de un departamento muestra el centro de costo a cualquier usuario

La matriz §J.2 indica que un `EMPLOYEE` ve los departamentos por **nombre**; la
ficha le muestra además el centro de costo. **Se acepta**: es un código contable
interno, no información personal ni confidencial, y restringirlo exigiría un
permiso adicional sin beneficio de seguridad real. Se revisará si algún
centro de costo llega a codificar información sensible.

---

## Riesgos abiertos

| Riesgo | Estado |
|---|---|
| Algoritmo del NIT sin contrastar con NIT reales | **Bloqueante para producción**, no para el desarrollo |
| CUI sin validación geográfica | Aceptado a propósito: no hay catálogo de municipios (§A.6) |
| `DepartmentHeadship` solo gestionable desde el admin | Sin interfaz propia; aceptable mientras las jefaturas las administre SUPERADMIN |
| Alcance de equipo del `MANAGER` | Se construye en la Fase 4; hay una prueba que obliga a revisarlo |
