# txnexplorer — Refactorización y personalización agéntica mediante Skills propias

Proyecto base: **Normalización y Exploración de Transacciones Multifuente**
Esta entrega lo refactoriza para separar **lógica, configuración y comportamiento del agente**, y agrega
**skills propias** integradas en **dos agentes personalizados**.

## 1. Diagnóstico del proyecto original (responsabilidades acopladas)

| # | Problema en el original | Dónde | Solución |
|---|---|---|---|
| 1 | `_context()` mezclaba HTTP, rutas, carga, pipeline, escritura del log de auditoría y métricas | `app.py` | `services.process_dataset()` (un único orquestador reutilizable) |
| 2 | Rutas (`data/`, `config/rules.json`, `logs/`) fijas dentro de la app web | `app.py` | `config.Settings` |
| 3 | Las capacidades (filtrar, métricas, explicar rechazos) solo se podían usar vía Flask y `request.args` | `app.py` | `skills/` (invocables desde web, CLI, agentes y tests) |
| 4 | La serialización de métricas (Decimal→float) vivía dentro de una ruta y mutaba el dict | `app.py` | `metrics.metrics_to_jsonable()` (sin mutar) |
| 5 | No existía capa de comportamiento: nada definía *quién* responde, con qué permisos ni cómo | — | `config/agents.json` + `agents/` |

El núcleo (`normalizer`, `validator`, `pipeline`, `rules`, `filters`, `models`) **no se modificó**: la refactorización
se apoya en él. Las 7 pruebas originales siguen pasando sin cambios.

## 2. Arquitectura

```
                 config/rules.json   config/skills.json   config/agents.json      <- CONFIGURACION
                        |                   |                     |
 app.py (HTTP) ---+     |                   |                     |
 agent_cli.py ----+--> agents/ (Agent + Planner + Profile)  <------+                <- COMPORTAMIENTO
                        |  usa solo los skills permitidos por su perfil
                        v
                  skills/ (Skill, Registry, builtin)                                 <- CAPACIDADES
                        |
                        v
        services.py -> loader -> normalizer -> validator -> pipeline -> metrics      <- LOGICA
```

### Skills propias (`txnexplorer/skills/builtin.py`)

| Skill | Responsabilidad |
|---|---|
| `list_datasets` | Lista los JSON disponibles |
| `ingest_dataset` | Ejecuta el pipeline completo sobre un dataset |
| `query_transactions` | Filtra/ordena transacciones válidas (estado, moneda, fuente, monto, fechas…) |
| `metrics_summary` | Totales por estado, moneda y fuente |
| `explain_invalid` | Agrupa la cuarentena por motivo + ejemplos + recomendación (de `skills.json`) |
| `audit_trail` | Ajustes de redondeo con monto original y ajustado |
| `quality_report` | Veredicto BUENA / ACEPTABLE / CRITICA según umbrales configurables |

Cada skill declara `name`, `description`, `params` y `requires_data`; se ejecuta con `execute()`, que valida
parámetros y prerrequisitos y **nunca lanza excepciones** (devuelve `SkillResult`).

### Agentes personalizados (`config/agents.json`)

| Agente | Rol | Skills permitidos |
|---|---|---|
| `auditor` | Evalúa calidad, explica rechazos, muestra ajustes | `list_datasets, ingest_dataset, quality_report, explain_invalid, audit_trail, metrics_summary` |
| `analyst` | Consulta transacciones y totales | `list_datasets, ingest_dataset, query_transactions, metrics_summary` |

La personalización (rol, `system_prompt`, skills permitidos, *intents* con palabras clave, valores por defecto como
`limit`, mensaje de *fallback*) está **en JSON**, validada al cargar (un skill inexistente o fuera de la lista blanca
falla al arrancar). El agente **inserta solo `ingest_dataset`** cuando hace falta y **rechaza** skills fuera de su perfil.

### Planificadores

- `RuleBasedPlanner` (por defecto): determinista, sin red. Elige el intent por palabras clave y extrae parámetros del
  texto (dataset, estado, moneda, fuente, código de error, "mayor a N", "menor a N").
- `LLMPlanner` (opcional, `--llm`): un LLM *propone* el plan en JSON; el código **valida** skill permitido y parámetros
  declarados, y ante cualquier fallo (red, JSON roto, skill no permitido) **cae al planificador de reglas**.
  Solo usa la librería estándar (`urllib`). Variables: `TXN_LLM_BASE_URL`, `TXN_LLM_API_KEY`, `TXN_LLM_MODEL`
  (cualquier endpoint compatible con `/chat/completions`).

## 3. Uso

```bash
pip install flask                      # solo para la interfaz web; agentes/CLI/tests usan solo la libreria estandar

python agent_cli.py --list
python agent_cli.py -a auditor "dame un reporte de calidad" -d transactions_mixed.json
python agent_cli.py -a auditor "por que se rechazaron registros?" -d transactions_mixed.json
python agent_cli.py -a analyst "muestra las transacciones fallidas en USD mayores a 100" -d transactions_valid.json
python agent_cli.py -a analyst         # modo interactivo

python app.py                          # http://127.0.0.1:5000
#   /api/agents
#   /api/agent?agent=auditor&q=reporte de calidad&dataset=transactions_mixed.json

python -m unittest discover tests -v   # 23 pruebas
```

## 4. Cómo extender

**Nuevo skill:** crear una clase `Skill` (nombre, parámetros, `run`) y registrarla en `BUILTIN_SKILLS`, o ponerla en un
módulo propio con `SKILLS = [MiSkill]` y listarlo en `config/skills.json -> extra_skill_modules`.

**Nuevo agente:** agregar una entrada en `config/agents.json` (skills + intents). No requiere cambios de código.

**Cambiar comportamiento:** umbrales de calidad, textos de remediación y límite de filas → `config/skills.json`;
reglas de negocio → `config/rules.json`.

## 5. Decisiones y limitaciones

- El `LLMPlanner` está probado con un proveedor simulado (`FakeLLM`), **no contra un
  servicio real**.
- El extractor de parámetros toma **un valor por tipo** (p. ej. solo la primera moneda si se mencionan varias).
- Los keywords/intents son simples; frases muy ambiguas caen en el mensaje de *fallback*.
- Los logs de auditoría (`logs/`) se generan al procesar, igual que en el original.

## 6. Uso de IA de apoyo y trazabilidad (proyecto base y esta refactorización)

### 6.1 Proyecto base
Fue desarrollado con **Claude y Copilot** como herramientas de apoyo (ver la nota técnica de esa semana). La IA ayudó a
estructurar el código, proponer formas de procesar los datos, interpretar los formatos de montos (separadores
decimales y de miles, unidades menores) y construir la interfaz Flask. Las decisiones de diseño fueron del estudiante y
quedaron en `config/rules.json`: esquema final, reglas de normalización y criterios de validez.

Cambios hechos por el estudiante a las propuestas iniciales de la IA:

| Propuesta inicial de la IA | Decisión final del estudiante | Por qué |
|---|---|---|
| Invalidar todo monto con más decimales de los permitidos | Redondear (ROUND_HALF_UP) si el exceso es <= 3 decimales; conservar `original_amount`, marcar y auditar | No perder transacciones recuperables, manteniendo trazabilidad |
| 4 monedas (USD, EUR, GBP, MXN) | 42 monedas, cada una con sus decimales (JPY=0, KWD=3, CLF=4) | Obligó a adaptar unidades menores y redondeo |
| `REQUIERE_REVISION` como estado | `REQUIERE_REVISION` como **flag** | Mantener los estados SUCCESS / FAILED / PENDING sin categorías extra |

Se mantuvieron: invalidar montos <= 0, rechazar estados desconocidos, enviar duplicados a cuarentena y usar UTC.
Validación: 7 pruebas en `tests/` y dos archivos de datos (uno limpio y uno con inconsistencias).

### 6.2 Esta actividad (refactorización agéntica)
Se usó **Copilot y claude** como asistentes para proponer la arquitectura (servicio, skills, agentes) y generar el código.
Aporte y verificación del estudiante: el diagnóstico se hizo sobre su propio proyecto, el núcleo del pipeline no se
modificó, y todo se validó ejecutando las pruebas originales (7) más las nuevas (16): 23/23 en verde.
El sistema **no requiere proveedor de LLM**; el planificador LLM es opcional y se probó con un proveedor simulado.

