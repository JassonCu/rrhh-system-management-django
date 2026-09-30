# ADR-007 — CSP estricta con nonce, mediante django-csp

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1

---

## Contexto

El autoescape de las plantillas de Django cubre la mayoría de los XSS, pero no
todos: un `|safe` mal puesto, un campo renderizado en un contexto JavaScript o
una dependencia comprometida bastan. La CSP es la segunda barrera, la que
convierte un XSS explotable en uno inerte.

La decisión es urgente porque **condiciona cómo se escribe todo el frontend**:
introducir una CSP estricta con cincuenta plantillas ya escritas obliga a
reescribirlas.

## Alternativas consideradas

### A. Sin CSP
- **En contra:** se renuncia a la única mitigación que funciona cuando el
  escape falla. En un sistema con datos salariales y documentos laborales no es
  defendible.

### B. CSP laxa con `unsafe-inline`
- **En contra:** es la política que no protege de nada. `unsafe-inline` permite
  exactamente el vector que la CSP existe para bloquear; sirve para poner una
  cabecera en un informe de cumplimiento, no para detener un ataque.

### C. CSP estricta con nonce por petición, vía `django-csp` *(elegida)*
- **A favor:** bloquea todo script y estilo que el servidor no haya marcado.
  `form-action 'self'` impide además que un XSS reenvíe un formulario a un
  servidor externo — la diferencia entre robar datos y no poder sacarlos.
- **En contra:** una dependencia más, y una restricción permanente sobre el
  frontend.

### D. Middleware propio de CSP
- **Rechazada.** Generar un nonce por petición, propagarlo a la plantilla,
  variar la política por vista y no romper el caché son cuatro cosas fáciles de
  implementar casi bien. `django-csp` es pequeño, está mantenido y resuelve
  exactamente ese problema; escribirlo a mano sería sustituir código probado por
  código propio sin ganancia.

## Decisión

Se adopta **C**. La política vive en `config/settings/base.py`:

| Directiva | Valor | Por qué |
|---|---|---|
| `default-src` | `'self'` | Lo no declarado, prohibido |
| `script-src` | `'self'` + nonce | Sin `unsafe-inline` |
| `style-src` | `'self'` + nonce | Prohíbe también `style=` en línea |
| `img-src` | `'self' data:` | `data:` para iconos embebidos |
| `font-src` | `'self'` | Fuentes autoalojadas: privacidad y un origen menos |
| `connect-src` | `'self'` | `fetch` solo al propio origen |
| `form-action` | `'self'` | **Impide la exfiltración por formulario** |
| `frame-ancestors` | `'none'` | Clickjacking |
| `base-uri` | `'none'` | Impide secuestrar rutas relativas con `<base>` |
| `object-src`, `frame-src` | `'none'` | Sin plugins ni marcos |

### Consecuencias asumidas en el frontend

- Nada de `onclick=` ni de `<script>` con código embebido: `addEventListener`
  desde archivos en `static/js/`.
- Nada de `style=` en línea: clases CSS.
- Los datos que el JS necesita viajan en atributos `data-*` o por `json_script`.
- Las cadenas traducidas del JS se sirven con `JavaScriptCatalog`, que entrega un
  script externo del propio origen y por tanto es compatible.

### Despliegue por fases

`development` arranca en **modo informe** (`Content-Security-Policy-Report-Only`)
mientras el conjunto de plantillas se estabiliza; `testing` y `production`
bloquean desde el primer día. El paso definitivo de desarrollo a modo bloqueo
está previsto al cerrar la Fase 2.

## Consecuencias

### Positivas
- Un XSS que consiga inyectar `<script>` no ejecuta nada.
- `form-action 'self'` corta la vía de exfiltración más común.
- La disciplina de no escribir código en línea mantiene el frontend ordenado.

### Negativas aceptadas
- Una dependencia más que auditar y actualizar.
- Integrar una librería de terceros que inyecte estilos o scripts en línea
  requerirá adaptarla o descartarla. Se considera aceptable: es una restricción
  que empuja en la dirección correcta.
- El endpoint que recoge los informes de violación queda para la Fase 9.

### Qué habría que hacer para revertirla
Relajar la política es trivial (una línea) pero desanda la protección. Lo caro
sería lo contrario: volver a estricta tras haber escrito plantillas con código
en línea. Por eso se adopta ahora.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| La cabecera está presente en las respuestas | `tests/security/test_security_headers.py::test_csp_header_is_present` |
| No hay `unsafe-inline` ni `unsafe-eval` en la respuesta real | `...::test_csp_is_strict` |
| Las directivas críticas están declaradas en los ajustes | `tests/test_settings_contract.py::test_csp_declares_the_critical_directives` |
| La política de los ajustes no contiene fuentes inseguras | `...::test_csp_has_no_unsafe_sources` |
| Las plantillas no llevan código en línea | Revisión de PR + checklist de seguridad por fase |
