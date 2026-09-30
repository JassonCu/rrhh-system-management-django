# Revisión de seguridad — Fase 2 (Cuentas y acceso)

- **Fecha:** 2026-09-11
- **Alcance:** `apps/accounts`, integración de `django-allauth`, enrutamiento y plantillas de acceso
- **Checklist aplicado:** [§K.9](11-seguridad.md#k9-revisión-de-seguridad-por-fase)
- **Resultado:** **aprobada**, con dos desviaciones aceptadas y documentadas

---

## Checklist

| # | Punto | Estado | Verificación |
|---|---|---|---|
| 1 | Toda vista tiene autenticación explícita | ✅ | `test_url_coverage.py` recorre las 30 URLs con nombre del proyecto |
| 2 | Toda vista tiene comprobación de permiso | ✅ | Ver desviación D-2 |
| 3 | Todo acceso a objeto pasa por un selector con alcance | ✅ | `deactivate_user` usa `selectors.get_user_or_404`; ninguna vista consulta el modelo directamente |
| 4 | Ningún formulario usa `fields = "__all__"` | ✅ | `test_form_safety.py` descubre y recorre **todos** los `ModelForm` de `apps/` |
| 5 | Ningún formulario expone campos de privilegio ni FKs de propiedad | ✅ | Ídem, más una prueba de extremo a extremo que envía `is_superuser` y comprueba que no cambia |
| 6 | Las plantillas no usan `\|safe` sobre datos de usuario | ✅ | **Nuevo:** `test_template_safety.py` |
| 7 | Las plantillas no llevan JS ni CSS en línea | ✅ | **Nuevo:** ídem, incluidos `style=` y `onclick=` |
| 8 | Los cambios de estado son `POST` con CSRF | ✅ | `require_http_methods(["POST"])` en la baja; prueba con `enforce_csrf_checks` |
| 9 | Los datos sensibles no aparecen en logs ni en URLs | ✅ | Filtro de redacción con prueba propia; ninguna contraseña llega a la bitácora |
| 10 | Las acciones relevantes emiten `AuditEvent` | ✅ | Los 9 eventos de §I.6, cada uno con su prueba |
| 11 | Tests de acceso no autorizado por vista | ✅ | Matriz rol × vista para las cuatro vistas de `accounts` |
| 12 | Test de IDOR por recurso con identificador en URL | ✅ | `test_out_of_scope_account_is_404_not_403` y `test_deactivating_an_unknown_account_is_404` |
| 13 | Bandit sin severidad media/alta | ✅ | Limpio |
| 14 | `pip-audit` sin vulnerabilidades | ✅ | Limpio |
| 15 | `detect-secrets` sin hallazgos nuevos | ✅ | Limpio |
| 16 | `check --deploy` sin advertencias | ✅ | Limpio con configuración de producción |
| 17 | Los errores no filtran información interna | ✅ | `test_error_pages_do_not_leak_internals` |

**Métricas:** 380 pruebas, 186 con marca `security`, 95,8 % de cobertura.

---

## Hallazgos corregidos durante la fase

| # | Hallazgo | Gravedad | Corrección |
|---|---|---|---|
| H-1 | El sincronizador de roles se ejecutaba en el `post_migrate` de `accounts`, antes de que existieran los permisos de `audit`. **El rol `AUDITOR` quedaba sin `view_audit_log` en silencio** | Media — privilegios menores de los declarados, sin señal visible | Se ejecuta en el `post_migrate` de todas las apps; es idempotente y converge. Prueba: `test_only_auditor_reads_the_audit_log` |
| H-2 | La prueba que implementa el **criterio de cierre** perdía el espacio de nombres al recorrer los patrones, y omitía en silencio las vistas de `accounts` | Alta — la garantía principal de la fase pasaba en vacío | Se lee del `reverse_dict`. Prueba de red: `test_the_project_views_are_included` |
| H-3 | `ACCOUNT_DEFAULT_HTTP_PROTOCOL` no se elevaba a `https` en producción: los enlaces de invitación y restablecimiento habrían viajado por HTTP | Alta — credencial de un solo uso en claro | Fijado en `production.py` y cubierto por `test_production_sends_https_links_in_emails` |
| H-4 | Dos puntos del checklist (`\|safe`, código en línea) estaban documentados pero sin verificación automática | Baja — regla sin mecanismo | 83 comprobaciones nuevas sobre las plantillas |

---

## Desviaciones aceptadas

### D-1 — `deactivate_user` expone la clave primaria en la URL

`/cuentas/usuarios/<int:pk>/desactivar/` usa el identificador de base de datos y
no un `public_id`, a diferencia de lo previsto para `Employee`, `EmploymentContract`,
`LeaveRequest` y `EmployeeDocument` (§B, «Identificador público»).

**Se acepta** porque `User` no está en esa lista: el selector acota el acceso
antes de buscar, de modo que el identificador no concede nada, y la enumeración
solo revela que existen cuentas —algo que el listado ya muestra a quien tiene
permiso—. **Se revisará** si la gestión de cuentas llega a ser accesible desde
fuera de la red corporativa.

### D-2 — `profile` y `home` solo llevan `login_required`

No tienen `permission_required` porque el recurso es **propio**: el alcance es
`request.user` por construcción, y exigir un permiso adicional sería ceremonia
sin efecto. Está cubierto por pruebas de acceso anónimo.

---

## Riesgos abiertos al cerrar la fase

| Riesgo | Estado |
|---|---|
| Sin MFA | Diferido a la Fase 9. Con `allauth.mfa` disponible, es configuración y no cambio de librería |
| Contraseñas almacenadas localmente | Consecuencia de diferir el SSO (ADR-017) |
| Los catálogos `.po` no se han generado | Bloqueado por la falta de `gettext` en la máquina de desarrollo; lo hace el CI |
| Sin endpoint de informes de violación de CSP | Fase 9. La política ya bloquea, que es lo que protege |
