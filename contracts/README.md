# AstroMed · Team Antares: contracts

JSON examples of what is exchanged between the parts. All dates are in UTC (ISO 8601). Changing a contract needs a PR approved by whoever produces the data and whoever uses it.

The executable contracts are in `contracts/schemas.py`, with tests against all
the examples. The official API and its connection to the console are described in
[`api/README.md`](../api/README.md). The GET endpoints and the manual check are public
by team decision; the board keeps `X-API-Key` on telemetry and events.

Source of this document: the Team Antares guide and [AstroMed: JSON format for the backend](../firmware/BACKEND_JSON_FORMAT.md), checked against the firmware. If something does not match, the firmware wins.

| File | Contract | Endpoint |
|---|---|---|
| `telemetry.example.json` | ① Normal telemetry | `POST /api/v1/telemetry`, every 2 s from both the board and the simulator |
| `telemetry-no-data.example.json` | ① Telemetry with no crew member and a failing DHT11 | same |
| `event.example.json` | ① `exercise_summary` event | `POST /api/v1/events`, when it happens |
| `event-crew_checkin.example.json` | ① `crew_checkin` event | same |
| `event-inactivity.example.json` | ① `inactivity` event | same |
| `check.example.json` | ② Manual check | `POST /api/v1/checks` |
| `assessment.example.json` | ③ Risk assessment | returned by `evaluate()` |
| `ws-message.example.json` | ④ WebSocket envelope: `{"type": "assessment", "data": ...}`, where `data` is a full ③ assessment (systems, trends, recommendations, `earth_summary`) | WebSocket |

## Telemetry ①: what can arrive as `null`

| Field | When it arrives as `null` |
|---|---|
| `crew_id` | Nobody has swiped a card |
| `vitals.resp_rate_bpm` | **Always.** Respiration is not measured, but the field is kept |
| `vitals.heart_rate_bpm` | When `hr_quality` is below 0.4 |
| `vitals.body_temp_c` | Thermistor not touching the skin, or reading outside 30-45 °C |
| `cabin.*` (all five, including `condensation_risk`) | The DHT11 fails 5 times in a row |

Also:

- `hr_quality` is **always a number**, 0 when there is no signal.
- `humidity_pct` is an **integer**: the DHT11 gives no decimals.
- `motion.sleep_state` does not exist.
- `body_temp_c` already arrives as `null` outside 30-45 °C, so the API should not need to reject it with a 422.

- A number with `.0` may arrive as an integer (`23` instead of `23.0`), because of how ArduinoJson serializes. Numeric fields must be read as numbers, whether integers or decimals.
- `heart_rate_bpm`, when it has a value, is between 35 and 200.
- `motion.still_for_s` is 0 with `activity: "moving"` and 3 or more with `"still"`.

Possible local alerts in `alerts`, always in this order and without repeats: `HR_HIGH`, `HR_LOW`, `BODY_TEMP_HIGH`, `BODY_TEMP_LOW`, `CABIN_TEMP_HIGH`, `CABIN_TEMP_LOW`, `HEAT_INDEX_HIGH`, `CONDENSATION_HIGH`. `RESP_HIGH` and `RESP_LOW` never arrive. They use the firmware's demo thresholds (pulse > 120 or < 45, body temperature > 38.0 or < 35.5 °C, cabin > 28 or < 18 °C, heat index > 32 °C). The official levels come from the engine, not from these alerts.

Kit cards (the UID is the `crew_id`): `F3786E09` (crew member 1) and `336F8312` (crew member 2).

## Events ①: there are only three types

| `type` | `severity` | `data` | Details |
|---|---|---|---|
| `crew_checkin` | `info` | `action`: `in` or `out` | When the card changes, two arrive back to back: `out` for the previous one and `in` for the new one, the latter with a `ts` 1 s later so it does not count as a duplicate |
| `inactivity` | `medium` | `still_for_s`, `threshold_s` | Only with a crew member checked in, and once per period without moving. `threshold_s` is 30 in the demo and 600 in real use |
| `exercise_summary` | `info` | `exercise` (`pushup`), `reps`, `duration_s`, `cadence_rpm` | May arrive with `crew_id: null` if nobody has swiped a card |

`sleep_summary` and `reaction_test` do not exist.

## How the ESP32 reacts to API responses

| Response | What the ESP32 does |
|---|---|
| 2xx with `{"ok": true}`, no body, or a body that is not JSON | Considers it sent |
| 2xx with `{"ok": false}` | Treats it as a failure and **retries forever**: it blocks the queue. Never respond with it |
| 409 | Treats it as an already stored duplicate and does not retry. For duplicates, 200 or 409 both work |
| 401, 403, 408 or 429 | Retries. Use 429 if you need to rate limit; 401 and 403 (bad key) are retried so that no data is lost once the key is fixed |
| Other 4xx (400, 404, 422...) | Drops the message and does not retry: **that data is lost**. The API answers 422 for impossible values and 400 only for broken JSON |
| 5xx, 3xx or no response within 4 s | Retries at 1, 2, 4... s, up to 30 s, with up to 50 messages queued. It does not follow redirects |

Messages are sent in order: while the first one fails, the others wait. The `ts` does not change on retries, so duplicates are recognized by `(device_id, ts, type)`, with `type` = telemetry on `/api/v1/telemetry`.

**Time without Internet:** if there is no NTP, the ESP32 does a `GET /` to the backend and takes the time from the `Date` header. It is enough for `/` to respond with anything, even a 404; almost all servers set `Date` on their own.

## What the engine receives

`evaluate(telemetry, events, manual_checks, now)` receives lists for a single `crew_id`, so messages with `crew_id: null` do not reach it. Any `null` is treated as "no data", never as normal.

## Assessment ③: what the engine returns

| Field | What it is |
|---|---|
| `overall_level`, `systems.*.level` | 0 green, 1 amber, 2 orange, 3 red. **`null` if there is no data at all**: painted as "no data", never green |
| `systems.*.reasons` | Reasons in English, the most severe first and then the "no data" ones |
| `trends` | One line per indicator with **at least 7 measurements**: check (`systolic_mmhg`, `diastolic_mmhg`, `glucose_mg_dl`, `mood`), sets (`pushup_reps`) and sensor (`heart_rate_bpm`, `body_temp_c`, `cabin_temp_c`, `humidity_pct`) |
| `trends[].label`, `unit` | Name and unit in English, for the web app |
| `trends[].basis`, `x_unit` | `"count"` with `x_unit` `"check"` or `"set"`: x is the measurement number (the latest is 0, the previous −1...). `"time"` with `"s"`: x is the seconds relative to `ts` |
| `trends[].points` | The measurements used in the line, `[[x, value], ...]` |
| `trends[].slope`, `intercept` | Line `value = intercept + slope · x` (slope per `x_unit`) |
| `trends[].horizon`, `projected` | How far ahead it is projected (7 measurements or 60 s) and the line's value there |
| `trends[].threshold`, `threshold_level` | Next threshold in the worsening direction, and the level it would lead to. `null` if the line heads toward normal or no thresholds are left |
| `trends[].crosses_in` | Measurements or seconds until it is crossed, or `null` if it is not crossed within the horizon |
| `recommendations` | In English: the level's action, countermeasures and trend warnings |
| `earth_summary` | English text ready to send to the doctors on Earth. Only if `overall_level` is 3; otherwise `null` |

For trends to exist, the API has to pass the engine the checks and events from **the last 7 days** and the telemetry from the last minute (about 30 readings at 2 s).

**Demo mode:** with the environment variable `ASTROMED_DEMO=1` in the API process, the amber for inactivity fires at 30 s instead of 600 s, just like the board's `inactivity` event in the demo.
