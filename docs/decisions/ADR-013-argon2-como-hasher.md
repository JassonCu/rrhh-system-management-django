# ADR-013 — Argon2 como hasher principal de contraseñas

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1

---

## Contexto

El sistema almacena contraseñas de personal de RRHH, que tiene acceso a datos
salariales, documentos laborales e identificadores personales. Si la base se
filtra, el tiempo que resista el hash es la diferencia entre un incidente
contenido y una brecha de credenciales.

Django trae PBKDF2 por defecto y soporta Argon2, bcrypt y scrypt. El encargo
manda **no implementar criptografía a mano** (regla 30), que es exactamente lo
que aquí se cumple: se elige entre implementaciones probadas.

## Alternativas consideradas

### A. PBKDF2 por defecto de Django
- **A favor:** cero dependencias; implementación en la biblioteca estándar;
  perfectamente aceptable.
- **En contra:** al ser puramente iterativo y con poca huella de memoria, es el
  más favorable al atacante con GPU. Se defiende subiendo iteraciones, lo que
  encarece también cada inicio de sesión legítimo.

### B. Argon2id vía `argon2-cffi` *(elegida)*
- **A favor:** ganador del Password Hashing Competition y recomendación actual de
  OWASP para almacenamiento de contraseñas; su coste en **memoria** hace que el
  paralelismo masivo en GPU deje de ser barato. Es la vía que la propia
  documentación de Django señala.
- **En contra:** una dependencia con extensión compilada (`cffi`), lo que implica
  necesitar ruedas para cada versión de Python y plataforma.

### C. bcrypt
- **A favor:** muy contrastado.
- **En contra:** límite de 72 bytes en la entrada, sin coste de memoria
  configurable, y no aporta nada sobre Argon2 aquí.

### D. scrypt
- **A favor:** también tiene coste de memoria y viene en la biblioteca estándar.
- **En contra:** Django lo soporta pero es menos habitual en este ecosistema;
  Argon2id es la recomendación más actual.

## Decisión

Se adopta **B**, con esta lista ordenada:

```
django.contrib.auth.hashers.Argon2PasswordHasher      ← principal
django.contrib.auth.hashers.PBKDF2PasswordHasher      ← respaldo
django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher  ← respaldo heredado
```

Los respaldos no son decorativos: Django **rehashea de forma transparente** al
iniciar sesión cuando detecta que el hash usa un algoritmo distinto del primero
de la lista. Si algún día hubiera que migrar desde PBKDF2, ocurriría sin pedirle
a nadie una contraseña nueva.

Decisiones relacionadas que forman parte de esta:

- **Longitud mínima de 12 caracteres**, por encima del 8 por defecto de Django.
  Un hash lento no compensa una contraseña de ocho caracteres.
- **MD5 en el entorno de pruebas**, y solo ahí: derivar Argon2 en cada *fixture*
  haría la suite inviable. Está confinado a `config/settings/testing.py` y hay
  una prueba que lo vigila.
- **Los parámetros de coste** (memoria, iteraciones, paralelismo) se dejan en los
  valores por defecto de `argon2-cffi`, que son razonables. Ajustarlos exige
  medir en el hardware real de producción, y se hará en la Fase 9.

### Verificación de viabilidad

`argon2-cffi 25.1.0` y `argon2-cffi-bindings 26.1.0` instalan sin compilar en
Python 3.14 sobre Windows. Si en alguna plataforma de destino no hubiera ruedas
disponibles, la reversión a PBKDF2 es una línea en los ajustes y **no invalida
las contraseñas existentes** gracias al rehash transparente.

## Consecuencias

### Positivas
- Resistencia muy superior ante un volcado de la base.
- La migración de algoritmo, en cualquier dirección, es transparente.

### Negativas aceptadas
- Una dependencia con extensión compilada: hay que vigilar que existan ruedas
  para la versión de Python de cada entorno.
- Cada inicio de sesión consume más CPU y memoria que con PBKDF2. Es
  intencionado, y a este volumen de usuarios resulta irrelevante.
- Un hasher rápido convive en el repositorio (el de pruebas). Su confinamiento
  depende de que la prueba que lo vigila siga existiendo.

### Qué habría que hacer para revertirla
Colocar PBKDF2 primero en la lista. Los hashes Argon2 existentes seguirían
validando, y se irían rehasheando en cada inicio de sesión.

## Cómo se verifica

| Verificación | Prueba |
|---|---|
| Argon2 es el hasher principal | `tests/test_settings_contract.py::test_argon2_is_the_primary_hasher` |
| `argon2-cffi` está **realmente instalado y cargable** | `...::test_argon2_is_actually_installed` |
| Hay respaldo PBKDF2 para el rehash transparente | `...::test_fallback_hashers_allow_transparent_rehashing` |
| La longitud mínima es 12 | `...::test_minimum_password_length_is_twelve` |
| MD5 no se escapa del entorno de pruebas | `...::test_fast_hasher_is_confined_to_the_test_environment` |
| La contraseña nunca se almacena en claro | `apps/accounts/tests/test_models.py::test_password_is_hashed_never_stored_in_clear` |
