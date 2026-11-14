# AstroMed: formato JSON para el backend

Nov 14, 2026 · @therin · versión definitiva, sacada del firmware

Este documento sustituye a «SpaceHealth qué se mide y qué se manda por JSON final.md» para el backend. Todo lo que pone aquí está comprobado contra el código: `firmware/uno_sensores/uno_sensores.ino`, `firmware/uno_sensores/config.h` y `firmware/esp32_gateway/esp32_gateway.ino`. Si algo no cuadra, manda el código.

## Resumen

Un Arduino UNO mide a cada tripulante y la cabina, un ESP32 reenvía los datos por WiFi y el backend los guarda y los muestra en el dashboard.

1. **Sensores → UNO:** identifica al tripulante por RFID y mide pulso, temperatura corporal, inmovilidad, flexiones y ambiente de cabina.
2. **UNO → ESP32:** puerto serie a 115200 baudios, una línea de JSON por mensaje.
3. **ESP32 → backend:** WiFi, HTTP POST con JSON. El ESP32 añade `device_id` y `ts`.
4. **Backend → dashboard:** estación en Tierra con el último estado de cada tripulante y las alertas.

## Cambios respecto a la versión anterior

Si ya empezaste con la versión anterior, esto es lo que cambia. Lo demás sigue igual.

| Qué | Antes | Ahora |
| --- | --- | --- |
| Sueño | `motion.sleep_state` y evento `sleep_summary` | no existen: ni el campo ni el evento |
| Respiración | `vitals.resp_rate_bpm` con valor | el campo sigue en el JSON pero **siempre es `null`**; `RESP_HIGH` y `RESP_LOW` nunca se envían |
| Movimiento | PIR + interruptor de inclinación | solo el interruptor de inclinación; `activity` y `still_for_s` no cambian de formato |
| HC-SR04 | dos modos (descanso y ejercicio) con pulsador | solo cuenta flexiones; no hay modos. El pulsador solo reinicia `met_s` si se mantiene al encender |
| Cabina | siempre con número | **todos** los `cabin.*` pueden ser `null` (al arrancar y si el DHT11 falla 5 veces seguidas) |
| `cabin.humidity_pct` | número | **entero** |
| `vitals.hr_quality` | número | siempre número de 0 a 1, con 0 si no hay señal; nunca `null` |
| `vitals.heart_rate_bpm` | null si la calidad es mala | igual (null si `hr_quality` < 0,4), y cuando hay valor está entre 35 y 200 |
| `vitals.body_temp_c` | número o null | `null` también fuera de 30–45 °C (el firmware ya filtra) |
| Cambio de tarjeta | no estaba definido | se mandan dos `crew_checkin`: `out` del anterior y luego `in` del nuevo, con el segundo `ts` adelantado 1 s |
| `inactivity` | al pasar el umbral | solo con un tripulante fichado, y una sola vez por cada periodo quieto |
| `exercise_summary` | con `crew_id` | `crew_id` puede ser `null`; también sale al pasar una tarjeta con una serie a medias |
| Respuestas HTTP | `200` o reintento | cualquier 2xx vale; `409` = duplicado; el resto de 4xx **descarta el mensaje** (se pierde); 5xx o sin respuesta = reintento |
| Hora sin Internet | — | el ESP32 hace `GET /` al backend y toma la hora de la cabecera `Date` |
| Decimales | `23.0` | un número con `.0` puede llegar como entero (`23`), por cómo serializa ArduinoJson |
| Validación con `422` | pulso 20–250, respiración 0–60, temperatura 30–45, humedad 0–100 | se quita la respiración, y conviene no rechazar: un 4xx tira el mensaje entero (ver la lista del final) |

## Qué se mide

Son 9 variables: las vitales, el movimiento y la cabina salen cada 2 s; los fichajes, la inactividad y las flexiones van como eventos.

| Variable | Sensor | Unidad | Cuándo se manda | Fiabilidad |
| --- | --- | --- | --- | --- |
| Identificación del tripulante | RFID RC522 + tarjeta o llavero | UID en hexadecimal | evento al pasar la tarjeta, y como `crew_id` en cada mensaje | alta |
| Temperatura corporal | Termistor NTC 10k | °C | cada 2 s | alta, si se calibra |
| Pulso | LED rojo + fotorresistencia | lat/min | cada 2 s (ventana de 10 s) | media |
| Tripulante inmóvil | Interruptor de inclinación (lo lleva el tripulante) | s sin movimiento | cada 2 s, y evento al pasar el umbral | media |
| Flexiones | HC-SR04 en el suelo bajo el pecho | repeticiones y rep/min | resumen al terminar la serie | alta |
| Temperatura de cabina | DHT11 | °C | cada 2 s | media (±2 °C) |
| Humedad de cabina | DHT11 | % | cada 2 s | media (±5 %) |
| Índice de calor | Calculado | °C | cada 2 s | la del DHT11 |
| Riesgo de condensación | Calculado (punto de rocío) | bajo, medio, alto | cada 2 s | la del DHT11 |

La respiración no se mide. `resp_rate_bpm` se queda en el JSON a `null` para no cambiar el formato.

El pulso, la temperatura corporal y el movimiento se miden siempre, haya o no alguien fichado. Si `crew_id` es `null`, esos valores no son de ningún tripulante.

> **Estado actual del firmware:** en `config.h` está `PRUEBA_RFID_US = 1` (prueba por partes). Así solo salen los eventos `crew_checkin` y `exercise_summary`, y no hay telemetría ni `inactivity`. Con `PRUEBA_RFID_US = 0` sale todo lo de este documento.

## Tarjetas registradas

Las dos tarjetas del kit ya se leen con el RC522; su UID es el `crew_id` que va en cada mensaje.

| `crew_id` | Tipo | Tripulante |
| --- | --- | --- |
| `F3786E09` | MIFARE 1K | Tripulante 1 (por asignar) |
| `336F8312` | MIFARE 1K | Tripulante 2 (por asignar) |

El UID va en hexadecimal en mayúsculas, sin separadores: 8 caracteres (UID de 4 bytes), o 14 o 20 si alguna vez se usa una tarjeta con UID de 7 o 10 bytes.

## Cómo se envía

El ESP32 manda dos tipos de mensaje, ambos como POST con JSON: telemetría cada 2 s y eventos al instante.

| Endpoint | Cuándo | Qué lleva |
| --- | --- | --- |
| `POST /api/v1/telemetry` | cada 2 s | vitales, movimiento, cabina y alertas activas |
| `POST /api/v1/events` | al ocurrir | fichajes RFID, inactividad y resúmenes de flexiones |
| `GET /` | solo si no hay NTP | nada; el ESP32 solo lee la cabecera `Date` de la respuesta |

- Cabeceras de los POST: `Content-Type: application/json` y `X-API-Key: <clave>`. El `GET /` va **sin** `X-API-Key`.
- URL exacta: `API_BASE` + la ruta, sin barra final (`http://192.168.1.50:8000/api/v1/telemetry`). Con `https`, el ESP32 no comprueba el certificado.
- Tiempo máximo de respuesta: 4 s para conectar y 4 s para responder. Pasado eso cuenta como «sin respuesta».
- Todas las fechas van en UTC, ISO 8601, con precisión de segundos: `2026-11-14T10:30:05Z`.

Qué hace el ESP32 con cada respuesta del backend:

| Respuesta | Qué hace el ESP32 |
| --- | --- |
| 2xx con `{"ok": true}`, sin cuerpo o con un cuerpo que no es JSON | enviado: lo quita de la cola |
| 2xx con JSON en el que `ok` es `false` (o no es `true`) | lo trata como fallo y **reintenta sin fin** |
| `409` | duplicado: lo da por enviado y no reintenta |
| `408` o `429` | reintenta |
| otro 4xx (`400`, `401`, `404`, `422`…) | **lo descarta**: el mensaje se pierde y solo queda impreso en el monitor serie del ESP32 |
| 5xx, 3xx, tiempo agotado o sin conexión | reintenta |

- Reintentos: a 1 s, 2 s, 4 s… hasta 30 s entre intentos, y vuelve a 1 s tras un envío correcto.
- Se envía en orden: mientras el primer mensaje de la cola falla, los demás esperan detrás.
- La cola guarda 50 mensajes (unos 4 minutos de telemetría). Si se llena, se descarta el más antiguo.
- El ESP32 no sigue redirecciones: un 3xx se reintenta para siempre.

## JSON de telemetría

Cada 2 s el ESP32 manda un solo objeto con el estado del tripulante y de la cabina. Siempre van todas las claves; lo que no se pudo medir va como `null`.

```json
{
  "device_id": "esp32-01",
  "ts": "2026-11-14T10:30:05Z",
  "met_s": 18245,
  "crew_id": "F3786E09",
  "vitals": {
    "heart_rate_bpm": 72,
    "hr_quality": 0.85,
    "resp_rate_bpm": null,
    "body_temp_c": 36.7
  },
  "motion": {
    "activity": "still",
    "still_for_s": 120
  },
  "cabin": {
    "temp_c": 24.6,
    "humidity_pct": 48,
    "dew_point_c": 12.9,
    "heat_index_c": 24.6,
    "condensation_risk": "low"
  },
  "alerts": []
}
```

Así llega cuando no se mide nada: nadie ha fichado, no hay dedo en el sensor de pulso, el termistor está suelto y el DHT11 aún no ha respondido.

```json
{
  "device_id": "esp32-01",
  "ts": "2026-11-14T10:30:10Z",
  "met_s": 18250,
  "crew_id": null,
  "vitals": {
    "heart_rate_bpm": null,
    "hr_quality": 0,
    "resp_rate_bpm": null,
    "body_temp_c": null
  },
  "motion": {
    "activity": "moving",
    "still_for_s": 0
  },
  "cabin": {
    "temp_c": null,
    "humidity_pct": null,
    "dew_point_c": null,
    "heat_index_c": null,
    "condensation_risk": null
  },
  "alerts": []
}
```

Con alertas activas, `alerts` lleva los códigos en este orden fijo, sin repetir: `["HR_HIGH", "BODY_TEMP_HIGH", "CABIN_TEMP_HIGH", "HEAT_INDEX_HIGH"]`.

| Campo | Tipo | ¿Puede ser `null`? | Unidad o valores | Notas |
| --- | --- | --- | --- | --- |
| `device_id` | texto | no | — | identifica el ESP32 (`DEVICE_ID` en su `config.h`) |
| `ts` | texto | no | ISO 8601 UTC, `AAAA-MM-DDThh:mm:ssZ` | hora a la que el ESP32 recibió el mensaje; ver «Hora y duplicados» |
| `met_s` | entero | no | s, ≥ 0 | tiempo de misión desde el RTC DS1307; sin RTC, segundos desde que arrancó el UNO |
| `crew_id` | texto | sí | UID en hexadecimal | `null` si nadie ha fichado |
| `vitals.heart_rate_bpm` | entero | sí | lat/min, 35 a 200 | `null` si no hay pulso o `hr_quality` < 0,4 |
| `vitals.hr_quality` | número | no | 0 a 1, 2 decimales | calidad de la señal del pulso; 0 sin señal |
| `vitals.resp_rate_bpm` | null | siempre | — | no se mide; se mantiene por compatibilidad |
| `vitals.body_temp_c` | número | sí | °C, 1 decimal, 30,0 a 45,0 | `null` con el termistor suelto o fuera de 30–45 °C |
| `motion.activity` | texto | no | `moving` o `still` | `moving` si el interruptor se movió en los últimos 3 s |
| `motion.still_for_s` | entero | no | s | 0 si `moving`; 3 o más si `still` |
| `cabin.temp_c` | número | sí | °C, 1 decimal | DHT11 |
| `cabin.humidity_pct` | entero | sí | %, 0 a 100 | DHT11, redondeado |
| `cabin.dew_point_c` | número | sí | °C, 1 decimal | calculado; puede ser negativo |
| `cabin.heat_index_c` | número | sí | °C, 1 decimal | calculado; igual a `temp_c` fuera del rango de la fórmula |
| `cabin.condensation_risk` | texto | sí | `low`, `medium` o `high` | calculado |
| `alerts` | lista de textos | no | códigos de la tabla siguiente | los activos en ese momento; `[]` si no hay ninguno |

Notas sobre los valores:

- **Cabina, todo o nada:** los cinco `cabin.*` son `null` a la vez o tienen valor a la vez. Son `null` desde que arranca el UNO hasta la primera lectura buena del DHT11, y cuando falla 5 veces seguidas (unos 12 s). Con 1 a 4 fallos se repite la última lectura buena.
- **Decimales:** el UNO manda los números con decimales fijos, pero el ESP32 los vuelve a serializar con ArduinoJson, que puede quitar el `.0`. Así, `23.0` puede llegar como `23` y `0.00` como `0`. Lee los campos «número» como número, sea entero o decimal.
- **Alertas sin redondear:** las alertas se calculan con el valor antes de redondear. En el límite puede salir `BODY_TEMP_HIGH` con `body_temp_c` a `38.0`.

## Códigos de alerta

Estos son los únicos códigos que el firmware puede mandar, con umbrales de demo (no clínicos, en `uno_sensores/config.h`). Cada uno sale solo si su valor no es `null`.

| Código | Condición |
| --- | --- |
| `HR_HIGH` | pulso mayor de 120 lat/min |
| `HR_LOW` | pulso menor de 45 lat/min |
| `BODY_TEMP_HIGH` | más de 38,0 °C |
| `BODY_TEMP_LOW` | menos de 35,5 °C |
| `CABIN_TEMP_HIGH` | más de 28 °C |
| `CABIN_TEMP_LOW` | menos de 18 °C |
| `HEAT_INDEX_HIGH` | índice de calor mayor de 32 °C |
| `CONDENSATION_HIGH` | riesgo de condensación alto |

`RESP_HIGH` y `RESP_LOW` ya no existen. Las alertas no generan eventos: son un estado que va en cada telemetría. Si el backend quiere avisar cuando empieza o acaba una alerta, lo tiene que deducir comparando con la telemetría anterior.

## JSON de eventos

Todo lo que no es una lectura periódica va a `/api/v1/events` con el mismo sobre y un campo `type` que dice qué hay en `data`. Siempre van las seis claves.

```json
{
  "device_id": "esp32-01",
  "ts": "2026-11-14T10:32:10Z",
  "crew_id": "F3786E09",
  "type": "crew_checkin",
  "severity": "info",
  "data": { "action": "in" }
}
```

```json
{
  "device_id": "esp32-01",
  "ts": "2026-11-14T10:41:02Z",
  "crew_id": "F3786E09",
  "type": "inactivity",
  "severity": "medium",
  "data": { "still_for_s": 30, "threshold_s": 30 }
}
```

```json
{
  "device_id": "esp32-01",
  "ts": "2026-11-14T10:45:37Z",
  "crew_id": null,
  "type": "exercise_summary",
  "severity": "info",
  "data": { "exercise": "pushup", "reps": 12, "duration_s": 17, "cadence_rpm": 41.6 }
}
```

| `type` | Cuándo se manda | `severity` | `crew_id` |
| --- | --- | --- | --- |
| `crew_checkin` | al pasar una tarjeta por el RC522 | `info` | siempre con valor |
| `inactivity` | el tripulante fichado pasa el umbral sin moverse | `medium` | siempre con valor |
| `exercise_summary` | 10 s después de la última flexión, o al pasar una tarjeta con una serie a medias | `info` | puede ser `null` |

Contenido de `data`:

| `type` | Campo de `data` | Tipo | Valores | Notas |
| --- | --- | --- | --- | --- |
| `crew_checkin` | `action` | texto | `in` o `out` | `in` empieza a medir a ese tripulante; `out` lo saca |
| `inactivity` | `still_for_s` | entero | s, ≥ `threshold_s` | segundos quieto al saltar el aviso |
| `inactivity` | `threshold_s` | entero | s | 30 en la demo, 600 en real (`INACTIVITY_THRESHOLD_S`) |
| `exercise_summary` | `exercise` | texto | siempre `pushup` | |
| `exercise_summary` | `reps` | entero | ≥ 1 | repeticiones de la serie |
| `exercise_summary` | `duration_s` | entero | s, ≥ 1 | de la primera bajada a la última subida, redondeado |
| `exercise_summary` | `cadence_rpm` | número | rep/min, 1 decimal | `reps × 60 / duración` (con la duración sin redondear) |

Cómo se comporta cada evento:

- **Fichaje:** la misma tarjeta otra vez manda `out` y deja a nadie fichado. Otra tarjeta con alguien dentro manda dos eventos seguidos: `out` del anterior y `in` del nuevo. Si se lee la misma tarjeta dos veces en menos de 2 s, la segunda se ignora.

  | `ts` | `crew_id` | `action` |
  | --- | --- | --- |
  | `2026-11-14T10:50:00Z` | `F3786E09` | `out` |
  | `2026-11-14T10:50:01Z` | `336F8312` | `in` |

- **Inactividad:** solo sale con alguien fichado, y una sola vez por periodo quieto. Para que vuelva a salir, el tripulante tiene que moverse y volver a quedarse quieto el tiempo del umbral. Pasar una tarjeta cuenta como movimiento.
- **Flexiones:** se cuentan aunque no haya nadie fichado, y entonces `crew_id` es `null`. Si se pasa una tarjeta con una serie a medias, el resumen sale justo después de los `crew_checkin`. Ojo: en ese caso lleva el `crew_id` del tripulante que **acaba de entrar** (o `null` si el anterior salió con su propia tarjeta), no el de quien hizo las flexiones. Una bajada sin subida se descarta a los 30 s sin mandar nada.

## Hora y duplicados

El `ts` lo pone el ESP32, no el UNO, y no cambia en los reintentos. Por eso el backend puede descartar duplicados por `(device_id, ts, type)`, tomando `type` = telemetría para `/api/v1/telemetry`.

- El ESP32 toma la hora por NTP (`pool.ntp.org`, `time.google.com`). Si a los 15 s de tener WiFi sigue sin hora, prueba cada 30 s con `GET /` al backend y usa la cabecera `Date` (formato HTTP: `Sat, 14 Nov 2026 10:30:05 GMT`). Vale cualquier código de respuesta, mientras traiga `Date`.
- Hasta tener hora no envía nada, pero guarda los mensajes en la cola. Cuando la consigue, a cada mensaje le pone la hora a la que llegó del UNO (hacia atrás).
- Dos mensajes del mismo tipo nunca comparten segundo: si caerían en el mismo, el segundo se adelanta 1 s (y el siguiente otro más, si hace falta). Pasa sobre todo con el `out` y el `in` al cambiar de tarjeta. Así el `ts` de cada tipo siempre sube.
- Tipos distintos sí pueden compartir segundo (por ejemplo, un `crew_checkin` y un `exercise_summary`).

## Cálculos

El UNO calcula el punto de rocío, el índice de calor y el riesgo de condensación a partir de la temperatura y la humedad; el backend puede recalcularlos con las mismas fórmulas.

Punto de rocío (fórmula de Magnus), con T en °C y RH en % (si RH es menor que 1, se usa 1). Con 23 °C y 45 % da 10,4 °C.

```latex
\gamma = \ln\left(\frac{RH}{100}\right) + \frac{17.62\,T}{243.12 + T}, \qquad T_d = \frac{243.12\,\gamma}{17.62 - \gamma}
```

Índice de calor: regresión de Rothfusz de la NOAA, que trabaja en °F y solo es válida desde 80 °F (26,7 °C) y 40 % de humedad. Por debajo de eso, `heat_index_c` es igual a `temp_c`.

Riesgo de condensación: se mide con el margen entre la temperatura de cabina y el punto de rocío.

| Margen (`temp_c` menos `dew_point_c`) | `condensation_risk` |
| --- | --- |
| más de 5 °C | `low` |
| de 2 a 5 °C | `medium` |
| menos de 2 °C | `high` |

No hay sensor en las paredes, que son las superficies más frías, así que estos márgenes son prudentes a propósito.

Los cálculos se hacen con la humedad sin redondear, así que recalcularlos con `humidity_pct` puede dar una décima de diferencia.

## Qué decirle al backend

Los seis primeros puntos bastan para que la demo funcione sin perder datos; el resto lo mejora.

- [ ] Exponer `POST /api/v1/telemetry` y `POST /api/v1/events` exactamente con esas rutas (sin barra final y sin redirigir de `http` a `https`), con JSON y la cabecera `X-API-Key`, y responder `200` con `{"ok": true}` en menos de 4 s.
- [ ] No responder nunca 2xx con `{"ok": false}`: el ESP32 lo reintenta sin fin y bloquea la cola.
- [ ] Aceptar `null` en `crew_id`, `heart_rate_bpm`, `resp_rate_bpm` (siempre `null`), `body_temp_c` y en **todos** los `cabin.*`, sin tratarlo como error.
- [ ] Guardar cada mensaje con su `ts` en UTC y su `crew_id`, y tratar los duplicados (misma combinación de `device_id`, `ts` y `type`) respondiendo `200` o `409`, nunca otro 4xx.
- [ ] No rechazar con 4xx datos que son válidos aunque no se esperen (un `crew_id` sin asignar, un valor raro, un campo de más, un `type` desconocido): cualquier 4xx que no sea `408`, `409` o `429` hace que el ESP32 **tire el mensaje**. Guárdalo y márcalo. Usa `401` solo para la clave mala y `400` solo para JSON roto. Si hay que limitar, responde `429`, que sí se reintenta.
- [ ] Responder a `GET /` sin pedir `X-API-Key` y con cabecera `Date` (casi todos los servidores la ponen solos). Es como el ESP32 saca la hora sin Internet.
- [ ] Leer los campos «número» como número, sea entero o decimal (`23` o `23.0`).
- [ ] Servir el último estado de cada tripulante: `GET /api/v1/crew/{crew_id}/latest`.
- [ ] Asociar `crew_id` (UID del RFID) con nombre y rol; un UID desconocido se guarda igual y se marca como sin asignar.
- [ ] Decidir qué hacer con la telemetría con `crew_id` a `null` (vitales que no son de nadie): guardarla aparte o no mostrarla en ningún tripulante.
- [ ] Servir el histórico: `GET /api/v1/crew/{crew_id}/telemetry?from=&to=`.
- [ ] Servir los eventos, filtrables: `GET /api/v1/events?crew_id=&type=`.
- [ ] Deducir el inicio y el fin de cada alerta comparando telemetrías seguidas, y avisar al dashboard en tiempo real (WebSocket o SSE) cuando empiece una alerta o llegue un evento.
- [ ] Guardar los umbrales de alerta como configuración editable, con los valores de la tabla de códigos como punto de partida.
- [ ] Si se validan rangos, hacerlo al menos con estos márgenes, que el firmware ya garantiza: pulso 35–200, `hr_quality` 0–1, temperatura corporal 30–45 °C, humedad 0–100 %. Mejor marcar el valor como sospechoso que responder `422`, porque `422` pierde el mensaje entero. La respiración ya no se valida.
- [ ] Permitir CORS para el origen del dashboard.

## JSON Schema

Describen exactamente lo que manda el firmware (draft 2020-12). Son estrictos (`additionalProperties: false`) para fijar el formato; en el backend conviene no rechazar por un campo de más, por lo dicho en la lista anterior.

Telemetría (`POST /api/v1/telemetry`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "astromed/telemetry.schema.json",
  "title": "AstroMed telemetría",
  "type": "object",
  "required": ["device_id", "ts", "met_s", "crew_id", "vitals", "motion", "cabin", "alerts"],
  "additionalProperties": false,
  "properties": {
    "device_id": { "type": "string", "minLength": 1 },
    "ts": { "$ref": "#/$defs/ts" },
    "met_s": { "type": "integer", "minimum": 0, "maximum": 4294967295 },
    "crew_id": { "$ref": "#/$defs/crew_id_or_null" },
    "vitals": {
      "type": "object",
      "required": ["heart_rate_bpm", "hr_quality", "resp_rate_bpm", "body_temp_c"],
      "additionalProperties": false,
      "properties": {
        "heart_rate_bpm": { "type": ["integer", "null"], "minimum": 35, "maximum": 200 },
        "hr_quality": { "type": "number", "minimum": 0, "maximum": 1 },
        "resp_rate_bpm": { "type": "null" },
        "body_temp_c": { "type": ["number", "null"], "minimum": 30, "maximum": 45 }
      }
    },
    "motion": {
      "type": "object",
      "required": ["activity", "still_for_s"],
      "additionalProperties": false,
      "properties": {
        "activity": { "enum": ["moving", "still"] },
        "still_for_s": { "type": "integer", "minimum": 0 }
      },
      "if": { "properties": { "activity": { "const": "moving" } } },
      "then": { "properties": { "still_for_s": { "const": 0 } } },
      "else": { "properties": { "still_for_s": { "minimum": 3 } } }
    },
    "cabin": {
      "type": "object",
      "required": ["temp_c", "humidity_pct", "dew_point_c", "heat_index_c", "condensation_risk"],
      "additionalProperties": false,
      "oneOf": [
        {
          "properties": {
            "temp_c": { "type": "number" },
            "humidity_pct": { "type": "integer", "minimum": 0, "maximum": 100 },
            "dew_point_c": { "type": "number" },
            "heat_index_c": { "type": "number" },
            "condensation_risk": { "enum": ["low", "medium", "high"] }
          }
        },
        {
          "properties": {
            "temp_c": { "type": "null" },
            "humidity_pct": { "type": "null" },
            "dew_point_c": { "type": "null" },
            "heat_index_c": { "type": "null" },
            "condensation_risk": { "type": "null" }
          }
        }
      ],
      "properties": {
        "temp_c": true,
        "humidity_pct": true,
        "dew_point_c": true,
        "heat_index_c": true,
        "condensation_risk": true
      }
    },
    "alerts": {
      "type": "array",
      "uniqueItems": true,
      "items": {
        "enum": [
          "HR_HIGH", "HR_LOW",
          "BODY_TEMP_HIGH", "BODY_TEMP_LOW",
          "CABIN_TEMP_HIGH", "CABIN_TEMP_LOW",
          "HEAT_INDEX_HIGH", "CONDENSATION_HIGH"
        ]
      }
    }
  },
  "$defs": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
    },
    "crew_id": { "type": "string", "pattern": "^([0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})$" },
    "crew_id_or_null": { "oneOf": [{ "$ref": "#/$defs/crew_id" }, { "type": "null" }] }
  }
}
```

Eventos (`POST /api/v1/events`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "astromed/event.schema.json",
  "title": "AstroMed evento",
  "type": "object",
  "required": ["device_id", "ts", "crew_id", "type", "severity", "data"],
  "additionalProperties": false,
  "properties": {
    "device_id": { "type": "string", "minLength": 1 },
    "ts": { "$ref": "#/$defs/ts" },
    "crew_id": true,
    "type": { "enum": ["crew_checkin", "inactivity", "exercise_summary"] },
    "severity": { "enum": ["info", "medium"] },
    "data": { "type": "object" }
  },
  "oneOf": [
    {
      "properties": {
        "type": { "const": "crew_checkin" },
        "severity": { "const": "info" },
        "crew_id": { "$ref": "#/$defs/crew_id" },
        "data": {
          "type": "object",
          "required": ["action"],
          "additionalProperties": false,
          "properties": { "action": { "enum": ["in", "out"] } }
        }
      }
    },
    {
      "properties": {
        "type": { "const": "inactivity" },
        "severity": { "const": "medium" },
        "crew_id": { "$ref": "#/$defs/crew_id" },
        "data": {
          "type": "object",
          "required": ["still_for_s", "threshold_s"],
          "additionalProperties": false,
          "properties": {
            "still_for_s": { "type": "integer", "minimum": 1 },
            "threshold_s": { "type": "integer", "minimum": 1 }
          }
        }
      }
    },
    {
      "properties": {
        "type": { "const": "exercise_summary" },
        "severity": { "const": "info" },
        "crew_id": { "oneOf": [{ "$ref": "#/$defs/crew_id" }, { "type": "null" }] },
        "data": {
          "type": "object",
          "required": ["exercise", "reps", "duration_s", "cadence_rpm"],
          "additionalProperties": false,
          "properties": {
            "exercise": { "const": "pushup" },
            "reps": { "type": "integer", "minimum": 1 },
            "duration_s": { "type": "integer", "minimum": 1 },
            "cadence_rpm": { "type": "number", "exclusiveMinimum": 0 }
          }
        }
      }
    }
  ],
  "$defs": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
    },
    "crew_id": { "type": "string", "pattern": "^([0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})$" }
  }
}
```

JSON Schema no puede comparar dos campos, así que `still_for_s ≥ threshold_s` en `inactivity` queda solo en la tabla de `data`.

## Límites

Ninguna medida es de grado médico: es una demo con sensores de un kit educativo.

- **Pulso:** la fotorresistencia es lenta y ruidosa, por eso existe `hr_quality` y el pulso va a `null` cuando la señal es mala.
- **Respiración:** no se mide.
- **Movimiento:** solo hay un interruptor de inclinación; un tripulante que se mueve sin inclinarlo cuenta como quieto.
- **Flexiones:** cuenta bien si el pecho pasa justo por encima del sensor; flexiones a medias pueden no contar.
- **Temperatura corporal:** solo es fiable si el termistor se calibra contra un termómetro clínico.
- **Cabina:** el DHT11 tiene ±2 °C y ±5 % de humedad; el punto de rocío y el índice de calor heredan ese error.
- **Umbrales:** los de las alertas son valores de demo, no clínicos.
