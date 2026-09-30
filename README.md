# Sistema de Gestión de Recursos Humanos

Monolito modular en Django para la administración de personal: expediente,
estructura organizacional, contratos, asistencia, ausencias, documentos y nómina.

**Estado: Fase 1 — Fundación.** El andamiaje de calidad, seguridad e
internacionalización está en pie. La autenticación llega en la Fase 2 y el
dominio de RRHH en la Fase 3. Ver el [roadmap](docs/development/13-roadmap.md).

---

## Objetivo

Construir una base **relacional, segura y probada** sobre la que un sistema de
RRHH pueda crecer, en lugar de un CRUD que funcione hoy y estorbe mañana. Las
prioridades del proyecto, en orden: integridad del modelo de datos, seguridad,
correctitud, mantenibilidad, testabilidad, escalabilidad, legibilidad,
simplicidad y rendimiento.

---

## Arquitectura

Monolito modular: **un despliegue, un esquema, fronteras internas explícitas**.
Sin microservicios, sin API REST, sin SPA — cada una de esas piezas se añadiría
solo con una razón de negocio documentada en un ADR.

```
config/     Proyecto Django: settings por entorno, urls, formatos localizados
apps/       Un contexto de dominio por app, con interfaz pública explícita
templates/  Plantillas globales, includes y páginas de error
static/     CSS y JavaScript vanilla (sin frameworks, sin código en línea)
locale/     Catálogos de traducción (.po versionado, .mo no)
docs/       Diseño, decisiones y documentación viva
scripts/    Utilidades de operación y de CI
tests/      Pruebas transversales: integración y seguridad
```

Cada app separa responsabilidades en `models` (datos e invariantes),
`selectors` (lecturas con alcance de autorización), `services` (escrituras
transaccionales y auditoría), `forms`, `views` y `templates`. El detalle está en
[Arquitectura Django](docs/architecture/08-arquitectura-django.md).

### Apps implementadas

| App | Estado | Contenido |
|---|---|---|
| `core` | Fase 1 | `TimeStampedModel`, `Company`, `Holiday`, excepciones de dominio, filtros de logging, middleware de `request_id` |
| `accounts` | Fase 1 | Modelo `User` propio (login por correo, sin `username`) |
| `audit` | Fase 1 | `AuditEvent` append-only y su servicio de registro |
| `employees` | Fase 3 | Personas, fichas, identificaciones, contactos y PII enmascarada |
| `departments`, `positions` | Fase 3 | Organigrama, jefaturas con historial, puestos y bandas salariales |
| `contracts` | Fase 4 | Contratos, historial salarial y asignaciones |
| `attendance` | Fase 5 | Jornadas, marcaje, incidencias y cierre diario |
| `leave` | Fase 6 | Tipos, devengo por antigüedad, aprobación y libro de saldos |
| `documents` | Fase 7 | Expediente con validación de archivos y descarga auditada |
| `reports` | Módulo transversal | Cuatro reportes con Excel y PDF con QR |
| `dashboard` | UX | Inicio por rol |
| `payroll` | Pendiente | Fase 8, ver roadmap |

---

## Modelo de datos

El diseño relacional se hizo **antes** que el código y está documentado por
completo. Todas las relaciones están en BCNF; las excepciones (snapshots
históricos) están justificadas una por una.

| Documento | Contenido |
|---|---|
| [Análisis del dominio](docs/architecture/01-analisis-de-dominio.md) | Entidades, agregados, cardinalidades y 60 reglas de negocio numeradas |
| [Modelo relacional](docs/database/02-modelo-relacional.md) | Claves primarias, candidatas, foráneas y restricciones |
| [Dependencias funcionales](docs/database/03-dependencias-funcionales.md) | DF por entidad y dependencias evitadas |
| [Normalización](docs/database/04-normalizacion.md) | Demostración 1NF→5NF y análisis de anomalías |
| [ERD](docs/database/05-erd.md) | Diagramas Mermaid, globales y por contexto |
| [Diccionario de datos](docs/database/06-diccionario-de-datos.md) | Atributos, tipos, reglas y clasificación de la información |
| [Integridad e índices](docs/database/07-integridad-e-indices.md) | `on_delete` por FK, constraints e índices con su consulta justificante |

---

## Requisitos

- **Python 3.12 o superior** (desarrollado sobre 3.14; el CI prueba ambos extremos)
- **gettext**, para trabajar con las traducciones
  - Linux: `apt-get install gettext`
  - macOS: `brew install gettext`
  - **Windows: no viene incluido.** Instálalo aparte o trabaja en WSL. Sin él,
    `makemessages` y `compilemessages` fallan; el resto del proyecto funciona.

---

## Instalación

```bash
git clone <url-del-repositorio>
cd rrhh-system-management-django

python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r requirements/development.txt

cp .env.example .env        # y edítalo
python manage.py migrate
python manage.py bootstrap_admin   # primera cuenta: correo verificado + rol SUPERADMIN
python manage.py runserver
```

La aplicación queda en <http://127.0.0.1:8000/> y el admin en `/admin/`.

### Hooks de pre-commit

```bash
pre-commit install
```

---

## Configuración

Todo valor sensible o dependiente del entorno se lee de variables de entorno.
**`.env` nunca se versiona**; `.env.example` documenta cada clave.

| Variable | Obligatoria | Descripción |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | Sí | `config.settings.{development,testing,production}` |
| `SECRET_KEY` | En producción | Sin valor por defecto: si falta, el proceso **no arranca** |
| `DEBUG` | — | `False` salvo en desarrollo |
| `ALLOWED_HOSTS` | En producción | Lista separada por comas |
| `CSRF_TRUSTED_ORIGINS` | Tras un proxy | — |
| `DATABASE_URL` | No | Sin definir, SQLite. `postgres://…` para PostgreSQL |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | En producción | Mailer SMTP |
| `DEFAULT_FROM_EMAIL`, `ADMIN_EMAILS` | En producción | — |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` | En producción | Redirección y HSTS |
| `BEHIND_TRUSTED_PROXY` | Solo con proxy | Habilita `X-Forwarded-Proto` y `X-Forwarded-For`. **Activarlo sin proxy permitiría falsificar la IP registrada** |
| `MEDIA_ROOT` | En producción | Debe quedar **fuera** del árbol servido por el servidor web |

Genera una clave de producción con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

---

## Comandos habituales

```bash
python manage.py runserver            # servidor de desarrollo
python manage.py makemigrations       # generar migraciones
python manage.py migrate              # aplicarlas
python manage.py bootstrap_admin      # primera cuenta (no uses createsuperuser: su correo queda sin verificar y no puede entrar)
python manage.py check                # checks del sistema
python manage.py shell                # shell con el proyecto cargado
python manage.py seed_demo            # datos de demostración (solo con DEBUG=True)
```

### Datos de demostración

`seed_demo` carga una organización inventada para ver el sistema funcionando:
doce personas en tres áreas con sus jefaturas, contratos activos con salario y
puesto, dos semanas de marcajes con tardanzas y horas extra, medio año de
devengo de vacaciones, solicitudes en distintos estados y expedientes con
documentos —uno confidencial y otro por vencer—.

No hace inserciones crudas: **todo pasa por los servicios**, así que los datos
respetan las mismas invariantes que en producción y dejan su rastro en la
bitácora. Vive en `apps.demo`, que **solo se instala en desarrollo**, y el
comando además se niega a ejecutarse con `DEBUG=False`.

```bash
python manage.py seed_demo                      # carga la organización completa
python manage.py seed_demo --people 4           # una organización más pequeña
python manage.py seed_demo --attendance-days 0  # sin marcajes, más rápido
```

Si los datos ya están cargados no toca nada. Para empezar de cero, borre
`db.sqlite3`, vuelva a aplicar las migraciones y ejecútelo otra vez.

Las cuentas de demostración se crean **sin contraseña utilizable**: nadie
hereda una clave conocida. Para entrar con una de ellas, fíjela usted **con el
Python del entorno virtual** (el del sistema no tiene Django):

```bash
.venv\Scripts\python.exe manage.py changepassword ana.lopez@ceiba.test
```

Si ve `ModuleNotFoundError: No module named 'django'`, la terminal no está
usando el entorno virtual: actívelo (`.venv\Scripts\Activate.ps1`) o use la
ruta de arriba.

### Migraciones

Siempre generadas por Django; **nunca se modifica la base a mano**. Antes de
fusionar, el CI verifica que no haya modelos sin su migración:

```bash
python manage.py makemigrations --check --dry-run
```

---

## Pruebas

```bash
pytest                                   # suite completa
pytest -m security                       # solo pruebas de seguridad
pytest --cov --cov-report=html           # informe de cobertura en htmlcov/
pytest apps/audit -q                     # una app concreta
```

Objetivo de cobertura: **≥ 80 %** global, con umbrales más altos en servicios,
selectores y modelos. Estado actual: **109 pruebas, 95 %**.

Las pruebas se agrupan con marcadores: `unit`, `integration`, `security`, `slow`.

---

## Calidad de código

```bash
ruff check .          # linting
ruff check . --fix    # con correcciones automáticas
ruff format .         # formateo
ruff format --check . # verificación (lo que corre el CI)
```

Ruff hace de linter y formateador: no hay black, isort ni flake8.

> `target-version = "py312"` está fijado a propósito. Con `py314`, Ruff reescribe
> `except (A, B):` a la sintaxis sin paréntesis de PEP 758, que solo existe desde
> Python 3.14 y dejaría el código sin poder ejecutarse en 3.12 o 3.13.

---

## Internacionalización

Los literales del código se escriben **en inglés** y se traducen a `es-GT`
(idioma por defecto de la interfaz).

```bash
python manage.py makemessages --locale es_GT --locale en --ignore=.venv
python manage.py compilemessages
python scripts/check_translations.py    # falla si hay cadenas sin traducir
```

Se versiona el `.po`; el `.mo` se compila en el despliegue y está en
`.gitignore`. Los formatos numéricos y de fecha de Guatemala viven en
`config/formats/es_GT/formats.py` y están fijados por pruebas: sin ese módulo,
un salario se mostraría con la coma decimal de España. El criterio completo está
en [Internacionalización](docs/architecture/14-internacionalizacion.md).

---

## Seguridad

Documentación: [autenticación](docs/security/09-autenticacion.md) ·
[autorización](docs/security/10-autorizacion.md) ·
[seguridad](docs/security/11-seguridad.md).

Ya activo en la Fase 1:

- **CSP estricta** con nonce por petición, sin `unsafe-inline` ni `unsafe-eval`.
  En desarrollo arranca en modo informe; en pruebas y producción, bloquea.
- **Cabeceras**: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`,
  `Cross-Origin-Opener-Policy: same-origin`; HSTS y redirección HTTPS en producción.
- **Cookies** de sesión `HttpOnly` + `SameSite=Lax`, `Secure` en producción.
- **Contraseñas** con Argon2 y longitud mínima de 12.
- **Auditoría append-only**: los permisos `change`/`delete` de `AuditEvent` ni
  siquiera se generan, y el borrado del actor conserva el evento.
- **Logs sin secretos**: un filtro de redacción depura contraseñas, tokens,
  cookies e identificadores personales antes de que lleguen a ningún handler.
- **`MEDIA_ROOT` no se sirve**: los documentos se entregarán desde una vista que
  autoriza primero (Fase 7).

```bash
python manage.py check --deploy      # con settings de producción, sin advertencias
bandit -c pyproject.toml -r apps config -ll
pip-audit --strict
git ls-files -z | xargs -0 detect-secrets-hook --baseline .secrets.baseline
```

Si un secreto llega a Git: **se rota primero** y se limpia el historial después.
Reescribir el historial no invalida lo que otros ya clonaron.

---

## DevSecOps

El pipeline ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) corre en
cada push y PR sobre `main`, con seis trabajos en paralelo:

| Trabajo | Falla si… |
|---|---|
| `lint` | Ruff encuentra algo o hay archivos sin formatear |
| `security` | Bandit halla severidad media/alta, `pip-audit` encuentra una vulnerabilidad o aparece un secreto nuevo |
| `django-checks` | Los checks fallan, `check --deploy` emite **cualquier advertencia**, o hay modelos sin migración |
| `i18n` | Hay cadenas sin extraer o sin traducir |
| `test-sqlite` | Falla una prueba o baja la cobertura (Python 3.12 y 3.14) |
| `test-postgres` | La suite se comporta distinto en PostgreSQL que en SQLite |

El trabajo `test-postgres` existe desde el primer día a propósito: detecta las
divergencias entre motores cuando se introducen, no el día de la migración.

---

## Flujo de desarrollo

1. Rama desde `main`.
2. Escribe primero la prueba de acceso no autorizado si tocas una vista.
3. `pre-commit` se encarga del formato y de los controles rápidos.
4. `pytest` en local antes de abrir el PR.
5. PR con el CI en verde y una revisión aprobada.
6. Actualiza la documentación **en el mismo commit** que cambia el diseño: una
   migración que altera relaciones sin actualizar el ERD debe rechazarse en
   revisión.

Una fase no se cierra hasta cumplir todos sus
[criterios de aceptación](docs/development/12-devsecops.md#l7-criterios-de-aceptación-de-una-fase).

---

## Decisiones de arquitectura

Las decisiones costosas de revertir se documentan como ADR. El índice y la
plantilla están en [docs/decisions](docs/decisions/README.md); la primera
aceptada es
[ADR-004 — Alta de cuentas y registro cerrado](docs/decisions/ADR-004-alta-de-cuentas-y-registro-cerrado.md).

---

## Documentación

El índice completo está en [docs/README.md](docs/README.md).
