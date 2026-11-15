# AstroMed · Team Antares: two-ESP32 simulator

Simulates **two ESP32 boards, one per crew member**. They send the API exactly what the real board sends: the same JSON every 2 s, with the same queue and the same retries. The API stores the messages, calls the risk engine, and notifies the web app over WebSocket. Nothing is calculated in the simulator or the web app: the levels, reasons, and trendlines all come from the engine.

The **manual check** (blood pressure, glucose, and mood) is not simulated. Enter it by hand in the *Daily check* tab. Until the first check, the neurobehavioral system shows *No data*.

## Getting started

1. Start the API from the repository root (see the root README):

   ```bash
   python -m uvicorn api.main:app --env-file .env.example --host 0.0.0.0 --port 8000
   ```

2. In another terminal, also from the root:

   ```bash
   python -m simulator.simulate
   ```

3. Open <http://localhost:8000/console.html>.

To record from scratch without losing earlier data, set a new path in `.env`, for example `ASTROMED_DATABASE_URL=sqlite:///./astromed-recording.db`, and start the API with `--env-file .env`. Without an explicit URL, the API reuses `spacehealth.db` if it exists and creates `astromed.db` on new installations. Checks and the last 7 days of series are kept between runs.

`Ctrl+C` stops the simulator and sends the exit `crew_checkin` for both crew members.

## `config.json`

```json
{
  "api_url": "http://localhost:8000",
  "api_key": "spacehealth-dev-key-2026",
  "mode": "fixed",
  "interval_s": 2,
  "pushup_every_s": 20,
  "crew": [
    { "crew_id": "F3786E09", "device_id": "esp32-sim-1", "level": 0 },
    { "crew_id": "336F8312", "device_id": "esp32-sim-2", "level": 2 }
  ]
}
```

| Field | What it does |
|---|---|
| `api_url`, `api_key` | Where to send and which `X-API-Key` to use. The key must match the API's (`ASTROMED_API_KEY`) |
| `mode` | `"fixed"`: each crew member stays at their level. `"normal"`: each system's level changes on its own |
| `interval_s` | How often telemetry is sent (the real board: 2 s) |
| `pushup_every_s` | How often a set of push-ups is performed |
| `crew[].level` | Level 0, 1, 2, or 3 for everything, or one per system: `{"cardiovascular": 3, "musculoskeletal": 0, "environment": 1}` |
| `normal` | Settings for normal mode (below) |

The order of `crew` matters: the web app follows the last card checked in, which is the last one in the list.

Without editing the file:

```bash
python -m simulator.simulate --level F3786E09=1 --level 336F8312=3
python -m simulator.simulate --mode normal
python -m simulator.simulate --url http://192.168.137.1:8000
```

## What is sent at each level (`fixed` mode)

The values sit in the middle of each band in `risk/thresholds.json`, with some noise, so that the noise does not change the level.

| System | Level 0 | Level 1 | Level 2 | Level 3 |
|---|---|---|---|---|
| Cardiovascular | pulse 72, 36.7 °C | pulse 108, 37.7 °C | pulse 114, **38.6 °C** | **pulse 160**, 39.8 °C |
| Musculoskeletal: push-up drop versus personal average | 0% | 15% | 30% | 50% |
| Environment: cabin | 22.5 °C, 45% | 26 °C, 52% | 29 °C, 55% | 33.5 °C, 50% |
| Neurobehavioral | manual check only | | | |

- **Cardiovascular level 2 comes from the fever, not the pulse:** the engine downgrades an orange pulse to amber for 5 minutes after push-ups, and the simulator does them every 20 s.
- **Orange and red take about 10 s:** the engine requires sustained readings (3 readings and 10 s). In the meantime the level shows amber.
- **Push-ups:** the first 3 sets are the usual ones (20) and form the baseline. From the fourth, each set drops by the level's percentage compared with the average of the previous sets, which is what the engine measures. At levels 2 and 3 the repetitions keep falling over time, because the average falls too.
- **Inactivity:** the crew member moves every 12 s, so they never reach the 30 s alert.
- **If the API already has series for that crew member** (from an earlier run), the simulator reads them at startup and uses them as the baseline, as the engine does.

## `normal` mode

Each system picks a new level every 40 to 90 s (40% green, 30% amber, 20% orange, 10% red) and ramps toward it at 20 s per level. These ramps are what the sensor trendlines detect: "Heart rate reaches 120 bpm in 14 s".

```json
"normal": { "seed": 1, "change_every_s": [40, 90], "ramp_s_per_level": 20, "level_weights": [0.4, 0.3, 0.2, 0.1] }
```

The same `seed` always produces the same sequence. Change it for a different one.

## Without the API

```bash
python -m simulator.simulate --print --count 3                  # the JSON it would send
python -m simulator.simulate --evaluate --fast --count 120      # engine levels, locally
```

## Tests

```bash
python -m pytest -q simulator
```
