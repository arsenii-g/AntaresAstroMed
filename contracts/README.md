# Contratos

Ejemplos JSON de lo que se manda entre las partes. Todas las fechas van en UTC (ISO 8601). Cambiar un contrato necesita un PR que aprueben quien produce el dato y quien lo usa.

Fuente de este documento: guía del equipo y «SpaceHealth: formato JSON para el backend» del electrónico (14 de noviembre de 2026, versión definitiva sacada del firmware). Si algo no cuadra, manda el firmware.

| Archivo | Contrato | Endpoint |
|---|---|---|
| `telemetry.example.json` | ① Telemetría normal | `POST /api/v1/telemetry`, cada 5 s |
| `telemetry-no-data.example.json` | ① Telemetría sin tripulante y con el DHT11 fallando | igual |
| `event.example.json` | ① Evento `exercise_summary` | `POST /api/v1/events`, al ocurrir |
| `event-crew_checkin.example.json` | ① Evento `crew_checkin` | igual |
| `event-inactivity.example.json` | ① Evento `inactivity` | igual |
| `check.example.json` | ② Chequeo manual | `POST /api/v1/checks` |
| `assessment.example.json` | ③ Evaluación de riesgo | lo devuelve `evaluate()` |
| `ws-message.example.json` | ④ Sobre del WebSocket | WebSocket |

## Telemetría ①: qué puede llegar como `null`

| Campo | Cuándo llega `null` |
|---|---|
| `crew_id` | Nadie ha pasado la tarjeta |
| `vitals.resp_rate_bpm` | **Siempre.** No se mide la respiración, pero el campo se mantiene |
| `vitals.heart_rate_bpm` | Cuando `hr_quality` es menor de 0,4 |
| `vitals.body_temp_c` | Termistor sin contacto con la piel, o lectura fuera de 30–45 °C |
| `cabin.*` (los cinco, también `condensation_risk`) | El DHT11 falla 5 veces seguidas |

Además:

- `hr_quality` es **siempre un número**, 0 cuando no hay señal.
- `humidity_pct` es un **entero**: el DHT11 no da decimales.
- No existe `motion.sleep_state`.
- `body_temp_c` ya llega `null` fuera de 30–45 °C, así que la API no debería tener que rechazarlo con un 422.

- Un número con `.0` puede llegar como entero (`23` en vez de `23.0`), por cómo serializa ArduinoJson. Hay que leer los campos numéricos como número, sean enteros o decimales.
- `heart_rate_bpm`, cuando tiene valor, está entre 35 y 200.
- `motion.still_for_s` es 0 con `activity: "moving"` y 3 o más con `"still"`.

Alertas locales posibles en `alerts`, siempre en este orden y sin repetir: `HR_HIGH`, `HR_LOW`, `BODY_TEMP_HIGH`, `BODY_TEMP_LOW`, `CABIN_TEMP_HIGH`, `CABIN_TEMP_LOW`, `HEAT_INDEX_HIGH`, `CONDENSATION_HIGH`. Nunca llegan `RESP_HIGH` ni `RESP_LOW`. Usan los umbrales de demo del firmware (pulso > 120 o < 45, temperatura corporal > 38,0 o < 35,5 °C, cabina > 28 o < 18 °C, índice de calor > 32 °C). Los niveles oficiales los da el motor, no estas alertas.

Tarjetas del kit (el UID es el `crew_id`): `F3786E09` (tripulante 1) y `336F8312` (tripulante 2).

## Eventos ①: solo hay tres tipos

| `type` | `severity` | `data` | Detalles |
|---|---|---|---|
| `crew_checkin` | `info` | `action`: `in` u `out` | Al cambiar de tarjeta llegan dos seguidos: `out` del anterior y `in` del nuevo, este con el `ts` 1 s más tarde para que no cuente como duplicado |
| `inactivity` | `medium` | `still_for_s`, `threshold_s` | Solo con un tripulante fichado, y una vez por periodo sin moverse. `threshold_s` vale 30 en la demo y 600 en uso real |
| `exercise_summary` | `info` | `exercise` (`pushup`), `reps`, `duration_s`, `cadence_rpm` | Puede llegar con `crew_id: null` si nadie ha pasado la tarjeta |

No existen `sleep_summary` ni `reaction_test`.

## Cómo reacciona el ESP32 a las respuestas de la API

| Respuesta | Qué hace el ESP32 |
|---|---|
| 2xx con `{"ok": true}`, sin cuerpo o con un cuerpo que no es JSON | Lo da por enviado |
| 2xx con `{"ok": false}` | Lo trata como fallo y **reintenta sin fin**: bloquea la cola. No lo respondas nunca |
| 409 | Lo toma como duplicado ya guardado y no reintenta. Para duplicados vale 200 o 409 |
| 408 o 429 | Reintenta. Usa 429 si hay que limitar |
| Otro 4xx (400, 401, 404, 422…) | Descarta el mensaje y no reintenta: **ese dato se pierde**. Usa 401 solo para la clave mala y 400 solo para JSON roto |
| 5xx, 3xx o sin respuesta en 4 s | Reintenta a 1, 2, 4… s, hasta 30 s, con hasta 50 mensajes en cola. No sigue redirecciones |

Los mensajes se mandan en orden: mientras el primero falla, los demás esperan. El `ts` no cambia en los reintentos, así que los duplicados se reconocen por `(device_id, ts, type)`, con `type` = telemetría en `/api/v1/telemetry`.

**Hora sin Internet:** si no hay NTP, el ESP32 hace `GET /` al backend y toma la hora de la cabecera `Date`. Basta con que `/` responda algo, aunque sea un 404; casi todos los servidores ponen `Date` solos.

## Qué recibe el motor

`evaluate(telemetry, events, manual_checks, now)` recibe listas de un solo `crew_id`, así que los mensajes con `crew_id: null` no le llegan. Cualquier `null` lo trata como "sin dato", nunca como normal.

## Evaluación ③: qué devuelve el motor

| Campo | Qué es |
|---|---|
| `overall_level`, `systems.*.level` | 0 verde, 1 ámbar, 2 naranja, 3 rojo. **`null` si no hay ningún dato**: se pinta "sin dato", nunca verde |
| `systems.*.reasons` | Motivos en inglés, primero los más graves y después los "no data" |
| `trends` | Un elemento por indicador con datos suficientes (al menos 3 medidas en al menos 1 día): `systolic_mmhg`, `diastolic_mmhg`, `glucose_mg_dl`, `mood`, `pushup_reps` |
| `trends[].projected_7d` | Valor que da la recta dentro de 7 días |
| `trends[].crosses_threshold_in_days` | Días hasta cruzar el siguiente umbral, o `null` si no lo cruza en 7 días |
| `trends[].threshold`, `threshold_level` | Ese umbral y el nivel al que llevaría. `null` si no cruza |
| `trends[].slope_per_day` | Pendiente de la recta, en unidades por día |
| `recommendations` | En inglés: acción del nivel, contramedidas y avisos de tendencia |
| `earth_summary` | Texto en inglés listo para enviar a los médicos en Tierra. Solo si `overall_level` es 3; si no, `null` |

Para que haya tendencias, la API tiene que pasar al motor los chequeos y los eventos de **los últimos 7 días**. La telemetría basta con la del último minuto.

**Modo demo:** con la variable de entorno `SPACEHEALTH_DEMO=1` en el proceso de la API, el ámbar por inactividad salta a los 30 s en vez de a los 600 s, igual que el evento `inactivity` de la placa en la demo.
