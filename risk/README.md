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

Cada vez que guardes un mensaje de un tripulante con `crew_id`: telemetría (cada 2 s en la placa actual), un evento o un chequeo manual. Si el `crew_id` llega `null` (nadie ha pasado la tarjeta), guarda el mensaje pero no llames al motor.

### Cuánto historial

| Lista | Ventana | Por qué |
|---|---|---|
| `telemetry` | Último minuto (unos 30 mensajes de la placa actual) | El motor descarta la telemetría de más de 60 s: un pulso de hace 10 minutos ya no vale. Mandar más no rompe nada, solo es más lento |
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
    { "indicator": "glucose_mg_dl", "label": "Glucose", "unit": "mg/dL",
      "basis": "count", "x_unit": "check",
      "points": [[-6, 80], [-5, 83], [-4, 86], [-3, 89], [-2, 92], [-1, 95], [0, 98]],
      "slope": 3.0, "intercept": 98.0, "horizon": 7, "projected": 119.0,
      "threshold": 99, "threshold_level": 1, "crosses_in": 0.3 }
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
| `trends` | Una recta por indicador: chequeo, flexiones y sensor (sección 5) | Solo aparecen los que tienen **al menos 7 medidas** |
| `trends[].crosses_in` | Medidas (`basis: "count"`) o segundos (`"time"`) hasta cruzar el siguiente umbral | `null` si no lo cruza dentro del horizonte |
| `recommendations` | **En inglés**: primero la acción del nivel, luego las contramedidas y los avisos de tendencia | |
| `earth_summary` | Texto en inglés listo para mandar a los médicos en Tierra | Solo en nivel 3; si no, `null` |

Los cuatro sistemas se reparten así en la web: `cardiovascular`, `neuro` y `musculoskeletal` van en el muñeco del tripulante; `environment`, en la cabina.

## 3. Reglas que evitan falsas alarmas

Además de los umbrales de `thresholds.json`, el motor aplica estas reglas. No cambian el contrato ③: solo deciden el nivel y añaden una nota al final del motivo, en inglés. Todas son **criterio propio** y se ajustan en `thresholds.json` (`rules_source` explica cada una).

| Regla | Qué hace | Por qué | Ajuste |
|---|---|---|---|
| **Pulso y temperatura sostenidos** | Naranja o rojo solo si **al menos 3 lecturas consecutivas durante 10 s** están en ese nivel o peor. Mientras no, cualquier lectura alta da **ámbar, nunca verde**: `(not sustained yet: 1 of 3 readings)`. Lecturas altas y bajas mezcladas dan ámbar con `(inconsistent readings; check the sensor)` | La fotorresistencia es ruidosa y el termistor se puede soltar. El pulso usa ventanas de 10 s que se solapan. La placa actual manda cada 2 s: necesita al menos 6 lecturas para cubrir 10 s entre la primera y la última. El simulador manda cada 5 s y necesita 3: un pico suelto no debe llamar a Tierra, pero un fallo del sensor tampoco debe esconder un problema real | `sustain_readings` y `sustain_seconds` en `heart_rate_bpm` y `body_temp_c` |
| **Pulso tras ejercicio** | Si el último mensaje dice `activity: "moving"`, o hubo una serie de flexiones en los últimos 5 min, el pulso alto en **naranja** baja a ámbar: `(after exercise; recheck at rest)`. El rojo (más de 150 lpm) y el pulso bajo no se rebajan | Subir el pulso con el esfuerzo es normal, pero más de 150 ya no se explica por unas flexiones | `heart_rate_bpm.exercise_recovery_s` |
| **Temperatura de muñeca** | La temperatura **baja** da como mucho ámbar: `(wrist reading; confirm with a thermometer)`. La alta (fiebre) mantiene naranja y rojo | El termistor va en la muñeca, y la piel se enfría varios grados con el ambiente aunque el tripulante esté bien (white paper de Polar, citado en `thresholds.json`). Una muñeca fría pide un termómetro, no llamar a Tierra | `body_temp_c.low_max_level` |
| **Serie del tripulante anterior** | Se ignora una serie de flexiones que llega hasta 3 s después de un `crew_checkin` `in` | Si se pasa una tarjeta con una serie a medias, la placa manda el resumen con el `crew_id` del que entra, pero las flexiones son del anterior y le bajarían la basal | Fijo, 3 s |
| **Tensión entre días** | El naranja necesita dos medidas seguidas en naranja o peor. La última tiene que ser de las últimas 24 h; la anterior puede ser de cualquiera de los 7 días | La guía dice "140/90 en dos medidas", y en la misión se mide una vez al día. Antes, la medida de ayer (a 25 h) no contaba | Ventana de 7 días |
| **Ánimo frente a su media** | Ámbar si el ánimo de hoy está **1,5 puntos o más** por debajo de la media del propio tripulante en los 7 días anteriores, con al menos 3 chequeos previos. Se suma al corte fijo (menos de 3) | Un 3/5 es normal para alguien que suele estar en 3, pero es una bajada clara para alguien que siempre está en 5 | `mood.personal_drop`, `mood.personal_min_checks` |

Consecuencia para la demo: el segundo tripulante sale en ámbar a los 100 s y en **rojo a los 110 s**, cuando ya hay 3 lecturas de 156 lpm.

## 4. Modo demo

Arranca la API con la variable de entorno `SPACEHEALTH_DEMO=1`. Así el ámbar por inactividad salta a los 30 s en vez de a los 600 s, igual que el evento `inactivity` de la placa.

**Ojo:** el firmware está ahora en modo demo (`INACTIVITY_THRESHOLD_S 30` en `firmware/uno_sensores/config.h`). Con la placa real, arranca la API con `SPACEHEALTH_DEMO=1`; si no, la placa avisará de inactividad a los 30 s y el motor no la pintará en ámbar hasta los 600 s. Para uso real, los dos a 600 s.

```bash
SPACEHEALTH_DEMO=1 uvicorn api.main:app --reload
```

(El comando de `uvicorn` es un ejemplo; usa el tuyo.)

## 5. Rectas de tendencia

Cada tendencia es una recta de mínimos cuadrados sobre las medidas reales del propio tripulante, proyectada hacia delante. Avisa si la recta cruza el siguiente umbral aunque hoy esté en verde. La recta y los puntos van en la evaluación, así que la web los dibuja tal cual, sin recalcular nada.

| Datos | Eje x (`basis`) | Ventana | Proyección (`horizon`) |
|---|---|---|---|
| Chequeo manual: tensión, glucosa, ánimo | Por chequeo (`count`, `check`): el último es 0, el anterior −1… | Últimos 7 días | 7 chequeos más |
| Flexiones (`exercise_summary`) | Por serie (`count`, `set`) | Últimos 7 días | 7 series más |
| Sensor: pulso, temperatura corporal, cabina, humedad | Segundos respecto a ahora (`time`, `s`) | Último minuto (unas 30 lecturas) | 60 s |

Criterio propio:

- **Hacen falta 7 medidas.** Con el séptimo chequeo aparece la recta; con 7 lecturas del sensor (14 s), la del sensor.
- **Chequeos y series van por medida, no por día.** En uso real se hace un chequeo al día, así que 7 chequeos son una semana. En la demo se pueden meter 7 chequeos en unos minutos y la recta sale igual de bien; por días, todos caerían en el mismo día y la pendiente se dispararía.
- **Solo se vigila el umbral hacia el que empeora.** Si el valor está en una franja alta y la recta baja (o en una baja y sube), se está recuperando: `threshold` es `null`.
- **Temperatura corporal baja:** solo se vigila el ámbar, porque el motor no la sube de ámbar (sección 3).
- **Flexiones:** el umbral en repeticiones es la basal (media de las series anteriores a la última) menos el porcentaje de caída de cada nivel.

### Probarlas

```bash
python -m pytest -q risk/tests/test_trends.py
python -m simulator.simulate --mode normal --evaluate --fast --count 150
```

Las pruebas comprueban, entre otras cosas, que 7 chequeos seguidos dan la misma recta que 7 chequeos en 7 días, que con 6 medidas no hay recta y que un pulso que sube 1 lpm/s avisa de que cruzará 120 lpm en 12 s. El modo `normal` del simulador hace subir y bajar los niveles en rampa, y las rectas del sensor lo detectan. Ver [`simulator/README.md`](../simulator/README.md).

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
| `trends.py` | Rectas de tendencia (sección 5) |
| `recommendations.py` | Contramedidas y avisos de tendencia |
| `summary.py` | Resumen en inglés para Tierra |
| `tests/` | `pytest -q` desde la raíz del repo |
