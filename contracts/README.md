# Contratos

Ejemplos JSON de lo que se manda entre las partes. Todas las fechas van en UTC (ISO 8601). Cambiar un contrato necesita un PR que aprueben quien produce el dato y quien lo usa.

Fuente de este documento: guía del equipo y notas del electrónico para el backend (14 de noviembre de 2026).

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

Alertas locales posibles en `alerts`: `HR_HIGH`, `HR_LOW`, `BODY_TEMP_HIGH`, `BODY_TEMP_LOW`, `CABIN_TEMP_HIGH`, `CABIN_TEMP_LOW`, `HEAT_INDEX_HIGH`, `CONDENSATION_HIGH`. Nunca llegan `RESP_HIGH` ni `RESP_LOW`. Los niveles oficiales los da el motor, no estas alertas.

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
| 2xx | Lo da por enviado. Da igual que el cuerpo sea `{"ok": true}` o no sea JSON |
| 409 | Lo toma como duplicado ya guardado y no reintenta. Para duplicados vale 200 o 409 |
| Otro 4xx (400, 401, 422…) | Descarta el mensaje y no reintenta: **ese dato se pierde** |
| 5xx o sin respuesta | Reintenta a 1, 2, 4… s, hasta 30 s, con hasta 50 mensajes en cola |

**Hora sin Internet:** si no hay NTP, el ESP32 hace `GET /` al backend y toma la hora de la cabecera `Date`. Basta con que `/` responda algo, aunque sea un 404; casi todos los servidores ponen `Date` solos.

## Qué recibe el motor

`evaluate(telemetry, events, manual_checks, now)` recibe listas de un solo `crew_id`, así que los mensajes con `crew_id: null` no le llegan. Cualquier `null` lo trata como "sin dato", nunca como normal.
