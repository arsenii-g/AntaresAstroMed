# SpaceHealth · NASA Space Apps 2026

Web que guía al astronauta en su chequeo diario, evalúa su riesgo con reglas explicables y verifica con sensores reales lo que hace.

Reto: *Create Health Monitoring Software for Astronauts on Space Missions*.

## Cómo funciona

```
Sensores → Arduino UNO ──serie──▶ ESP32 ──WiFi, HTTP POST──▶ FastAPI ──evaluate()──▶ motor de riesgos
                                                                │
Frontend (chequeo manual) ──POST /api/v1/checks─────────────────┤
Frontend (dashboard)      ◀──GET + WebSocket────────────────────┘
```

El motor de riesgos es un paquete de Python que la API importa y llama en el mismo proceso. No usa ML: compara cada medida con `risk/thresholds.json` y da un nivel de 0 (verde) a 3 (rojo).

## Estructura

| Carpeta | Contenido | Responsable |
|---|---|---|
| `contracts/` | Los 4 contratos JSON: ejemplos y modelos Pydantic | todos |
| `firmware/` | UNO + ESP32: sensores y envío por WiFi | Electrónico |
| `risk/` | Motor de riesgos y `thresholds.json` | Arsenii |
| `simulator/` | Emite telemetría ① con escenarios | Arsenii |
| `api/` | FastAPI: endpoints, base de datos, WebSocket | Jesus |
| `frontend/` | Cuerpo clicable, chequeo guiado, gráficas | Roberto |

## Contratos

| # | Flujo | Endpoint | Dueño |
|---|---|---|---|
| ① | Telemetría y eventos, ESP32 → API | `POST /api/v1/telemetry`, `POST /api/v1/events` | Electrónico |
| ② | Chequeo manual, frontend → API | `POST /api/v1/checks` | Roberto |
| ③ | Evaluación de riesgo, motor → API | `evaluate(...)` | Arsenii |
| ④ | API → frontend | `GET /api/v1/crew/{crew_id}/latest`, WebSocket | Jesus |

Fechas en UTC (ISO 8601). Lo que no se mide va como `null`, que significa "sin dato", nunca "normal".

## Ramas

- `main` está protegida: siempre arranca y solo se entra por PR revisado por otra persona.
- El primer PR es `contracts/init`. Cualquier cambio en `contracts/` lo aprueban el productor y el consumidor.
- Ramas cortas por tarea (uno o dos días como mucho), con prefijo por persona:

| Persona | Prefijo | Primera rama |
|---|---|---|
| Electrónico | `hw/` | `hw/telemetry-wifi` |
| Arsenii | `risk/` | `risk/indicator-levels`, `risk/simulator` |
| Jesus | `api/` | `api/post-endpoints` |
| Roberto | `web/` | `web/body-svg` |

- Rebase sobre `main` cada mañana. Quien se bloquee más de 30 minutos, avisa.

```bash
git fetch origin
git switch risk/indicator-levels     # o tu rama
git rebase origin/main
```

## Límites

Es una demo con sensores de un kit educativo: ninguna medida es de grado médico y los umbrales son de demo, a contrastar con NASA HRP.
