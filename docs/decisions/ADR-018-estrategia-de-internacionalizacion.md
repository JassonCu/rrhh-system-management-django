# ADR-018 — Estrategia de internacionalización

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Producto, con recomendación del equipo técnico
- **Fase:** 1

---

## Contexto

La aplicación se usa en Guatemala, en español. Aun así, la i18n se adopta desde
el primer commit: retrofitearla obliga a revisar cada plantilla, cada
`verbose_name`, cada `choices` y cada mensaje del proyecto.

Hay **tres decisiones distintas** que suelen confundirse en una:

1. ¿En qué idioma se escriben los literales del código?
2. ¿Se traducen los **datos** que captura RRHH?
3. ¿Cómo se formatean números y fechas?

## Decisión 1 — Los `msgid` se escriben en inglés

### Alternativas

**A. `msgid` en español, catálogo en inglés.** Más cómodo de escribir para el
equipo.

- **En contra:** Django, `django-allauth` y el admin ya traen sus cadenas con
  `msgid` en inglés y su traducción al español. Media interfaz quedaría indexada
  por un idioma y media por otro, con el mismo concepto bajo dos claves
  distintas. Además, con `msgid` en español **el catálogo español no existe**: la
  cadena original es la traducción, así que corregir una errata visible obliga a
  tocar código Python en lugar de un `.po`, y nadie sin perfil técnico puede
  revisar la redacción. Por último, las reglas de plural que asumen las
  herramientas por defecto son las del inglés.

**B. `msgid` en inglés, catálogo `es_GT`** *(elegida)*.

- **En contra:** el equipo escribe en un idioma y lee la interfaz en otro.

### Decisión
Se adopta **B**. Es reversible solo al principio: cambiar de criterio a mitad de
proyecto implica reescribir todos los literales y regenerar los catálogos.

## Decisión 2 — Los datos se almacenan en un solo idioma

`Department.name`, `Position.title`, `LeaveType.name` y los demás catálogos
editables son **datos capturados por RRHH**, no cadenas del programa.

### Alternativas

**A. Columnas `name_es`, `name_en`.**
- **Rechazada.** Es un grupo repetitivo: cada idioma nuevo es una migración de
  esquema y la tabla se llena de nulos. Viola 1NF en su sentido de diseño.

**B. `name` como `JSONField` con `{"es": ..., "en": ...}`.**
- **Rechazada.** Es una relación escondida en un campo: no se puede indexar, ni
  imponer unicidad por idioma, ni consultar relacionalmente (regla 7).

**C. `django-modeltranslation`.**
- **Rechazada.** Implementa exactamente la opción A —una columna por idioma— y
  además añade una dependencia que reescribe el comportamiento del ORM.

**D. Un solo idioma, con salida documentada** *(elegida)*.
- Si algún día se requieren catálogos bilingües, la solución correcta es una
  entidad de traducción: `DepartmentTranslation(department, language, name)` con
  unicidad por `(department, language)`, que mantiene la normalización.

### Decisión
Se adopta **D**. El criterio para distinguir dato de cadena del programa es
simple: **si RRHH puede editarlo desde la interfaz, es dato y no se traduce.**

## Decisión 3 — Módulo de formatos propio para Guatemala

El catálogo `es` de Django usa la convención de España: coma decimal y espacio
duro como separador de millares (`1 500,00`). En Guatemala es al revés:
`1,500.00`.

Lo peligroso no es el separador de millares, sino la **coma decimal**: un lector
guatemalteco la interpreta como separador de miles, de modo que la misma cadena
puede leerse como dos cantidades distintas. En un recibo de nómina eso no es un
detalle estético.

### Alternativas

**A. Usar `LANGUAGE_CODE = "es-mx"`,** cuyo catálogo sí usa punto decimal.
- **Rechazada.** Funciona por accidente y miente sobre el país; cualquiera que lo
  vea lo «corregirá» a `es` y romperá los importes.

**B. Módulo de formatos propio en `config/formats/es_GT/`** *(elegida)*, fijado
por pruebas.

### Decisión
Se adopta **B**, con `FORMAT_MODULE_PATH = ["config.formats"]`.

## Otras decisiones que forman parte de esta

- **Sin `i18n_patterns`.** El idioma es una preferencia de la persona, no una
  propiedad del recurso: `/es/employees/<id>/` y `/en/employees/<id>/` serían dos
  URL para la misma fila, lo que ensucia los enlaces y el rastro de auditoría.
  La preferencia se guarda en `User.language`.
- **Idiomas soportados: `es-gt` y `en`.** Ni uno más «por si acaso»: cada idioma
  es un catálogo que hay que mantener y revisar en cada PR.
- **Lo que se consulta, se busca o se compara no se traduce:** valores de
  `choices`, códigos, `AuditEvent.action`, `object_repr`, `__str__` y los
  mensajes de log. Un `__str__` traducido haría que el mismo objeto quedara
  registrado distinto según el idioma de quien lo tocó.
- **Se versiona el `.po`, no el `.mo`.** El binario se compila en el despliegue.

## Consecuencias

### Positivas
- Añadir un idioma es traducir un catálogo, no tocar el código.
- Los importes se muestran con la convención correcta, y hay una prueba que lo
  impide cambiar por descuido.
- La bitácora y los logs siguen siendo buscables en un solo idioma.

### Negativas aceptadas
- El equipo escribe literales en inglés y lee la interfaz en español.
- `gettext` es una dependencia del sistema que **no viene en Windows**: hay que
  instalarla o trabajar en WSL. En esta máquina de desarrollo no está, así que
  los catálogos se generarán en CI.
- Marcar cada cadena tiene un coste constante al escribir código nuevo.

### Qué habría que hacer para revertirla
La decisión 1 es la cara: cambiar el idioma de los `msgid` exige reescribir todos
los literales. Las decisiones 2 y 3 son locales y reversibles.

## Cómo se verifica

| Verificación | Dónde |
|---|---|
| Los importes usan punto decimal y coma de millares | `apps/core/tests/test_formats.py::test_decimal_uses_guatemalan_separators` |
| El catálogo genérico `es` daría otra convención (demuestra que el módulo propio actúa) | `...::test_generic_spanish_would_use_a_different_convention` |
| Las fechas son día/mes/año y aceptan también ISO | `...::test_date_format_is_day_first`, `...::test_date_input_accepts_local_and_iso` |
| El módulo de formatos está configurado | `tests/test_settings_contract.py::test_localized_formats_module_is_configured` |
| Los idiomas soportados son exactamente los mantenidos | `...::test_supported_languages_are_limited_to_what_is_maintained` |
| `LocaleMiddleware` está en su posición | `...::test_locale_middleware_sits_between_session_and_common` |
| `__str__` no cambia con el idioma | `apps/audit/tests/test_models.py::test_str_is_not_translated`, `apps/accounts/tests/test_models.py::test_str_is_not_translated` |
| No hay cadenas nuevas sin extraer | Trabajo `i18n` del CI: `makemessages` + `git diff --exit-code locale/` |
| No hay cadenas sin traducir ni marcadas *fuzzy* | `scripts/check_translations.py`, probado en `tests/test_check_translations.py` |
