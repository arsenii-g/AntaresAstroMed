# Motor de riesgos: cómo usarlo desde la API

Dueño: Arsenii. Lo usa: Jesus (`api/`).

El motor es una función de Python puro, sin red, sin base de datos y sin dependencias. La API la importa y la llama dentro de su propio proceso. Python 3.11 o más.

```python
from risk import evaluate
```

## Resumen en una tabla

| | Qué | Detalle |
|---|---|---|
| **Le mandas** | `telemetry` | Mensajes ① de telemetría del **último minuto** |
| | `events` | Eventos ① de los **últimos 7 días** |
| | `manual_checks` | Chequeos ② de los **últimos 7 días** |
| | `now` | `datetime.now(timezone.utc)` |
| **Te devuelve** | un `dict` | La evaluación ③, como `contracts/assessment.example.json` |

Todos los textos que devuelve (motivos, recomendaciones, resumen) van **en inglés**, porque el proyecto se presenta en inglés.

Todo de **un solo `crew_id`**, como dicts con el mismo JSON que llegó a la API. No hace falta ordenarlos: el motor ordena por `ts`.

## 1. Qué le mandas

### Cuándo llamarlo

Cada vez que guardes un mensaje de un tripulante con `crew_id`: telemetría (cada 5 s), un evento o un chequeo manual. Si el `crew_id` llega `null` (nadie ha pasado la tarjeta), guarda el mensaje pero no llames al motor.

### Cuánto historial

| Lista | Ventana | Por qué |
|---|---|---|
| `telemetry` | Último minuto (unos 12 mensajes) | El motor descarta la telemetría de más de 60 s: un pulso de hace 10 minutos ya no vale. Mandar más no rompe nada, solo es más lento |
| `events` | Últimos 7 días | Las flexiones se comparan con la media del propio tripulante en 7 días, y salen en la tendencia |
| `manual_checks` | Últimos 7 días | El nivel de hoy usa los chequeos de las últimas 24 h; la tendencia, los de 7 días |

**Importante:** guarda el `ts` que viene en el mensaje, no la hora a la que llegó a la API. La tendencia y la basal de las flexiones se calculan con ese `ts`. El simulador manda historia con fechas pasadas, y la placa reenvía mensajes atrasados cuando se recupera la conexión.

### Ejemplo en un endpoint

```python
from datetime import datetime, timedelta, timezone
from risk import evaluate

now = datetime.now(timezone.utc)
assessment = evaluate(
    telemetry=db.telemetry(crew_id, since=now - timedelta(minutes=1)),
    events=db.events(crew_id, since=now - timedelta(days=7)),
    manual_checks=db.checks(crew_id, since=now - timedelta(days=7)),
    now=now,
)
db.save_assessment(assessment)
await ws.broadcast({"type": "assessment", "data": assessment})
```

`db.telemetry`, `db.events` y `db.checks` son de ejemplo: cómo lees la base de datos es cosa tuya. Cada una devuelve una lista de dicts.

`evaluate()` no lanza excepciones con datos ausentes, incompletos o con basura (textos donde va un número, listas, `null`…): eso cuenta como "no data". Aun así, envuélvelo en un `try` para que un fallo del motor nunca tumbe el endpoint que guarda los datos.

Dos detalles:

- **`now` tiene que llevar zona horaria:** `datetime.now(timezone.utc)`. Con un `datetime.now()` sin zona, el motor lanza `ValueError`. Si lo aceptara, en UTC+1 toda la telemetría parecería de hace una hora y saldría todo "no data".
- **Duplicados:** el motor cuenta una sola vez los mensajes con el mismo `(device_id, ts, type)`, que es lo que la placa repite en los reintentos. Aun así, conviene no guardarlos dos veces.

## 2. Qué te devuelve

```json
{
  "crew_id": "F3786E09",
  "ts": "2026-11-14T10:30:05Z",
  "overall_level": 1,
  "systems": {
    "cardiovascular": { "level": 1, "reasons": ["Heart rate 118 bpm, above 100 bpm"] },
    "neuro": { "level": 0, "reasons": [] },
    "musculoskeletal": { "level": 0, "reasons": [] },
    "environment": { "level": 1, "reasons": ["Cabin humidity 72%, above 60%"] }
  },
  "trends": [
    { "indicator": "pushup_reps", "projected_7d": 14, "crosses_threshold_in_days": 4,
      "threshold": 16.2, "threshold_level": 2, "slope_per_day": -0.6 }
  ],
  "recommendations": ["...", "..."],
  "earth_summary": null
}
```

| Campo | Qué es | Ojo con |
|---|---|---|
| `overall_level` | El peor de los 4 sistemas: 0 verde, 1 ámbar, 2 naranja, 3 rojo | **Puede ser `null`** si no hay ningún dato |
| `systems.*.level` | Nivel de cada sistema | **Puede ser `null`**: la web lo pinta gris, "no data", nunca verde |
| `systems.*.reasons` | Motivos **en inglés**, primero los más graves y luego los "no data" | |
| `trends` | Proyección a 7 días de `systolic_mmhg`, `diastolic_mmhg`, `glucose_mg_dl`, `mood` y `pushup_reps` | Solo aparecen los que tienen al menos 3 medidas en al menos 1 día |
| `trends[].crosses_threshold_in_days` | Días hasta cruzar el siguiente umbral | `null` si no lo cruza en 7 días |
| `recommendations` | **En inglés**: primero la acción del nivel, luego las contramedidas y los avisos de tendencia | |
| `earth_summary` | Texto en inglés listo para mandar a los médicos en Tierra | Solo en nivel 3; si no, `null` |

Los cuatro sistemas se reparten así en la web: `cardiovascular`, `neuro` y `musculoskeletal` van en el muñeco del tripulante; `environment`, en la cabina.

## 3. Reglas que evitan falsas alarmas

Además de los umbrales de `thresholds.json`, el motor aplica estas reglas. No cambian el contrato ③: solo deciden el nivel y añaden una nota al final del motivo, en inglés. Todas son **criterio propio** y se ajustan en `thresholds.json` (`rules_source` explica cada una).

| Regla | Qué hace | Por qué | Ajuste |
|---|---|---|---|
| **Pulso y temperatura sostenidos** | Naranja o rojo solo si las **3 últimas lecturas** (15 s) están en ese nivel o peor. Mientras no, cualquier lectura alta da **ámbar, nunca verde**: `(not sustained yet: 1 of 3 readings)`. Lecturas altas y bajas mezcladas dan ámbar con `(inconsistent readings; check the sensor)` | La fotorresistencia es ruidosa y el termistor se puede soltar: un pico suelto no debe llamar a Tierra, pero un fallo del sensor tampoco debe esconder un problema real | `sustain_readings` en `heart_rate_bpm` y `body_temp_c` |
| **Pulso tras ejercicio** | Si el último mensaje dice `activity: "moving"`, o hubo una serie de flexiones en los últimos 5 min, el pulso alto en **naranja** baja a ámbar: `(after exercise; recheck at rest)`. El rojo (más de 150 lpm) y el pulso bajo no se rebajan | Subir el pulso con el esfuerzo es normal, pero más de 150 ya no se explica por unas flexiones | `heart_rate_bpm.exercise_recovery_s` |
| **Tensión entre días** | El naranja necesita dos medidas seguidas en naranja o peor. La última tiene que ser de las últimas 24 h; la anterior puede ser de cualquiera de los 7 días | La guía dice "140/90 en dos medidas", y en la misión se mide una vez al día. Antes, la medida de ayer (a 25 h) no contaba | Ventana de 7 días |
| **Ánimo frente a su media** | Ámbar si el ánimo de hoy está **1,5 puntos o más** por debajo de la media del propio tripulante en los 7 días anteriores, con al menos 3 chequeos previos. Se suma al corte fijo (menos de 3) | Un 3/5 es normal para alguien que suele estar en 3, pero es una bajada clara para alguien que siempre está en 5 | `mood.personal_drop`, `mood.personal_min_checks` |

Consecuencia para la demo: el segundo tripulante sale en ámbar a los 100 s y en **rojo a los 110 s**, cuando ya hay 3 lecturas de 156 lpm.

## 4. Modo demo

Arranca la API con la variable de entorno `SPACEHEALTH_DEMO=1`. Así el ámbar por inactividad salta a los 30 s en vez de a los 600 s, igual que el evento `inactivity` de la placa en la demo.

```bash
SPACEHEALTH_DEMO=1 uvicorn api.main:app --reload
```

(El comando de `uvicorn` es un ejemplo; usa el tuyo.)

## 5. Cómo probar la tendencia de 7 días

La tendencia es una regresión lineal sobre los últimos 7 días del propio tripulante, proyectada 7 días hacia delante. Avisa si la recta cruza el siguiente umbral aunque hoy esté en verde. Hay tres formas de probarla, de menos a más integración.

### a) Tests del motor, sin nada más

```bash
.venv/bin/pytest -q risk/tests/test_trends.py
```

Comprueban, entre otras cosas, que una glucosa que sube 3 mg/dl al día avisa antes de salir de verde, que valores estables no avisan, y que con menos de 3 medidas no hay tendencia.

### b) Simulador contra el motor en local, sin API

`--history-days 7` genera antes una semana de chequeos (08:00) y series de flexiones (18:00). Con `healthy` son estables; con `worsening` y `demo`, la tensión, la glucosa y el ánimo empeoran y las flexiones caen.

```bash
.venv/bin/python -m simulator.simulate --scenario healthy --fast --evaluate --count 1 --history-days 7
.venv/bin/python -m simulator.simulate --scenario worsening --fast --evaluate --count 1 --history-days 7
```

El primero no da ninguna tendencia; el segundo, algo así:

```
t=   0s  F3786E09 hr=75 temp=36.8 ... → overall=1 cardio=0 neuro=— muscle=1 cabin=0
        recommends: Review the strength training plan
        trend: systolic_mmhg crosses 140 in 5.7 days
        trend: pushup_reps crosses 14.8 in 0.8 days
```

Sin `--evaluate` imprime los JSON que mandaría, para verlos o guardarlos en un archivo:

```bash
.venv/bin/python -m simulator.simulate --scenario worsening --fast --count 1 --history-days 7 > historia.jsonl
```

### c) Simulador contra tu API

```bash
python -m simulator.simulate --scenario worsening --history-days 7 \
    --url http://localhost:8000 --api-key demo
```

Primero manda la historia: los chequeos a `POST /api/v1/checks` y las flexiones a `POST /api/v1/events`, con fechas de los 7 días anteriores. Después manda telemetría cada 5 s a `POST /api/v1/telemetry`. Si tu API guarda el `ts` del mensaje y pasa 7 días al motor, la evaluación que emitas tendrá `trends` con `crosses_threshold_in_days` en tensión y flexiones. Si `trends` sale vacío, lo más probable es que estés guardando la hora de llegada en vez del `ts`, o pasando menos de 7 días.

El escenario `demo` hace lo mismo y además recorre el guion de 2 minutos: ámbar por inactividad, flexiones, vuelta a verde y un segundo tripulante en rojo con `earth_summary` (a los 110 s; ver sección 3).

## 6. Respuestas de la API al simulador y a la placa

El simulador reacciona igual que el ESP32 (detalle en `contracts/README.md`):

| Respondes | Qué hace |
|---|---|
| 2xx | Lo da por enviado |
| 409 | Lo toma como duplicado ya guardado |
| Otro 4xx (400, 401, 422…) | **Descarta el mensaje**: ese dato se pierde |
| 5xx o sin respuesta | Reintenta a 1, 2, 4… s, hasta 30 s |

Por eso, nunca respondas 422 a un campo `null`: los `null` son normales (sensor sin contacto, DHT11 fallando, respiración que no se mide).

## Archivos

| Archivo | Qué hace |
|---|---|
| `engine.py` | `evaluate()`: junta todo |
| `indicators.py` | Nivel 0–3 de cada medida y modo demo |
| `thresholds.json` | Umbrales y reglas extra; cada corte cita su fuente |
| `trends.py` | Regresión de 7 días |
| `recommendations.py` | Contramedidas y avisos de tendencia |
| `summary.py` | Resumen en inglés para Tierra |
| `tests/` | `pytest -q` desde la raíz del repo |
