# AstroMed API · Team Antares

The API validates and stores incoming messages in SQLite, calls the Python engine
`risk.evaluate()`, and publishes changes over `/ws`. It also serves the landing page
and the console from `frontend/web/`. Full setup instructions are in the root README.

## Flow

1. Validate the JSON with `contracts/schemas.py` and normalize timestamps to UTC.
2. Store the message and its idempotency receipt in a single transaction.
3. For that `crew_id`, pass the engine the last minute of telemetry and the last
   seven days of events and checks. With `crew_id: null`, store without evaluating.
4. Store the assessment and emit `telemetry` or `event`, followed by `assessment`.
   A check emits its new assessment directly.

Each message is acknowledged with `200` and `{"ok": true, "duplicate": false,
"assessment_pending": false}`. A retry is acknowledged with `duplicate: true`,
without storing or broadcasting the data again. The idempotency key is
`(device_id, ts, telemetry)` for telemetry, `(device_id, ts, type)` for events, and
`(crew_id, ts, checks)` for checks. The database guarantees that two concurrent
requests cannot create two messages.

The new `ingestion_receipts` table coexists with the four original tables. The API
also handles earlier messages that have no receipt: an existing database is never
deleted or rebuilt.

If the engine fails, the received message stays stored and the API responds
`ok: true` with `assessment_pending: true`. The exception is logged; `/latest`
retries the assessment and returns `assessment: null` plus `assessment_error` if it
keeps failing. A retry of the same message can also recover the pending assessment.

## Endpoints

| Method and path | Result |
|---|---|
| `POST /api/v1/telemetry` | ESP32 telemetry; requires `X-API-Key` |
| `POST /api/v1/events` | Board events; requires `X-API-Key` |
| `POST /api/v1/checks` | Manual check; no API key, by team decision |
| `GET /api/v1/crew` | List of stored known and unknown cards, with name, role, and `assigned` |
| `GET /api/v1/crew/active` | Latest RFID tap (`in` → that crew member, `out` → nobody); with no taps, the crew member from the latest telemetry. With several boards at once, telemetry would switch crew member every 2 s |
| `GET /api/v1/crew/{id}/latest` | Metadata, latest telemetry, assessment recomputed at the current time, and latest exercise set |
| `GET /api/v1/crew/{id}/telemetry?from=&to=&limit=` | Latest readings in the interval, returned in chronological order |
| `GET /api/v1/crew/{id}/checks?from=&to=&limit=` | Checks in the interval, for plotting the real measurements |
| `GET /api/v1/events?crew_id=&type=&from=&to=&limit=` | Filterable events, in chronological order |
| `GET /api/v1/status` | Backend status, time, and demo mode |
| `WS /ws` | Envelopes `{"type": "telemetry" / "event" / "assessment", "data": {...}}` |
| `GET /` and `GET /console.html` | Landing page and console; both include an HTTP `Date` header |

`from` and `to` are ISO 8601 timestamps with a time zone. The maximum limit is 10,000.
By default the last 3,000 telemetry readings or 1,000 events/checks are returned;
the console requests the 48 most recent telemetry readings and seven days of
checks/events.

`POST /api/v1/assessment` is kept as a legacy import route with an API key, marked
deprecated in `/docs`. Normal operation does not depend on it.

## Validation and compatibility

- Missing data is `null`, never zero or green. Complete loss of the DHT11 and the
  absence of a crew member are both accepted.
- Where appropriate, numbers may be integers or integral decimals. Booleans,
  non-finite numbers, and timestamps without a time zone are rejected.
- Extra fields and unknown cards are accepted. Future events of an unknown type are
  stored as opaque events, preserving their data.
- Physically impossible values (outside the ranges in `contracts/schemas.py`, for
  example heart rate outside 20-250 bpm or body temperature outside 30-45 °C) are
  rejected with `422`. The firmware never sends such values: the ESP32 drops 4xx
  responses, except `401`, `403`, `408`, and `429`, which it retries. Rejections on
  the authenticated routes are stored with their reason in `rejected_messages`; the
  public `/api/v1/checks` route does not store them. Malformed JSON gets `400`; a
  missing or wrong key gets `401`; a transient SQLite error gets `503`, so the sender
  retries.
- Configuration uses `ASTROMED_*` variables. For compatibility with existing setups,
  the legacy `SPACEHEALTH_*` variables are still accepted (the new ones take
  precedence) and an existing `spacehealth.db` is reused; new installs create
  `astromed.db`. `ASTROMED_DATABASE_URL` selects another location. The device API key
  is unchanged.
- A slow browser cannot block the board's acknowledgment indefinitely.

## Security notes (demo)

- The default dev API key `spacehealth-dev-key-2026` is a public placeholder, kept so
  boards that are already flashed keep working. Set `ASTROMED_API_KEY` for any real
  deployment.
- CORS defaults to `*`, and `start-demo.bat` binds `0.0.0.0`. On a shared network,
  anyone on the LAN can post data.
- `/api/v1/checks` is intentionally unauthenticated so the dashboard can submit
  daily checks.

The profiles of the kit's cards (`F3786E09` and `336F8312`) are edited in
`api/crew.py`; a new card is marked as unassigned.
