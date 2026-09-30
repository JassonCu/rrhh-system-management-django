# ADR-001 — Monolito modular en lugar de microservicios

- **Estado:** Aceptado
- **Fecha:** 2026-09-11
- **Decide:** Equipo técnico
- **Fase:** 1

---

## Contexto

Sistema de RRHH para una organización, con un equipo de desarrollo pequeño, sin
volumen de tráfico conocido y sin entorno de producción todavía.

El dominio está fuertemente acoplado **por los datos**: una alta de contrato
toca `EmploymentContract`, `ContractSalary`, `Assignment`, `Employee` y
`AuditEvent` en una sola operación que debe ser atómica. Una corrida de nómina
lee contratos, asistencia y ausencias y produce recibos inmutables.

## Alternativas consideradas

### A. Monolito "clásico" sin fronteras internas
Una app Django grande, o varias que se importan libremente entre sí.

- **A favor:** máxima velocidad inicial; cero ceremonia.
- **En contra:** en doce meses cualquier cambio toca todo. Sin fronteras no hay
  forma de razonar sobre el impacto de una modificación, y la extracción
  posterior de un módulo se vuelve un proyecto en sí misma.
- **Costo de revertir:** alto (hay que descubrir las fronteras a posteriori).

### B. Monolito modular *(elegida)*
Un despliegue y un esquema, con apps Django por contexto de dominio e interfaz
pública explícita entre ellas.

- **A favor:** transacciones ACID entre dominios sin coordinación distribuida;
  un solo despliegue que operar; fronteras que permiten extraer un módulo el día
  que haga falta.
- **En contra:** exige disciplina que ninguna herramienta impone por defecto.
- **Costo de revertir:** bajo en ambas direcciones.

### C. Microservicios
Un servicio por contexto, con comunicación por API o mensajes.

- **En contra:** la atomicidad de «crear contrato + salario + asignación +
  auditoría» pasaría a ser una saga con compensaciones. Se pagaría complejidad
  distribuida —descubrimiento, reintentos, consistencia eventual, trazabilidad—
  sin ningún problema de escala que la justifique. La regla 56 del encargo lo
  prohíbe explícitamente sin justificación.

### D. Monolito con API REST desde el inicio
Django + DRF, con la interfaz web consumiéndola.

- **En contra:** duplica la superficie de autorización (hay que proteger las
  vistas **y** los endpoints) sin ningún consumidor que lo pida. Se añade cuando
  exista una aplicación móvil o una integración real.

## Decisión

Se adopta **B**. Las reglas concretas:

1. Una app Django por contexto delimitado (`core`, `accounts`, `employees`,
   `departments`, `positions`, `contracts`, `attendance`, `leave`, `documents`,
   `payroll`, `audit`).
2. `core` no importa ninguna otra app; cualquiera puede importar `core`.
3. Entre apps de dominio solo se consume la **interfaz pública**:
   `services`, `selectors`, `constants` y `exceptions`. `models`, `forms`,
   `views` y `admin` son privados.
4. Las claves foráneas entre apps se declaran por cadena
   (`"employees.Employee"`), nunca importando la clase: el acoplamiento vive en
   el esquema, no en el código.
5. `audit` no depende de ningún dominio: recibe cadenas y diccionarios.

## Consecuencias

### Positivas
- Una transacción cubre varios dominios sin coordinación distribuida.
- El impacto de un cambio es acotable leyendo la interfaz pública de una app.
- Extraer un módulo más adelante es un trabajo delimitado, no una arqueología.

### Negativas aceptadas
- Un fallo derriba todo el sistema: no hay aislamiento entre contextos.
- El escalado es vertical o por réplicas del monolito completo.
- La disciplina de fronteras depende de que la verificación exista y se respete.

### Qué habría que hacer para revertirla
Extraer un contexto exige: separar su esquema, sustituir las FK que lo cruzan
por identificadores, y convertir las llamadas a su interfaz pública en llamadas
remotas. Las reglas 3 y 4 existen precisamente para que ese trabajo sea acotado.

## Cómo se verifica

`tests/test_app_boundaries.py` analiza con `ast` **todos** los módulos de
`apps/` y falla si:

- `core` importa otra app,
- `audit` importa una app de dominio,
- alguna app importa un módulo privado de otra.

Incluye una prueba que comprueba que el analizador detecta de verdad (para que
no pase en vacío) y otra que verifica que hay módulos que analizar.
