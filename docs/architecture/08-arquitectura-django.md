# H. Arquitectura Django

Monolito modular: **un despliegue, un esquema, fronteras internas explícitas**.
No microservicios, no API REST, no SPA (regla 56).

---

## H.1 Estructura de directorios

```
rrhh-system-management-django/
│
├── config/                          # Proyecto Django (no contiene lógica de dominio)
│   ├── formats/                     # Formatos localizados propios
│   │   └── es_GT/formats.py         # Separadores y fechas de Guatemala (ver O.2.2)
│   ├── settings/
│   │   ├── __init__.py
│   │   ├── base.py                  # Común; lee variables de entorno, sin secretos
│   │   ├── development.py           # DEBUG=True, consola de correo, toolbar
│   │   ├── testing.py               # Hasher rápido, sin migraciones opcional, CSP report-only off
│   │   └── production.py            # Todas las cabeceras de seguridad activas
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── apps/
│   ├── core/                        # Primitivas compartidas. NO depende de nadie
│   ├── dashboard/                   # Inicio por rol. Sin modelos: compone otras apps
│   ├── accounts/
│   ├── employees/
│   ├── departments/
│   ├── positions/
│   ├── contracts/
│   ├── attendance/
│   ├── leave/
│   ├── documents/
│   ├── payroll/
│   └── audit/
│
├── templates/                       # Plantillas globales y de layout
│   ├── base.html
│   ├── includes/
│   └── errors/                      # 400, 403, 404, 500
│
├── locale/                          # Catálogos de traducción del proyecto
│   ├── es_GT/LC_MESSAGES/django.po  # .po versionado · .mo NO versionado
│   └── en/LC_MESSAGES/django.po
│
├── static/
│   ├── css/
│   └── js/                          # ES2019+ vanilla, sin frameworks
│
├── media/                           # NO servido directamente (ver seguridad de archivos)
│
├── tests/                           # Solo tests transversales / de integración
│   ├── conftest.py                  # Fixtures compartidas
│   ├── factories/                   # factory_boy por dominio
│   ├── integration/
│   └── security/                    # Suite de seguridad transversal
│
├── scripts/                         # Utilidades de operación (semillas, chequeos)
│
├── docs/                            # Este documento y sus hermanos
│   ├── architecture/  database/  security/  development/  decisions/
│
├── .github/workflows/ci.yml
├── requirements/
│   ├── base.txt  development.txt  production.txt
├── .env.example
├── .gitignore
├── .gitattributes
├── .pre-commit-config.yaml
├── pyproject.toml                   # Ruff, pytest, coverage
├── manage.py
└── README.md
```

**Desviaciones respecto de la estructura sugerida en el enunciado** (regla 27
permite desviarse explicándolo):

1. **Los tests viven junto a cada app** (`apps/<app>/tests/`), no todos en
   `tests/`. `tests/` se reserva para lo que cruza fronteras: flujos de
   integración y la suite de seguridad transversal. Motivo: los tests de una app
   son parte de esa app; separarlos duplica la estructura y hace que mover un
   módulo signifique tocar dos árboles.
2. **Se añade `docs/`** con la taxonomía de la regla 53.
3. **Se añade `.gitattributes`** (regla 52) fijando `* text=auto eol=lf`, crítico
   en un equipo mixto Windows/Linux para que el CI y `pre-commit` no discrepen.
4. **Se añaden `locale/` y `config/formats/`** por la internacionalización. Los
   catálogos van en el proyecto y no por app: una sola ubicación que traducir y
   revisar.

---

## H.2 Anatomía de una app

```
apps/employees/
├── __init__.py
├── apps.py
├── admin.py            # Registro en el admin, con readonly y permisos afinados
├── constants.py        # TextChoices y constantes del dominio
├── forms.py            # ModelForms y Forms, con campos EXPLÍCITOS
├── migrations/
├── models.py           # (o models/ si crece) Datos + invariantes locales
├── selectors.py        # Consultas de LECTURA, con alcance de autorización
├── services.py         # Casos de uso de ESCRITURA, transaccionales
├── urls.py
├── validators.py       # Validadores reutilizables del dominio
├── views.py
├── templates/employees/
└── tests/
    ├── test_models.py
    ├── test_forms.py
    ├── test_views.py
    ├── test_services.py
    ├── test_selectors.py
    └── test_permissions.py
```

**No se crean archivos vacíos por simetría.** Una app sin lógica de escritura no
tiene `services.py` hasta que la necesita (YAGNI, regla 56).

---

## H.3 Responsabilidad de cada capa

| Capa | Sí hace | No hace |
|---|---|---|
| **`models.py`** | Estructura, relaciones, constraints, `Meta`, `__str__`, `get_absolute_url`, propiedades derivadas baratas y validaciones **locales a la fila** en `clean()` | Enviar correo, escribir auditoría, orquestar otros modelos, comprobar permisos, hacer consultas pesadas en `save()` |
| **`selectors.py`** | Todas las consultas de lectura no triviales. Recibe `user` y **devuelve un queryset ya acotado** a lo que ese usuario puede ver. Aplica `select_related`/`prefetch_related` | Escribir. Decidir sobre HTTP |
| **`services.py`** | Casos de uso de escritura. Abre `transaction.atomic()`, valida invariantes entre filas, actualiza estado, emite el `AuditEvent`. Lanza excepciones de dominio | Conocer `HttpRequest`, renderizar, formatear mensajes de usuario |
| **`forms.py`** | Validación y saneamiento de la entrada. Campos declarados **uno a uno**. Limita los `queryset` de los `ModelChoiceField` a lo permitido | Contener reglas de negocio entre entidades. Ser la única barrera de seguridad |
| **`views.py`** | Traducir HTTP ↔ dominio: comprobar permisos, construir el formulario, llamar al servicio o selector, elegir plantilla, poner mensajes | Contener lógica de negocio. Hacer consultas ad-hoc complejas |
| **`urls.py`** | Enrutamiento con `path()` y nombres de ruta | — |
| **`templates/`** | Presentación y accesibilidad | **Cualquier decisión de seguridad** (regla 3) |
| **`admin.py`** | Herramienta de administración con permisos restringidos | Ser el CRUD principal del negocio |

### Responsabilidad de internacionalización por capa

Se resume aquí porque atraviesa todas las capas; el detalle está en
[O. Internacionalización](14-internacionalizacion.md).

| Capa | Qué traduce | Qué **no** traduce |
|---|---|---|
| `models.py` | `verbose_name`, `verbose_name_plural`, `help_text`, etiquetas de `choices`, mensajes de validación y de constraints | Los **valores** de `choices`, y `__str__` (se usa en logs y en `AuditEvent.object_repr`) |
| `services.py` | **Nada.** Devuelve códigos de error estables | Todo |
| `selectors.py` | Nada | Todo |
| `forms.py` | `error_messages` propios; hereda los `label` del `verbose_name` en lugar de repetirlos | — |
| `views.py` | Traduce el código de error del servicio y los mensajes al usuario | Lo que va al log |
| `templates/` | Todo el texto visible, con `{% translate %}` / `{% blocktranslate %}` | — |
| `static/js/` | Cadenas vía `JavaScriptCatalog` (script externo, compatible con la CSP) | — |

La regla que ordena todo: **lo que ve una persona se traduce; lo que se consulta,
se busca o se compara, no.**

### ¿Por qué `services` y `selectors` desde el inicio?

La regla 38 advierte contra aplicar patrones por moda. Aquí no se introduce una
capa de repositorios ni inyección de dependencias: solo **dos módulos de
funciones**. La justificación es concreta y verificable:

1. La **autorización a nivel de objeto** debe ocurrir en un solo lugar. Si cada
   vista construye su propio queryset, un IDOR es cuestión de tiempo. Con
   `selectors.employees_visible_for(user)`, existe **un** punto que auditar y
   testear.
2. Los **invariantes entre filas** (no traslape, saldo, FTE) requieren
   transacción y bloqueo. Ponerlos en `save()` los ejecuta en contextos donde no
   corresponde y no cubre `bulk_create`.
3. La **auditoría** debe emitirse junto al cambio, en la misma transacción. El
   servicio es el sitio natural.

Si una operación es un CRUD trivial sin invariantes ni auditoría (por ejemplo, el
alta de un `Holiday`), **la vista puede usar el `ModelForm` directamente**. No se
escribe un servicio de una línea por simetría.

### Excepciones de dominio

`apps/core/exceptions.py` define una jerarquía mínima:

```
DomainError                 # base
├── ValidationError         # dato inválido (400 / re-render del form)
├── ConflictError           # invariante violada (traslape, saldo insuficiente)
├── PermissionDeniedError   # se traduce a 403
└── NotFoundError           # se traduce a 404
```

Los servicios lanzan estas excepciones; las vistas las traducen a respuestas HTTP.
Los servicios nunca devuelven `HttpResponse`.

---

## H.4 Reglas de dependencia entre apps

1. `core` **no importa** ninguna otra app.
2. Ninguna app importa `models` de otra app directamente en su lógica: consume la
   **interfaz pública** (`services.py`, `selectors.py`, `constants.py`) de la
   otra.
3. Las FKs entre apps se declaran **por string** (`"employees.Employee"`), nunca
   importando la clase. Evita ciclos de importación y mantiene el acoplamiento en
   el esquema, no en el código.
4. La dirección permitida es la del grafo de [A.1](01-analisis-de-dominio.md#a1-contextos-delimitados-bounded-contexts).
   Una dependencia en sentido contrario requiere justificación en la revisión.
5. `audit` es consumida por todas, pero **no importa** ninguna: recibe cadenas y
   diccionarios, no objetos tipados de otros dominios.

**Verificación:** se añadirá al CI una comprobación de fronteras (un test que
recorre los imports de cada app y falla ante una dependencia no declarada). Es
una prueba de ~40 líneas y es la única forma de que la modularidad no se erosione
en el mes tres.

---

## H.5 Vistas: FBV o CBV

Criterio explícito (regla 2), para evitar discusiones por gusto:

| Caso | Elección |
|---|---|
| Listado paginado y filtrable | `ListView` con `get_queryset()` delegando en el selector |
| Detalle | `DetailView` con `get_object()` sobre el queryset del selector |
| Alta/edición con un servicio detrás | **FBV.** El flujo `form → service → mensaje → redirect` es más legible explícito que repartido entre seis métodos de `CreateView` |
| Acciones de dominio (aprobar, terminar, cancelar) | **FBV** con `require_POST` |
| Confirmación de borrado | `DeleteView` solo si el borrado es realmente admitido; en general, FBV de cambio de estado |
| Descarga de archivo | **FBV**, con autorización explícita antes de abrir el archivo |

**Toda** vista pasa por autenticación y autorización explícita: `LoginRequiredMixin`
o `@login_required`, más la comprobación de permiso y de objeto. No se depende del
enrutamiento ni de la ocultación de enlaces.

---

## H.6 Plantillas

```
templates/
├── base.html                    # <head>, nonce de CSP, bloques, sin lógica
├── includes/
│   ├── navbar.html              # Barra lateral agrupada (UX-1); ítems con {% if perms.x %}, por UX, NO por seguridad
│   ├── sidebar.html
│   ├── messages.html            # django.contrib.messages
│   ├── pagination.html
│   ├── form_field.html          # Render accesible de un campo: label, ayuda, errores
│   └── confirm_modal.html
├── errors/
│   ├── 400.html  403.html  404.html  500.html
└── <app>/                       # Plantillas específicas dentro de cada app
```

Reglas:

- Herencia con `{% extends %}`, reutilización con `{% include %}` (regla 40).
- **Nunca `|safe`, `mark_safe` ni `autoescape off`** sobre datos de usuario. Su
  uso requiere justificación en revisión.
- Sin JavaScript en línea: los scripts van en `static/js/` (requisito de la CSP
  estricta, ver [K](../security/11-seguridad.md)).
- `{% if perms.employees.view_contractsalary %}` sirve para **no mostrar** un
  botón inútil; la protección real está en la vista.
- Accesibilidad: `<label for>` en todo campo, `aria-describedby` para errores,
  contraste suficiente, foco visible, tablas con `<th scope>`.
- Diseño responsive con CSS propio (grid/flex). Sin framework CSS por ahora; si
  se adopta uno, será por ADR.

---

## H.7 Configuración

`config/settings/base.py` no contiene ningún secreto. Todo valor sensible o
dependiente del entorno se lee de variables de entorno con un valor por defecto
**seguro** (o sin defecto, fallando ruidosamente):

| Variable | Obligatoria en producción | Nota |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | Sí | — |
| `SECRET_KEY` | Sí | Sin valor por defecto en `production.py`: si falta, el arranque falla |
| `DEBUG` | Sí | `False` por defecto |
| `ALLOWED_HOSTS` | Sí | Lista separada por comas |
| `CSRF_TRUSTED_ORIGINS` | Sí | — |
| `DATABASE_URL` | No (SQLite por defecto en desarrollo) | Prepara la migración a PostgreSQL sin tocar código |
| `EMAIL_*` | Sí | En desarrollo, backend de consola |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | Sí | Desactivados en desarrollo (regla 29) |
| `MEDIA_ROOT` | Sí | Fuera del árbol servido por el servidor web |

`.env` **nunca** se versiona; `.env.example` documenta todas las claves con
valores ficticios.

`testing.py` usa el hasher MD5 de Django solo para acelerar la suite; está
**explícitamente prohibido** en cualquier otro entorno y el archivo lleva un
comentario que lo advierte.

---

## H.8 Rendimiento (sin optimización prematura)

Se aplican desde el inicio solo las prácticas cuyo costo es cero (regla 51):

1. **Paginación obligatoria** en todo listado. Ninguna vista devuelve un queryset
   sin acotar.
2. **`select_related` / `prefetch_related` en los selectores**, no dispersos por
   las plantillas.
3. **Prohibición de consultas en bucles de plantilla.** Se detecta con un test que
   cuenta consultas (`assertNumQueries`) en las vistas de listado; ese test es la
   red que impide que un N+1 se cuele en el mes tres.
4. `django-debug-toolbar` solo en desarrollo.

No se introduce caché, ni tareas en segundo plano, ni réplicas de lectura hasta
que exista una medición que lo exija.
