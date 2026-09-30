# L. DevSecOps

Cubre las reglas 41–48 y 60. Todo lo descrito aquí se implementa en la **Fase 1**,
antes que cualquier modelo de dominio: una barrera de calidad añadida al final no
detiene nada, porque el código problemático ya está dentro.

---

## L.1 Dependencias

Se dividen por entorno para que producción no instale herramientas de desarrollo
(regla 46):

```
requirements/
├── base.txt          # Django, django-allauth, django-csp, argon2-cffi, python-dotenv
├── development.txt   # -r base.txt + pytest, pytest-django, pytest-cov, factory-boy,
│                     #   ruff, bandit, pip-audit, detect-secrets, pre-commit,
│                     #   django-debug-toolbar
└── production.txt    # -r base.txt + gunicorn, psycopg[binary] (cuando toque)
```

**Inventario inicial y justificación de cada dependencia no obvia:**

| Paquete | Por qué | Alternativa descartada |
|---|---|---|
| `django-allauth` | Exigido por el enunciado. Aporta verificación de correo, límites de tasa y MFA futura sin cambiar de librería | Auth de Django a secas: habría que escribir la verificación de correo |
| `django-csp` | Nonce por petición y política por vista. Escribirlo a mano es fácil de hacer mal | Middleware propio |
| `argon2-cffi` | Hasher recomendado por OWASP y documentado por Django | PBKDF2 por defecto (aceptable; ADR-013) |
| `python-dotenv` | Cargar `.env` en desarrollo | Variables exportadas a mano: frágil entre Windows y Linux |
| `factory-boy` | Fixtures legibles y sin acoplar los tests al esquema | Fixtures JSON: se rompen con cada migración |

**Dependencia del sistema (no de pip):** `gettext`, necesaria para
`makemessages`/`compilemessages`. Se instala en el runner de CI; en Windows hay
que instalarla aparte o trabajar en WSL, y así debe advertirlo el README.

**Todo lo demás se justifica en revisión.** Se fijan versiones exactas (`==`) en
`base.txt` y `production.txt` para que las compilaciones sean reproducibles;
`development.txt` admite rangos menores en las herramientas.

**Actualización:** mensual, o inmediata ante un aviso de `pip-audit`. El
procedimiento se documenta en `docs/development/`: actualizar, ejecutar la suite,
revisar el changelog de los paquetes con cambios de mayor, abrir PR propio (nunca
mezclado con cambios funcionales).

---

## L.2 Ruff (`pyproject.toml`)

Ruff hace de linter **y** de formateador; no se instalan `black`, `isort` ni
`flake8` (regla 43).

Conjuntos de reglas activos:

| Código | Qué cubre | Por qué |
|---|---|---|
| `E`, `W` | pycodestyle | PEP 8 |
| `F` | pyflakes | Errores reales, imports y variables sin usar |
| `I` | isort | Orden de imports |
| `N` | pep8-naming | Nomenclatura |
| `UP` | pyupgrade | Sintaxis moderna de Python |
| `B` | flake8-bugbear | Errores frecuentes (mutable por defecto, `except` amplio) |
| `A` | builtins | No sombrear built-ins |
| `C4` | comprehensions | — |
| `DTZ` | flake8-datetimez | **`datetime` sin zona horaria.** Crítico con `USE_TZ=True` |
| `DJ` | flake8-django | `null=True` en `CharField`, `__str__` ausente, `on_delete` faltante |
| `S` | flake8-bandit | Solapa con bandit; detecta en el editor |
| `RUF` | reglas propias de Ruff | — |
| `SIM` | simplificaciones | — |
| `ARG` | argumentos sin usar | Código muerto |
| `PTH` | uso de `pathlib` | — |

Excepciones acotadas: `migrations/` excluida de `E501` y `N`; `settings/*.py`
exenta de `F403`/`F405` (imports con estrella entre módulos de configuración);
`tests/` exenta de `S101` (`assert` es su herramienta).

```
line-length = 100
target-version = "py312"
```

Comandos obligatorios: `ruff check .` y `ruff format --check .`

---

## L.3 Tests

`pytest` + `pytest-django` (regla 41). Configuración en `pyproject.toml`:

- `DJANGO_SETTINGS_MODULE = "config.settings.testing"`
- `--strict-markers` (un marcador con errata falla en vez de ignorarse)
- `--reuse-db` en local para agilizar; base limpia en CI
- Marcadores: `unit`, `integration`, `security`, `slow`

### Qué se prueba

| Capa | Contenido |
|---|---|
| **Modelos** | Cada `CheckConstraint` y `UniqueConstraint` verificado con un `IntegrityError` esperado; `__str__`; propiedades derivadas; comportamiento de `on_delete` (que `PROTECT` realmente protege) |
| **Servicios** | Casos de uso completos; invariantes entre filas (traslapes, FTE, saldo); atomicidad (que un fallo a mitad no deje estado parcial); emisión del `AuditEvent` |
| **Selectores** | Que el alcance por rol devuelve **exactamente** el conjunto esperado, incluidos los casos vacíos |
| **Formularios** | Datos válidos e inválidos, campos requeridos, ausencia de campos prohibidos, `queryset` acotado en los `ModelChoiceField` |
| **Vistas** | Matriz rol × URL × método × código esperado; redirecciones; mensajes; paginación; número de consultas |
| **Seguridad** | Suite propia: CSRF, IDOR, escalada, acceso no autorizado, subida de archivos maliciosos, path traversal, open redirect, cabeceras de seguridad presentes |
| **Integración** | Flujos completos (regla 41): alta de empleado → contrato → asignación → solicitud de ausencia → aprobación → verificación del rastro de auditoría |
| **i18n / l10n** | Formato de importes y fechas (la trampa de los separadores), `__str__` invariable al idioma, vistas en ambos idiomas, correos en el idioma del destinatario. Ver [O.9](../architecture/14-internacionalizacion.md) |

### Principios

- **Tests de seguridad negativos primero.** Al implementar una vista, se escribe
  antes el test que comprueba que un usuario no autorizado recibe 403/404.
- Fábricas (`factory-boy`) por dominio, sin fixtures JSON.
- **Sin red ni servicios externos** en la suite; correo con `locmem`.
- Los tests de dinero y de fechas se ejecutan **también** contra PostgreSQL en CI.
- `assertNumQueries` en las vistas de listado, como red contra los N+1.

---

## L.4 Cobertura

Objetivo inicial **≥ 80 %** global (regla 42), con umbrales más exigentes en lo
crítico:

| Zona | Umbral |
|---|---|
| `apps/*/services.py` | 95 % |
| `apps/*/selectors.py` | 95 % |
| `apps/*/models.py` | 90 % |
| `apps/*/forms.py` | 90 % |
| `apps/*/views.py` | 85 % |
| `apps/audit/` | 95 % |
| Global | 80 %, subiendo un punto por fase hasta 90 % |

Excluidos de la medición: `migrations/`, `settings/`, `manage.py`, `wsgi/asgi`,
`admin.py` (registro declarativo), y los propios tests.

`fail_under` configurado: el CI falla si baja. **No se escriben tests artificiales
para alcanzar el número** (regla 42); si una zona no llega, se decide
explícitamente si falta prueba o sobra código.

---

## L.5 Pre-commit

Rápido: el objetivo es que nadie lo desactive por lentitud (regla 44).

| Hook | Qué hace |
|---|---|
| `ruff` (con `--fix`) | Lint y corrección automática |
| `ruff-format` | Formato |
| `check-yaml`, `check-toml`, `check-json` | Sintaxis de configuración |
| `end-of-file-fixer`, `trailing-whitespace` | Higiene |
| `check-merge-conflict` | Marcadores de conflicto olvidados |
| `check-added-large-files` (max 500 KB) | Evita subir binarios y SQLite |
| `detect-private-key` | Claves privadas |
| `detect-secrets` | Secretos, con línea base versionada |
| `bandit` (solo `apps/` y `config/`) | Seguridad estática |
| `django-check` (hook local) | `manage.py check` |
| `no-missing-migrations` (hook local) | `makemigrations --check --dry-run`: impide commitear un modelo sin su migración |

**No** se ejecuta la suite completa en pre-commit: tardaría demasiado. Eso es
trabajo del CI.

---

## L.6 GitHub Actions

Un solo workflow (`.github/workflows/ci.yml`) que se dispara en `push` y
`pull_request` sobre `main`. Jobs en paralelo para que el resultado llegue rápido:

```
┌── lint ──────────────┐   ruff check · ruff format --check
│
├── security ──────────┤   bandit -r apps config · pip-audit · detect-secrets
│
├── django-checks ─────┤   manage.py check · check --deploy (settings de producción)
│                      │   makemigrations --check --dry-run
│
├── i18n ──────────────┤   makemessages + git diff --exit-code locale/
│                      │   catálogo es_GT sin msgstr vacíos ni fuzzy
│
├── test-sqlite ───────┤   pytest --cov  (matriz: Python 3.12)
│
└── test-postgres ─────┘   pytest  contra PostgreSQL 16 (servicio contenedor)
                           ↓
                        gate: todos deben pasar
```

| Etapa | Falla el pipeline si… |
|---|---|
| Checkout + setup Python + caché de pip | — |
| Instalar dependencias | Falla la resolución |
| `ruff check .` | Cualquier hallazgo |
| `ruff format --check .` | Cualquier archivo sin formatear |
| `manage.py check` | Cualquier error del sistema de checks |
| `manage.py check --deploy` (producción) | **Cualquier advertencia** |
| `makemigrations --check --dry-run` | Hay cambios de modelo sin migración |
| `makemessages` + `git diff --exit-code locale/` | Hay cadenas nuevas sin extraer al catálogo (requiere `gettext` instalado en el runner) |
| Verificación de catálogos | `es_GT` tiene `msgstr` vacíos o marcados `fuzzy` |
| `pytest --cov --cov-fail-under=80` | Un test falla o baja la cobertura |
| `pytest` sobre PostgreSQL | Divergencia entre motores |
| `bandit -r apps config -ll` | Hallazgo de severidad media o alta |
| `pip-audit` | Vulnerabilidad conocida (`--strict`) |
| `detect-secrets-hook --baseline` sobre `git ls-files` | Secreto nuevo no auditado en la línea base (`scan --baseline` **no** sirve como control: reescribe la línea base y sale con 0) |

**Reglas de la rama `main`:** protegida, sin push directo, PR con CI en verde y
una revisión aprobada. Las migraciones y los cambios en `security/` requieren
revisión explícita del apartado correspondiente.

**Lo que el CI todavía no hace y se sabe:** no despliega, no construye imágenes,
no ejecuta pruebas de carga ni análisis DAST. Se añadirá cuando exista un entorno
al que desplegar (regla 56).

---

## L.7 Criterios de aceptación de una fase

Una fase se considera terminada **solo** si (regla 60):

```
[ ] La funcionalidad cumple lo especificado
[ ] Todos los tests pasan en local y en CI
[ ] ruff check . y ruff format --check . sin hallazgos
[ ] Cobertura ≥ objetivo global y por zona crítica
[ ] bandit sin severidad media/alta
[ ] pip-audit sin vulnerabilidades conocidas
[ ] detect-secrets sin hallazgos nuevos
[ ] manage.py check y check --deploy sin advertencias
[ ] Las migraciones aplican sobre una base vacía Y sobre una con datos previos
[ ] Todo texto visible nuevo está marcado para traducción y el catálogo es_GT está completo
[ ] La suite pasa también contra PostgreSQL
[ ] Los permisos están probados para TODOS los roles
[ ] Existen tests de acceso indebido (IDOR, escalada, 403/404)
[ ] El checklist de seguridad de la fase está completo
[ ] La documentación (ERD, diccionario, ADR, README) está actualizada
[ ] No hay secretos en el repositorio ni en el historial
[ ] El CI está en verde
```

Si un punto no se cumple, la fase **no** se cierra. No se avanza a la siguiente
con deuda de calidad o de seguridad acumulada.
