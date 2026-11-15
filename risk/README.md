# AstroMed · Team Antares: risk engine

The risk engine used by the API (`api/`).

The engine is a pure Python function: no network, no database and no external dependencies. The shared configuration lives in `astromed_config.py`. The API imports it and calls it inside its own process. Python 3.11 or later.

```python
from risk import evaluate
```

## Summary in one table

| | What | Detail |
|---|---|---|
| **You send** | `telemetry` | ① telemetry messages from the **last minute** |
| | `events` | ① events from the **last 7 days** |
| | `manual_checks` | ② checks from the **last 7 days** |
| | `now` | `datetime.now(timezone.utc)` |
| **You get back** | a `dict` | The ③ assessment, like `contracts/assessment.example.json` |

All the texts it returns (reasons, recommendations, summary) are **in English**, because the project is presented in English.

Everything is for **a single `crew_id`**, as dicts with the same JSON that reached the API. You do not need to sort them: the engine sorts by `ts`.

## 1. What you send

### When to call it

Every time you store a message from a crew member with a `crew_id`: telemetry (every 2 s on the current board), an event or a manual check. If `crew_id` is `null` (nobody has swiped a card), store the message but do not call the engine.

### How much history

| List | Window | Why |
|---|---|---|
| `telemetry` | Last minute (about 30 messages from the current board) | The engine discards telemetry older than 60 s: a pulse from 10 minutes ago is no longer valid. Sending more breaks nothing, it is just slower |
| `events` | Last 7 days | Push-ups are compared with the crew member's own 7-day average, and they appear in the trend |
| `manual_checks` | Last 7 days | Today's level uses the checks from the last 24 h; the trend uses those from 7 days |

**Important:** store the `ts` that comes in the message, not the time it reached the API. The trend and the push-up baseline are computed with that `ts`. The simulator sends history with past dates, and the board resends late messages when the connection recovers.

### Example in an endpoint

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

`db.telemetry`, `db.events` and `db.checks` are examples: how you read the database is up to you. Each returns a list of dicts.

`evaluate()` does not raise exceptions on missing, incomplete or garbage data (text where a number goes, lists, `null`...): that counts as "no data". Even so, wrap it in a `try` so that an engine failure never takes down the endpoint that stores the data.

Two details:

- **`now` must carry a timezone:** `datetime.now(timezone.utc)`. With a naive `datetime.now()`, the engine raises `ValueError`. If it accepted it, in UTC+1 all telemetry would look an hour old and everything would come out as "no data".
- **Duplicates:** the engine counts messages with the same `(device_id, ts, type)` only once, which is what the board repeats on retries. Even so, avoid storing them twice.

## 2. What you get back

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

| Field | What it is | Watch out for |
|---|---|---|
| `overall_level` | The worst of the 4 systems: 0 green, 1 amber, 2 orange, 3 red | **Can be `null`** if there is no data at all |
| `systems.*.level` | Level of each system | **Can be `null`**: the web app paints it gray, "no data", never green |
| `systems.*.reasons` | Reasons **in English**, the most severe first and then the "no data" ones | |
| `trends` | One line per indicator: check, push-ups and sensor (section 5) | Only those with **at least 7 measurements** appear |
| `trends[].crosses_in` | Measurements (`basis: "count"`) or seconds (`"time"`) until the next threshold is crossed | `null` if it is not crossed within the horizon |
| `recommendations` | **In English**: first the level's action, then the countermeasures and trend warnings | |
| `earth_summary` | English text ready to send to the doctors on Earth | Only at level 3; otherwise `null` |

The four systems are laid out like this in the web app: `cardiovascular`, `neuro` and `musculoskeletal` go on the crew member's figure; `environment`, on the cabin.

## 3. Rules that avoid false alarms

In addition to the thresholds in `thresholds.json`, the engine applies these rules. They do not change the ③ contract: they only decide the level and add a note at the end of the reason, in English. All of them are **team criterion** and are tuned in `thresholds.json` (`rules_source` explains each one).

| Rule | What it does | Why | Setting |
|---|---|---|---|
| **Sustained pulse and temperature** | Orange or red only if **at least 3 consecutive readings spanning 10 s** are at that level or worse. Until then, any high reading gives **amber, never green**: `(not sustained yet: 1 of 3 readings)`. Mixed high and low readings give amber with `(inconsistent readings; check the sensor)` | The photoresistor is noisy and the thermistor can come loose. The pulse uses overlapping 10 s windows. Both the current board and the simulator send every 2 s, so at least 6 readings are needed to cover 10 s between the first and the last (3 readings would span only 4 s). A lone spike must not call Earth, but a sensor failure must not hide a real problem either | `sustain_readings` and `sustain_seconds` in `heart_rate_bpm` and `body_temp_c` |
| **Pulse after exercise** | If the latest message says `activity: "moving"`, or there was a set of push-ups in the last 5 min, a high pulse at **orange** drops to amber: `(after exercise; recheck at rest)`. Red (above 150 bpm) and a low pulse are not downgraded | A raised pulse from effort is normal, but above 150 is no longer explained by a few push-ups | `heart_rate_bpm.exercise_recovery_s` |
| **Wrist temperature** | A **low** temperature gives at most amber: `(wrist reading; confirm with a thermometer)`. A high one (fever) keeps orange and red | The thermistor sits on the wrist, and the skin cools several degrees with the surroundings even if the crew member is fine (Polar white paper, cited in `thresholds.json`). A cold wrist calls for a thermometer, not for calling Earth | `body_temp_c.low_max_level` |
| **Previous crew member's set** | A set of push-ups that arrives up to 3 s after a `crew_checkin` `in` is ignored | If a card is swiped in the middle of a set, the board sends the summary with the `crew_id` of the person arriving, but the push-ups belong to the previous one and would lower the new one's baseline | Fixed, 3 s |
| **Blood pressure across days** | Orange needs two consecutive readings at orange or worse. The latest must be from the last 24 h; the previous one can be from any of the 7 days | The team guide says "140/90 on two readings", and during the mission it is measured once a day. Before, yesterday's reading (25 h ago) did not count | 7-day window |
| **Mood against own average** | Amber if today's mood is **1.5 points or more** below the crew member's own average over the previous 7 days, with at least 3 previous checks. It is added to the fixed cut (below 3) | A 3/5 is normal for someone who is usually at 3, but it is a clear drop for someone who is always at 5 | `mood.personal_drop`, `mood.personal_min_checks` |

Consequence for the demo: the simulator (`simulator/config.json`) sets the second crew member (`336F8312`) to level 2, so by default it reaches **orange** (pulse about 114 bpm, 38.6 °C) once the 10 s sustain window is covered. It only reaches **red** when run with a level-3 override, for example `python -m simulator.simulate --level 336F8312=3` (pulse 160 bpm, 39.8 °C), again after at least 6 readings at 2 s.

## 4. Demo mode

Start the API with the environment variable `ASTROMED_DEMO=1`. That way the amber for inactivity fires at 30 s instead of 600 s, just like the board's `inactivity` event.

**Note:** the firmware is currently in demo mode (`INACTIVITY_THRESHOLD_S 30` in `firmware/uno_sensors/config.h`). With the real board, start the API with `ASTROMED_DEMO=1`; otherwise the board will report inactivity at 30 s and the engine will not paint it amber until 600 s. For real use, set both to 600 s.

```bash
ASTROMED_DEMO=1 uvicorn api.main:app --reload
```

(The `uvicorn` command is an example; use your own.)

## 5. Trend lines

Each trend is a least-squares line over the crew member's own real measurements, projected forward. It warns if the line crosses the next threshold even though today it is green. The line and the points are part of the assessment, so the web app draws them as they are, without recomputing anything.

| Data | x axis (`basis`) | Window | Projection (`horizon`) |
|---|---|---|---|
| Manual check: blood pressure, glucose, mood | Per check (`count`, `check`): the latest is 0, the previous one −1... | Last 7 days | 7 more checks |
| Push-ups (`exercise_summary`) | Per set (`count`, `set`) | Last 7 days | 7 more sets |
| Sensor: pulse, body temperature, cabin temperature, humidity | Seconds relative to now (`time`, `s`) | Last minute (about 30 readings) | 60 s |

Team criterion:

- **7 measurements are needed.** The line appears with the seventh check; the sensor line appears with 7 sensor readings (12 s at 2 s spacing).
- **Checks and sets go per measurement, not per day.** In real use there is one check per day, so 7 checks are a week. In the demo you can enter 7 checks within a few minutes and the line comes out just as well; per day, they would all fall on the same day and the slope would blow up.
- **Only the threshold in the worsening direction is monitored.** If the value is in a high band and the line goes down (or in a low band and it goes up), it is recovering: `threshold` is `null`.
- **Low body temperature:** only amber is monitored, because the engine does not raise it above amber (section 3).
- **Push-ups:** the threshold in repetitions is the baseline (average of the sets before the latest) minus the drop percentage of each level.

### Trying them out

```bash
python -m pytest -q risk/tests/test_trends.py
python -m simulator.simulate --mode normal --evaluate --fast --count 150
```

The tests check, among other things, that 7 consecutive checks give the same line as 7 checks over 7 days, that with 6 measurements there is no line, and that a pulse rising 1 bpm/s warns that it will cross 120 bpm in 12 s. The simulator's `normal` mode ramps the levels up and down, and the sensor lines detect it. See [`simulator/README.md`](../simulator/README.md).

## 6. API responses to the simulator and the board

The simulator reacts like the ESP32 (details in `contracts/README.md`):

| You respond | What it does |
|---|---|
| 2xx | Considers it sent |
| 409 | Treats it as an already stored duplicate |
| Other 4xx (400, 404, 422...) | **Drops the message**: that data is lost. The exceptions are 408 and 429, which are retried (the ESP32 also retries 401 and 403) |
| 5xx or no response | Retries at 1, 2, 4... s, up to 30 s |

That is why you should never answer 422 to a `null` field: `null`s are normal (sensor without contact, failing DHT11, respiration that is not measured). Genuinely impossible values are what 422 is for.

## Files

| File | What it does |
|---|---|
| `engine.py` | `evaluate()`: puts everything together |
| `indicators.py` | Level 0-3 for each measurement and demo mode |
| `thresholds.json` | Thresholds and extra rules; each cut cites its source |
| `trends.py` | Trend lines (section 5) |
| `recommendations.py` | Countermeasures and trend warnings |
| `summary.py` | English summary for Earth |
| `tests/` | `pytest -q` from the repo root |
