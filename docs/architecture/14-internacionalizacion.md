# O. Internacionalización (i18n) y localización (l10n)

Se adopta **desde la Fase 1**. Retrofitear i18n es de las tareas más ingratas que
existen: obliga a revisar cada plantilla, cada `verbose_name`, cada mensaje y cada
`choices` del proyecto. El costo de hacerlo desde el primer commit es marginal;
el de hacerlo en la Fase 5 es un sprint completo.

---

## O.0 Dos problemas distintos que no deben mezclarse

| | Qué es | Cómo se resuelve |
|---|---|---|
| **i18n de la interfaz** | Texto que escribe el programador: etiquetas, mensajes, errores, títulos | `gettext` + archivos `.po` |
| **i18n de los datos** | Contenido que captura RRHH: nombre de un departamento, título de un puesto, nombre de un tipo de ausencia | **Decisión de modelo de datos** (ver O.3.4) |

Confundirlos lleva al error clásico de añadir columnas `name_es` / `name_en` a las
tablas, que es un grupo repetitivo y una violación de 1NF. Este documento los
trata por separado.

---

## O.1 Decisiones

### O.1.1 Idioma de los literales del código fuente: **inglés**

Los `msgid` se escriben en inglés y se traducen a español en `locale/es_GT/`.

**Por qué**, aunque el equipo y el usuario final sean hispanohablantes:

1. Django, `django-allauth` y el admin ya traen sus cadenas con `msgid` en inglés
   y su traducción al español. Si nuestras cadenas fueran en español, la mitad de
   la interfaz estaría indexada por un idioma y la otra mitad por otro, y el
   mismo concepto tendría dos claves distintas.
2. Con `msgid` en español, el catálogo español **no existe** (la cadena original
   es la traducción). Corregir una errata visible obligaría a tocar el código
   Python en lugar de un `.po`, y se perdería la posibilidad de que alguien no
   técnico revise la redacción.
3. Las reglas de plural que asume la herramienta por defecto son las del inglés.

**Alternativa aceptable pero inferior:** `msgid` en español y catálogo en inglés.
Funciona, y es más cómodo de escribir, pero paga los tres costos anteriores. Si
se prefiere, hay que decidirlo **ahora**: cambiar de criterio a medio proyecto
implica reescribir todos los literales y regenerar los catálogos.

### O.1.2 Idiomas soportados

| Código | Uso | Estado |
|---|---|---|
| `es-gt` | Idioma por defecto de toda la aplicación | Completo |
| `en` | Segundo idioma | Se mantiene el catálogo; se activa cuando exista un usuario que lo necesite |

No se añaden más idiomas "por si acaso": cada uno es un catálogo que hay que
mantener sincronizado y revisar en cada PR (regla 56).

### O.1.3 Sin prefijo de idioma en las URLs

**No se usa `i18n_patterns`.** El idioma es una preferencia de la persona, no una
propiedad del recurso: el contrato `abc-123` es el mismo objeto se lea en español
o en inglés.

Con prefijos tendríamos `/es/employees/<id>/` y `/en/employees/<id>/` apuntando a
la misma fila, lo que duplica el espacio de URLs, complica `reverse()`, ensucia
los enlaces compartidos y confunde el rastro de auditoría. La resolución del
idioma se hace por preferencia del usuario, no por la ruta.

---

## O.2 Configuración

| Ajuste | Valor | Nota |
|---|---|---|
| `USE_I18N` | `True` | — |
| `USE_TZ` | `True` | Ya decidido; almacenamiento en UTC |
| `LANGUAGE_CODE` | `"es-gt"` | — |
| `LANGUAGES` | `[("es-gt", _("Spanish (Guatemala)")), ("en", _("English"))]` | Restringe el negociado a lo que realmente soportamos |
| `LOCALE_PATHS` | `[BASE_DIR / "locale"]` | Catálogos del proyecto, fuera de las apps: una sola ubicación para traducir todo |
| `TIME_ZONE` | `"America/Guatemala"` | — |
| `FORMAT_MODULE_PATH` | `["config.formats"]` | **Imprescindible.** Ver O.2.2 |
| `MIDDLEWARE` | `LocaleMiddleware` **después** de `SessionMiddleware` y **antes** de `CommonMiddleware` | Necesita la sesión para leer el idioma y `CommonMiddleware` depende del idioma activo |

> `USE_L10N` **no se configura**: quedó obsoleto en Django 4.0 y fue eliminado en
> Django 5.0. El formateo localizado está siempre activo. Añadirlo hoy produce un
> aviso o un error, no un efecto.

### O.2.1 Resolución del idioma activo

`LocaleMiddleware` resuelve en este orden: sesión → cookie → cabecera
`Accept-Language` → `LANGUAGE_CODE`. Se añade un paso previo: **si el usuario
está autenticado, manda su preferencia guardada** (`User.language`), que se activa
en la sesión al iniciar sesión.

Motivo: la preferencia debe seguir a la persona entre navegadores y dispositivos,
no quedarse en una cookie de una máquina compartida.

### O.2.2 La trampa de los separadores numéricos

**Este es el error de localización más probable del proyecto.** El catálogo `es`
que trae Django usa la convención de España:

```
DECIMAL_SEPARATOR  = ','
THOUSAND_SEPARATOR = '\xa0'   # espacio duro
```

Con esa configuración, un salario de 1500 quetzales se muestra como
**`1 500,00`**. En Guatemala la convención es la contraria: punto decimal y coma
de millares (`1,500.00`).

Lo peligroso no es el separador de millares, que a lo sumo se ve raro, sino la
**coma decimal**: un lector guatemalteco interpreta la coma como separador de
miles, de modo que `1 500,00` y `1,500.00` pueden leerse como cantidades
distintas. En un recibo de nómina eso no es un detalle estético.

**Solución:** módulo de formatos propio, `config/formats/es_GT/formats.py`:

```
DECIMAL_SEPARATOR      = "."
THOUSAND_SEPARATOR     = ","
NUMBER_GROUPING        = 3
DATE_FORMAT            = "d/m/Y"
SHORT_DATE_FORMAT      = "d/m/Y"
DATETIME_FORMAT        = "d/m/Y H:i"
FIRST_DAY_OF_WEEK      = 1          # lunes
DATE_INPUT_FORMATS     = ["%d/%m/%Y", "%Y-%m-%d"]
```

más `USE_THOUSAND_SEPARATOR = True` en los settings.

**Se cubre con un test** (O.9): un `Decimal("1500.00")` renderizado debe producir
`1,500.00` y una fecha, `09/09/2026`. Sin ese test, el día que alguien toque
`LANGUAGE_CODE` los importes cambiarán de significado en silencio.

### O.2.3 Zona horaria

- Guatemala no observa horario de verano, **pero el código no debe asumirlo**: se
  usa `zoneinfo` y `django.utils.timezone`, nunca desplazamientos fijos ni
  `datetime.now()`. La regla `DTZ` de Ruff ya lo vigila.
- El `weekday` de `WorkScheduleDay` (`0 = lunes`) es **dato**, no presentación:
  no cambia con `FIRST_DAY_OF_WEEK`. Lo que cambia es cómo se dibuja el
  calendario.

---

## O.3 Modelos

### O.3.1 Reglas

1. **Siempre `gettext_lazy`, nunca `gettext`.** Un `gettext` a nivel de módulo se
   evalúa al importar el modelo y congela el idioma del proceso para todos los
   usuarios. Convención: `from django.utils.translation import gettext_lazy as _`.
2. **Todo modelo** declara `verbose_name` y `verbose_name_plural` traducibles en
   su `Meta`. Alimentan el admin, los formularios y los mensajes de error de
   Django sin escribir nada más.
3. **Todo campo** lleva `verbose_name` (primer argumento posicional) y, cuando la
   regla de negocio no sea evidente, `help_text` — ambos traducibles. El
   `verbose_name` es lo que verá el usuario en el formulario si no se declara un
   `label`, así que traducirlo una vez sirve para todas las pantallas.
4. **Los `TextChoices` traducen la etiqueta, jamás el valor:**

   ```
   class EmploymentStatus(models.TextChoices):
       ACTIVE     = "ACTIVE",     _("Active")
       ON_LEAVE   = "ON_LEAVE",   _("On leave")
       SUSPENDED  = "SUSPENDED",  _("Suspended")
       TERMINATED = "TERMINATED", _("Terminated")
   ```

   El valor almacenado es ASCII estable y forma parte de los `CheckConstraint`,
   de las consultas y de la auditoría. **Traducir el valor rompería la base de
   datos**: el mismo estado se guardaría distinto según el idioma de quien lo
   creó, y el constraint rechazaría filas legítimas.
5. **`__str__` no se traduce.** Se usa en logs, en exportaciones y —lo decisivo—
   en `AuditEvent.object_repr`. Si se tradujera, el mismo objeto quedaría
   registrado de forma distinta según el idioma del usuario que lo tocó, y la
   bitácora dejaría de ser buscable. La representación legible para humanos en
   pantalla es responsabilidad de la plantilla, no de `__str__`.
6. **Mensajes de validación con interpolación por nombre**, nunca concatenación:
   `_("Salary must be at least %(minimum)s") % {"minimum": x}`. La concatenación
   impide que el traductor reordene la frase, cosa que otros idiomas exigen.
7. **Constraints con mensaje traducible:** `violation_error_message=_(...)` en
   `CheckConstraint` y `UniqueConstraint` (Django 4.1+), de modo que un choque de
   integridad llegue al usuario en su idioma en lugar de como `IntegrityError`.

### O.3.2 Efecto sobre las migraciones

Cambiar un `verbose_name` genera una migración que no altera el esquema. Es
ruido, pero inevitable y barato.

**Mitigación:** declarar `verbose_name` y `help_text` **desde la primera versión
del modelo**, no como un pase de limpieza posterior. Añadirlos después a treinta
modelos produce treinta migraciones vacías.

### O.3.3 Campo nuevo: `User.language`

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `language` | `CharField(10)` | No | Idioma preferido. Choices = `LANGUAGES`. Por defecto `"es-gt"` |

Es la única modificación al modelo de datos que exige la i18n. Se añade en la
Fase 1, junto con el modelo `User`, para no tener que migrar la tabla de
autenticación más adelante.

### O.3.4 Datos: **una sola lengua**, con salida documentada

`Department.name`, `Position.title`, `LeaveType.name`, `DocumentType.name` y
`PayrollConcept.name` son **datos capturados por RRHH**, no cadenas del programa.
Se almacenan en un solo idioma y **no** se traducen.

Razón: un catálogo bilingüe solo tiene sentido si la organización opera de verdad
en dos idiomas. Hoy no es el caso (supuesto S-01), y montar la maquinaria por
adelantado es complejidad sin usuario.

**Si algún día se requiere**, la solución correcta es una entidad de traducción:

```
DepartmentTranslation(**id**, _department_id_, language, name)
    UQ (department_id, language)
```

y **no**:

| Antipatrón | Por qué se rechaza |
|---|---|
| Columnas `name_es`, `name_en` | Grupo repetitivo. Cada idioma nuevo es una migración de esquema y la tabla se llena de nulos |
| `name` como `JSONField` con `{"es": ..., "en": ...}` | Relación escondida en un campo. No se puede indexar, ni imponer unicidad por idioma, ni consultar relacionalmente (regla 7) |
| `django-modeltranslation` | Implementa exactamente el primer antipatrón (una columna por idioma), y añade una dependencia que reescribe el ORM |

Los catálogos **del sistema** (los que se cargan por migración de datos y el
usuario no edita, como los tipos de documento de identidad) sí pueden llevar su
etiqueta traducida en el código, porque son cadenas del programa disfrazadas de
datos. Se distinguen por un criterio simple: **si RRHH puede editarlo desde la
interfaz, es dato y no se traduce.**

---

## O.4 Formularios

- `labels`, `help_texts` y `error_messages` traducibles.
- **Preferir no declarar `label`:** si el campo del modelo ya tiene
  `verbose_name` traducido, el `ModelForm` lo hereda. Declararlo otra vez duplica
  la cadena en el catálogo y crea dos sitios que pueden divergir.
- Los `error_messages` propios se traducen; los de Django ya lo están.
- **Entrada localizada:** los campos de fecha e importe usan `localize=True` para
  que lo que el usuario escribe se interprete con las mismas reglas con las que se
  le muestra. Un formulario que muestra `1,500.00` y solo acepta `1500.00` al
  reenviar es un error de validación que el usuario no entiende.
- Los `DATE_INPUT_FORMATS` del módulo de formatos aceptan tanto `09/09/2026` como
  ISO, para no pelear con el autocompletado del navegador.

---

## O.5 Vistas y servicios

### O.5.1 Dónde vive el mensaje

Regla: **los servicios no traducen; devuelven códigos estables.**

```
services  →  lanza ConflictError(code="contract_overlap", context={...})
views     →  traduce el código a un mensaje con _()
logs      →  registran el código, no el mensaje
```

**Por qué:** el mismo suceso debe verse en el idioma del usuario y, a la vez,
poder buscarse en los logs de forma unívoca. Si el servicio lanzara la cadena ya
traducida, el registro quedaría en el idioma de quien provocó el fallo y sería
inútil para diagnosticar (`grep "contrato traslapado"` no encuentra el mismo
incidente en inglés).

Consecuencia coherente con lo ya decidido: **`AuditEvent.action`, `outcome`,
`metadata` y los mensajes de log se escriben siempre en inglés/código estable, y
nunca se traducen.** Se traduce su presentación en la vista de auditoría.

### O.5.2 Mensajes al usuario

`django.contrib.messages` con `_()` y siempre con interpolación por nombre:

```
messages.success(request, _("Contract for %(employee)s was created.") % {...})
```

### O.5.3 Correos

**El punto que más se olvida.** Una notificación se genera en la petición de
*quien actúa*, pero la lee *el destinatario*. Renderizarla con el idioma activo
manda el correo en el idioma equivocado.

Regla: todo correo se renderiza dentro de
`translation.override(destinatario.language)`. Aplica a la invitación, al
restablecimiento de contraseña, a la verificación de correo y a las
notificaciones de ausencias. Tiene test propio.

### O.5.4 Cambio de idioma

Vista `set_language` de Django (obligatoriamente `POST` con CSRF), extendida para
persistir la elección en `User.language` cuando hay sesión iniciada. El selector
vive en el menú de usuario.

---

## O.6 Plantillas

- `{% load i18n %}` y `{% translate %}` / `{% blocktranslate %}`.
- `{% blocktranslate count n=... %}` para plurales; **nunca** un `{% if %}` que
  elija entre singular y plural: hay idiomas con más de dos formas.
- **Prohibido concatenar frases.** `{% translate "Total:" %} {{ n }}` es
  aceptable; partir una oración en dos cadenas, no: el traductor no puede
  reordenarla.
- `<html lang="{{ LANGUAGE_CODE }}">` — es un requisito de accesibilidad, no un
  detalle: los lectores de pantalla eligen la voz con ese atributo.
- Fechas e importes con los filtros localizados (`|date:"SHORT_DATE_FORMAT"`,
  `|floatformat` con `USE_THOUSAND_SEPARATOR`), nunca formateados a mano.
- **JavaScript:** las cadenas del JS se sirven con la vista `JavaScriptCatalog` y
  se usan con `gettext()` en los archivos de `static/js/`. Es compatible con la
  CSP estricta, porque el catálogo se entrega como **script externo del propio
  origen** (`script-src 'self'`) y no como código en línea.

---

## O.7 Qué **no** se traduce nunca

| Elemento | Motivo |
|---|---|
| Valores de `TextChoices` | Son datos; están en constraints y consultas |
| `employee_code`, `code` de catálogos, `public_id` | Identificadores |
| `AuditEvent.action`, `outcome`, `object_type`, `object_repr` | La bitácora debe ser unívoca y buscable |
| Mensajes de log | Ídem |
| `codename` de los permisos | Es una clave, no un texto |
| Datos capturados por RRHH | Ver O.3.4 |
| Nombres de campos y modelos en el código | El código es en inglés |

> **Trampa conocida:** `auth.Permission.name` se **almacena en la base de datos**
> con el texto vigente al ejecutar la migración, y no se retraduce después. Por
> eso la interfaz **no muestra `Permission.name` en crudo**: la matriz de roles usa
> etiquetas propias traducibles, mapeadas por `codename`. Es la misma razón por la
> que la vista de auditoría traduce `action` con un diccionario y no muestra el
> valor almacenado.

---

## O.8 Flujo de trabajo

```
Escribir el literal en inglés con _()
        ↓
django-admin makemessages -l es_GT -l en
        ↓
Traducir en locale/<lang>/LC_MESSAGES/django.po
        ↓
django-admin compilemessages          (genera .mo)
        ↓
Commit del .po   ·   el .mo NO se versiona
```

| Decisión | Valor |
|---|---|
| `.po` en Git | **Sí.** Es la fuente; se revisa en el PR como cualquier otro código |
| `.mo` en Git | **No.** Es un artefacto binario derivado; se compila en el build/despliegue. Va en `.gitignore` |
| `makemessages` para JS | `-d djangojs` en un paso aparte |
| Dependencia del sistema | `gettext`. En CI (Ubuntu) se instala con el gestor de paquetes; **en Windows hay que instalarlo aparte o trabajar en WSL** — conviene decirlo en el README para que no sorprenda |

### Control en CI

No existe un `makemessages --check`, así que se usa el patrón habitual:

1. Ejecutar `makemessages` en el pipeline.
2. `git diff --exit-code locale/` → si hay diferencias, **hay cadenas nuevas sin
   extraer** y el PR falla.
3. Un script propio falla si en `es_GT` hay `msgstr` vacíos o marcados `fuzzy`.

Así es imposible fusionar una pantalla nueva con texto sin traducir.

---

## O.9 Pruebas

| Test | Qué verifica |
|---|---|
| Formato numérico | `Decimal("1500.00")` se renderiza como `1,500.00` — **protege contra la trampa de O.2.2** |
| Formato de fecha | Una fecha se renderiza como `09/09/2026` |
| `__str__` invariable | `str(obj)` es idéntico bajo `translation.override("en")` y `("es-gt")` |
| Vistas en ambos idiomas | Las pantallas principales responden 200 en `es-gt` y en `en` |
| Correo del destinatario | Una invitación a un usuario con `language="en"` sale en inglés aunque quien invita tenga `es-gt` |
| Preferencia persistente | Cambiar el idioma lo guarda en `User.language` y sobrevive a un nuevo inicio de sesión |
| Catálogo completo | Sin `msgstr` vacíos ni `fuzzy` en `es_GT` |
| Valores no traducidos | Los valores de `TextChoices` almacenados son idénticos en ambos idiomas |
| `lang` en el HTML | El atributo coincide con el idioma activo |

---

## O.10 Impacto sobre el diseño ya documentado

| Documento | Cambio |
|---|---|
| [02 — Modelo relacional](../database/02-modelo-relacional.md) | `User` gana el campo `language` |
| [06 — Diccionario de datos](../database/06-diccionario-de-datos.md) | Ídem, y convención de `verbose_name`/`help_text` traducibles |
| [08 — Arquitectura Django](08-arquitectura-django.md) | Directorios `locale/` y `config/formats/`; responsabilidad de traducción por capa |
| [11 — Seguridad](../security/11-seguridad.md) | `JavaScriptCatalog` es compatible con la CSP estricta; los logs no se traducen |
| [12 — DevSecOps](../development/12-devsecops.md) | `gettext` en CI, verificación de catálogos, `.mo` en `.gitignore` |
| [13 — Roadmap](../development/13-roadmap.md) | i18n forma parte de los entregables de la Fase 1 |
| ADR | **ADR-018** — estrategia de internacionalización |

**Ninguno de estos cambios altera el modelo relacional más allá de una columna.**
La i18n bien planteada es una decisión de disciplina, no de esquema — y ese es
precisamente el motivo por el que conviene tomarla ahora.
