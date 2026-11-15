# AstroMed · Team Antares: JSON format for the backend

Final version, derived from the firmware.

This document defines the final AstroMed firmware format for the Team Antares backend. Everything in it was checked against the code: `firmware/uno_sensors/uno_sensors.ino`, `firmware/uno_sensors/config.h` and `firmware/esp32_gateway/esp32_gateway.ino`. If something does not match, the code wins.

## Overview

An Arduino UNO measures each crew member and the cabin, an ESP32 forwards the data over WiFi, and the backend stores it and shows it on the dashboard.

1. **Sensors → UNO:** identifies the crew member by RFID and measures pulse, body temperature, immobility, push-ups and cabin environment.
2. **UNO → ESP32:** serial port at 115200 baud, one JSON line per message.
3. **ESP32 → backend:** WiFi, HTTP POST with JSON. The ESP32 adds `device_id` and `ts`.
4. **Backend → dashboard:** ground station with the latest state of each crew member and the alerts.

## What is measured

There are 9 variables: vitals, motion and cabin are sent every 2 s; check-ins, inactivity and push-ups go as events.

| Variable | Sensor | Unit | When it is sent | Reliability |
| --- | --- | --- | --- | --- |
| Crew member identification | RFID RC522 + card or key fob | UID in hexadecimal | event when the card is scanned, and as `crew_id` in every message | high |
| Body temperature | 10k NTC thermistor | °C | every 2 s | high, if calibrated |
| Pulse | Red LED + photoresistor | beats/min | every 2 s (10 s window) | medium |
| Crew member immobile | Tilt switch (worn by the crew member) | s without motion | every 2 s, and an event when the threshold is passed | medium |
| Push-ups | HC-SR04 on the floor under the chest | repetitions and reps/min | summary when the set ends | high |
| Cabin temperature | DHT11 | °C | every 2 s | medium (±2 °C) |
| Cabin humidity | DHT11 | % | every 2 s | medium (±5 %) |
| Heat index | Calculated | °C | every 2 s | same as the DHT11 |
| Condensation risk | Calculated (dew point) | low, medium, high | every 2 s | same as the DHT11 |

Breathing is not measured. `resp_rate_bpm` stays in the JSON as `null` so the format does not change.

Pulse, body temperature and motion are always measured, whether or not someone is checked in. If `crew_id` is `null`, those values do not belong to any crew member.

> **Final firmware state:** `config.h` has `TEST_RFID_US = 0`, which enables the telemetry and events in this document. The value `1` is reserved for testing RFID and ultrasound separately, with no telemetry or inactivity events.

## Registered cards

The kit's two cards are already read by the RC522; their UID is the `crew_id` sent in every message.

| `crew_id` | Type | Crew member |
| --- | --- | --- |
| `F3786E09` | MIFARE 1K | Crew member 1 (to be assigned) |
| `336F8312` | MIFARE 1K | Crew member 2 (to be assigned) |

The UID is uppercase hexadecimal with no separators: 8 characters (4-byte UID), or 14 or 20 if a card with a 7- or 10-byte UID is ever used.

## How it is sent

The ESP32 sends two kinds of message, both as POST with JSON: telemetry every 2 s and events immediately.

| Endpoint | When | What it carries |
| --- | --- | --- |
| `POST /api/v1/telemetry` | every 2 s | vitals, motion, cabin and active alerts |
| `POST /api/v1/events` | when it happens | RFID check-ins, inactivity and push-up summaries |
| `GET /` | only if there is no NTP | nothing; the ESP32 only reads the `Date` header of the response |

- POST headers: `Content-Type: application/json` and `X-API-Key: <key>`. `GET /` is sent **without** `X-API-Key`.
- Exact URL: `API_BASE` + the path, no trailing slash (`http://192.168.1.50:8000/api/v1/telemetry`). With `https`, the ESP32 does not verify the certificate.
- Maximum response time: 4 s to connect and 4 s to respond. After that it counts as "no response".
- All dates are UTC, ISO 8601, with second precision: `2026-11-14T10:30:05Z`.

What the ESP32 does with each backend response:

| Response | What the ESP32 does |
| --- | --- |
| 2xx with `{"ok": true}`, no body, or a body that is not JSON | sent: removes it from the queue |
| 2xx with JSON where `ok` is `false` (or not `true`) | treats it as a failure and **retries forever** |
| `409` | duplicate: counts it as sent and does not retry |
| `401`, `403`, `408` or `429` | retries (a wrong API key does not lose data: fix the key and the queue drains) |
| any other 4xx (`400`, `404`, `422`…) | **drops it**: the message is lost and only printed on the ESP32 serial monitor |
| 5xx, 3xx, timeout or no connection | retries |

- Retries: at 1 s, 2 s, 4 s… up to 30 s between attempts, and back to 1 s after a successful send.
- Messages are sent in order: while the first message in the queue fails, the rest wait behind it.
- The queue holds 50 messages (about 4 minutes of telemetry). If it fills up, the oldest is dropped.
- The ESP32 does not follow redirects: a 3xx is retried forever.

## Telemetry JSON

Every 2 s the ESP32 sends a single object with the state of the crew member and the cabin. All keys are always present; anything that could not be measured is `null`.

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

This is what arrives when nothing is measured: nobody has checked in, there is no finger on the pulse sensor, the thermistor is loose and the DHT11 has not responded yet.

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

With active alerts, `alerts` carries the codes in this fixed order, without repeats: `["HR_HIGH", "BODY_TEMP_HIGH", "CABIN_TEMP_HIGH", "HEAT_INDEX_HIGH"]`.

| Field | Type | Can be `null`? | Unit or values | Notes |
| --- | --- | --- | --- | --- |
| `device_id` | string | no | — | identifies the ESP32 (`DEVICE_ID` in its `config.h`) |
| `ts` | string | no | ISO 8601 UTC, `YYYY-MM-DDThh:mm:ssZ` | time at which the ESP32 received the message; see "Time and duplicates" |
| `met_s` | integer | no | s, ≥ 0 | mission time from the DS1307 RTC; without an RTC, seconds since the UNO started |
| `crew_id` | string | yes | UID in hexadecimal | `null` if nobody has checked in |
| `vitals.heart_rate_bpm` | integer | yes | beats/min, 35 to 200 | `null` if there is no pulse or `hr_quality` < 0.4 |
| `vitals.hr_quality` | number | no | 0 to 1, 2 decimals | pulse signal quality; 0 with no signal |
| `vitals.resp_rate_bpm` | null | always | — | not measured; kept for compatibility |
| `vitals.body_temp_c` | number | yes | °C, 1 decimal, 30.0 to 45.0 | `null` with a loose thermistor or outside 30–45 °C |
| `motion.activity` | string | no | `moving` or `still` | `moving` if the switch moved in the last 3 s |
| `motion.still_for_s` | integer | no | s | 0 if `moving`; 3 or more if `still` |
| `cabin.temp_c` | number | yes | °C, 1 decimal | DHT11 |
| `cabin.humidity_pct` | integer | yes | %, 0 to 100 | DHT11, rounded |
| `cabin.dew_point_c` | number | yes | °C, 1 decimal | calculated; can be negative |
| `cabin.heat_index_c` | number | yes | °C, 1 decimal | calculated; equal to `temp_c` outside the formula's range |
| `cabin.condensation_risk` | string | yes | `low`, `medium` or `high` | calculated |
| `alerts` | list of strings | no | codes from the next table | those active at that moment; `[]` if none |

Notes on the values:

- **Cabin, all or nothing:** the five `cabin.*` fields are all `null` or all have a value. They are `null` from UNO startup until the first good DHT11 reading, and when it fails 5 times in a row (about 12 s). With 1 to 4 failures the last good reading is repeated.
- **Decimals:** the UNO sends numbers with fixed decimals, but the ESP32 re-serializes them with ArduinoJson, which may drop the `.0`. So `23.0` can arrive as `23` and `0.00` as `0`. Read "number" fields as a number, whether integer or decimal.
- **Unrounded alerts:** alerts are computed from the value before rounding. At the limit, `BODY_TEMP_HIGH` can appear with `body_temp_c` at `38.0`.

## Alert codes

These are the only codes the firmware can send, with demo thresholds (not clinical, in `uno_sensors/config.h`). Each one appears only if its value is not `null`.

| Code | Condition |
| --- | --- |
| `HR_HIGH` | pulse above 120 beats/min |
| `HR_LOW` | pulse below 45 beats/min |
| `BODY_TEMP_HIGH` | above 38.0 °C |
| `BODY_TEMP_LOW` | below 35.5 °C |
| `CABIN_TEMP_HIGH` | above 28 °C |
| `CABIN_TEMP_LOW` | below 18 °C |
| `HEAT_INDEX_HIGH` | heat index above 32 °C |
| `CONDENSATION_HIGH` | condensation risk high |

Alerts do not generate events: they are a state carried in every telemetry message. If the backend wants to notify when an alert starts or ends, it has to infer that by comparing with the previous telemetry.

## Events JSON

Everything that is not a periodic reading goes to `/api/v1/events` with the same envelope and a `type` field saying what is in `data`. All six keys are always present.

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

| `type` | When it is sent | `severity` | `crew_id` |
| --- | --- | --- | --- |
| `crew_checkin` | when a card is scanned on the RC522 | `info` | always has a value |
| `inactivity` | the checked-in crew member passes the threshold without moving | `medium` | always has a value |
| `exercise_summary` | 10 s after the last push-up, or when a card is scanned mid-set | `info` | can be `null` |

Contents of `data`:

| `type` | `data` field | Type | Values | Notes |
| --- | --- | --- | --- | --- |
| `crew_checkin` | `action` | string | `in` or `out` | `in` starts measuring that crew member; `out` removes them |
| `inactivity` | `still_for_s` | integer | s, ≥ `threshold_s` | seconds still when the warning fired |
| `inactivity` | `threshold_s` | integer | s | 30 in the demo, 600 in real use (`INACTIVITY_THRESHOLD_S`) |
| `exercise_summary` | `exercise` | string | always `pushup` | |
| `exercise_summary` | `reps` | integer | ≥ 1 | repetitions in the set |
| `exercise_summary` | `duration_s` | integer | s, ≥ 1 | from the first descent to the last rise, rounded |
| `exercise_summary` | `cadence_rpm` | number | reps/min, 1 decimal | `reps × 60 / duration` (with the unrounded duration) |

How each event behaves:

- **Check-in:** the same card again sends `out` and leaves nobody checked in. A different card while someone is checked in sends two events in a row: `out` for the previous one and `in` for the new one. If the same card is read twice within 2 s, the second read is ignored.

  | `ts` | `crew_id` | `action` |
  | --- | --- | --- |
  | `2026-11-14T10:50:00Z` | `F3786E09` | `out` |
  | `2026-11-14T10:50:01Z` | `336F8312` | `in` |

- **Inactivity:** only sent with someone checked in, and only once per still period. For it to fire again, the crew member has to move and then stay still for the threshold time. Scanning a card counts as movement.
- **Push-ups:** counted even if nobody is checked in, in which case `crew_id` is `null`. If a card is scanned mid-set, the summary is sent right after the `crew_checkin` events. Note: in that case it carries the `crew_id` of the crew member who **just checked in** (or `null` if the previous one checked out with their own card), not that of the person who did the push-ups. A descent with no rise is discarded after 30 s without sending anything.

## Time and duplicates

The `ts` is set by the ESP32, not the UNO, and does not change on retries. That is why the backend can discard duplicates by `(device_id, ts, type)`, taking `type` = telemetry for `/api/v1/telemetry`.

- The ESP32 gets the time via NTP (`pool.ntp.org`, `time.google.com`). If it still has no time 15 s after WiFi comes up, it tries every 30 s with `GET /` to the backend and uses the `Date` header (HTTP format: `Sat, 14 Nov 2026 10:30:05 GMT`). Any response code works, as long as it carries `Date`.
- Until it has the time it sends nothing, but it keeps messages in the queue. Once it gets the time, it stamps each message with the time it arrived from the UNO (backdated).
- Two messages of the same type never share a second: if they would fall in the same one, the second is moved ahead by 1 s (and the next by another, if needed). This happens mostly with the `out` and `in` when swapping cards. This way the `ts` of each type always increases.
- Different types can share a second (for example, a `crew_checkin` and an `exercise_summary`).

## Calculations

The UNO calculates the dew point, heat index and condensation risk from temperature and humidity; the backend can recompute them with the same formulas.

Dew point (Magnus formula), with T in °C and RH in % (if RH is less than 1, 1 is used). With 23 °C and 45 % it gives 10.4 °C.

```latex
\gamma = \ln\left(\frac{RH}{100}\right) + \frac{17.62\,T}{243.12 + T}, \qquad T_d = \frac{243.12\,\gamma}{17.62 - \gamma}
```

Heat index: NOAA's Rothfusz regression, which works in °F and is only valid from 80 °F (26.7 °C) and 40 % humidity. Below that, `heat_index_c` equals `temp_c`.

Condensation risk: measured by the margin between the cabin temperature and the dew point.

| Margin (`temp_c` minus `dew_point_c`) | `condensation_risk` |
| --- | --- |
| more than 5 °C | `low` |
| 2 to 5 °C | `medium` |
| less than 2 °C | `high` |

There is no sensor on the walls, which are the coldest surfaces, so these margins are deliberately conservative.

The calculations use the unrounded humidity, so recomputing them with `humidity_pct` can differ by a tenth.

## Backend integration requirements

This is the reference for the protocol between the ESP32 and the AstroMed API. The integrated implementation is described in [the API guide](../api/README.md).

- Expose `POST /api/v1/telemetry` and `POST /api/v1/events` with exactly those paths (no trailing slash and no `http` to `https` redirect), with JSON and the `X-API-Key` header, and reply `200` with `{"ok": true}` in under 4 s.
- Never reply 2xx with `{"ok": false}`: the ESP32 retries it forever and blocks the queue.
- Accept `null` in `crew_id`, `heart_rate_bpm`, `resp_rate_bpm` (always `null`), `body_temp_c` and in **all** `cabin.*` fields, without treating it as an error.
- Store each message with its `ts` in UTC and its `crew_id`, and handle duplicates (same combination of `device_id`, `ts` and `type`) by replying `200` or `409`, never another 4xx.
- Do not reject with 4xx data that is valid even if unexpected (an unassigned `crew_id`, an odd value, an extra field, an unknown `type`): any 4xx other than `401`, `403`, `408`, `409` or `429` makes the ESP32 **drop the message**. Store it and flag it. Use `401` only for a bad key and `400` only for broken JSON. If you need to rate-limit, reply `429`, which is retried.
- Answer `GET /` without requiring `X-API-Key` and with a `Date` header (almost all servers add it on their own). This is how the ESP32 gets the time without Internet.
- Read "number" fields as a number, whether integer or decimal (`23` or `23.0`).
- Serve the latest state of each crew member: `GET /api/v1/crew/{crew_id}/latest`.
- Associate `crew_id` (RFID UID) with a name and role; an unknown UID is stored anyway and marked as unassigned.
- Decide what to do with telemetry whose `crew_id` is `null` (vitals that belong to nobody): store it separately or do not show it under any crew member.
- Serve the history: `GET /api/v1/crew/{crew_id}/telemetry?from=&to=`.
- Serve the events, filterable: `GET /api/v1/events?crew_id=&type=`.
- Infer the start and end of each alert by comparing consecutive telemetry messages, and notify the dashboard in real time (WebSocket or SSE) when an alert starts or an event arrives.
- Store the alert thresholds as editable configuration, with the values in the alert codes table as a starting point.
- If ranges are validated, do so at least with these margins, which the firmware already guarantees: pulse 35–200, `hr_quality` 0–1, body temperature 30–45 °C, humidity 0–100 %. It is better to flag the value as suspicious than to reply `422`, because `422` loses the whole message. Breathing is no longer validated.
- Allow CORS for the dashboard origin.

## JSON Schema

They describe exactly what the firmware sends (draft 2020-12). They are strict (`additionalProperties: false`) to pin down the format; in the backend it is better not to reject over an extra field, as noted in the list above.

Telemetry (`POST /api/v1/telemetry`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "astromed/telemetry.schema.json",
  "title": "AstroMed telemetry",
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

Events (`POST /api/v1/events`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "astromed/event.schema.json",
  "title": "AstroMed event",
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

JSON Schema cannot compare two fields, so `still_for_s ≥ threshold_s` in `inactivity` is documented only in the `data` table.

## Limits

No measurement is medical grade: this is a demo with sensors from an educational kit.

- **Pulse:** the photoresistor is slow and noisy, which is why `hr_quality` exists and the pulse goes to `null` when the signal is bad.
- **Breathing:** not measured.
- **Motion:** there is only a tilt switch; a crew member who moves without tilting it counts as still.
- **Push-ups:** counts correctly if the chest passes right above the sensor; partial push-ups may not count.
- **Body temperature:** only reliable if the thermistor is calibrated against a clinical thermometer.
- **Cabin:** the DHT11 has ±2 °C and ±5 % humidity error; the dew point and heat index inherit that error.
- **Thresholds:** the alert thresholds are demo values, not clinical.
