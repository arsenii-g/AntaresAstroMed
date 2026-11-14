# AstroMed · Antares · NASA Space Apps 2026

Web que guía al astronauta en su chequeo diario, evalúa su riesgo con reglas explicables y verifica con sensores reales lo que hace.

Reto: *Create Health Monitoring Software for Astronauts on Space Missions*.

## Arrancar API y web juntas

Python 3.11 o posterior. Desde la raíz del repositorio:

```bash
python -m venv .venv
```

Activar el entorno en macOS/Linux: `source .venv/bin/activate`.
En PowerShell de Windows: `.\.venv\Scripts\Activate.ps1`.

```bash
python -m pip install -r requirements.txt
python -m uvicorn api.main:app --env-file .env.example --host 0.0.0.0 --port 8000
```

Abrir <http://localhost:8000> (portada) o <http://localhost:8000/console.html>
(consola de Roberto, commit `06d933e`, conectada al backend real). La API sirve también
los archivos de la web: no hace falta un segundo servidor ni compilar el frontend.
Desde otro equipo de la misma red, sustituir `localhost` por la IP del portátil.

`.env.example` activa `SPACEHEALTH_DEMO=1`: inactividad a 30 s, igual que la placa.
Se pueden copiar sus valores a `.env` y arrancar con `--env-file .env` para personalizarlos.
El ESP32 usa la misma API key y la dirección del portátil en `API_BASE`; los GET y el
chequeo manual de la web no necesitan clave.

En otra terminal, con el entorno activado, se pueden sustituir las placas por el
simulador: dos ESP32, uno por tripulante, con el nivel de cada uno en
`simulator/config.json` (detalles en [`simulator/README.md`](simulator/README.md)):

```bash
python -m simulator.simulate
python -m simulator.simulate --level F3786E09=1 --level 336F8312=3
python -m simulator.simulate --mode normal
```

La consola sigue la tarjeta activa, permite seleccionar otro tripulante, muestra los
datos en vivo, los motivos y las acciones del motor, las rectas de tendencia que
calcula el motor con sus puntos medidos, y un chequeo guiado en tres pasos. El resumen para Tierra se prepara y
se copia; no se envía automáticamente a ningún servicio externo.

La placa y el simulador mandan telemetría cada 2 s. Guarda el `ts`
original en UTC, deduplica los reintentos y llama al motor dentro del mismo proceso.
Los detalles y los endpoints están en [`api/README.md`](api/README.md).

## Comprobar el proyecto

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Las pruebas del frontend usan Node 20 o posterior, sin instalar paquetes:

```bash
node --test frontend/boceto/tests/*.test.js
```

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
| `hardware/` | PCB: esquemático, diseño y archivos de fabricación | Por confirmar |
| `risk/` | Motor de riesgos y `thresholds.json` | Arsenii |
| `simulator/` | Dos ESP32 simulados para el vídeo, con nivel configurable | Arsenii |
| `api/` | FastAPI: endpoints, base de datos, WebSocket | Jesus |
| `frontend/boceto/` | Consola AstroMed conectada, cuerpo clicable, chequeo guiado y gráficas | Roberto |

## Contratos

| # | Flujo | Endpoint | Dueño |
|---|---|---|---|
| ① | Telemetría y eventos, ESP32 → API | `POST /api/v1/telemetry`, `POST /api/v1/events` | Electrónico |
| ② | Chequeo manual, frontend → API | `POST /api/v1/checks` | Roberto |
| ③ | Evaluación de riesgo, motor → API | `evaluate(...)` | Arsenii |
| ④ | API → frontend | `GET /api/v1/crew/{crew_id}/latest`, WebSocket | Jesus |

Fechas en UTC (ISO 8601). Lo que no se mide va como `null`, que significa "sin dato", nunca "normal".

La API llama al motor así, dentro del mismo proceso:

```python
from risk import evaluate

evaluate(telemetry: list[dict], events: list[dict],
         manual_checks: list[dict], now: datetime) -> dict
```

Las listas llevan mensajes ① y ② de un solo `crew_id`, y `now` va en UTC. Devuelve la evaluación ③ (`contracts/assessment.example.json`). El motor no recibe perfil: le basta el `crew_id` que va en cada mensaje. El nombre y el rol los añade la API o el frontend.

**Para la API:** qué mandar al motor (telemetría del último minuto; eventos y chequeos de los últimos 7 días), qué devuelve y cómo funcionan las rectas de tendencia, en [`risk/README.md`](risk/README.md).

## Ramas

- Los cambios se proponen por PR para que otra persona los revise antes de entrar en `main`.
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

Fuera de alcance: no hay modo sueño ni medida de respiración (ni el modo descanso del HC-SR04, que ahora solo cuenta flexiones). Los cuatro sistemas del motor son cardiovascular, neuro, músculo-esquelético y entorno de cabina.

Es una demo con sensores de un kit educativo: ninguna medida es de grado médico y los umbrales son de demo, a contrastar con NASA HRP.
