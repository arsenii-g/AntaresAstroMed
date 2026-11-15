# AstroMed Console · Team Antares

The final AstroMed interface, built by Team Antares and integrated with the API.
It includes the landing page, the interactive body, the charts, and the daily check.
It has two pages: the landing page (`index.html`) and the console (`console.html`),
reached with *Open the console*. It is plain HTML, CSS, and JavaScript, with no
dependencies and no build step. Fonts fall back to system fonts when offline.

## How to view it

From the repository root, with the Python dependencies installed:

```bash
python -m uvicorn api.main:app --env-file .env.example --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000/console.html>. The API also serves the web pages on the
same origin and port. Setup for Windows/macOS/Linux is in the root README.
You can also run a separate server on port 5173:

```bash
python -m http.server 5173 --directory frontend/web
```

On port 5173 the console looks for the API on the same computer, port 8000 by
default. If it is on another machine, use `console.html?api=http://IP:8000`. Add
`&crew=F3786E09` to select a profile on open. GET requests and the daily check do
not need an API key.

The console uses `/api/v1/crew` to discover profiles and `/api/v1/crew/active` to
recover the active tap on load and on reconnect. `latest` returns the status, name,
and latest exercise set; `telemetry`, `checks`, and `events` provide the history.
The `/ws` WebSocket receives `telemetry`, `event`, and `assessment`.
`POST /api/v1/checks` produces a new assessment. If the link drops, *NO LINK TO BASE*
appears and the console reconnects after 1, 2, 4… s, up to 30 s. Every 15 s it
queries the status again so that old measurements expire.

## What is here

| File | What it is |
|---|---|
| `index.html` | Landing page: planet, three-step explanation, and a button to the console |
| `landing.css`, `js/landing.js` | Landing page styles and animations |
| `console.html` | The console, with two views. **Monitor**: crew, systems, body, vital signs, and cabin (with dew point, heat index, condensation risk, and board alerts), trends, actions, Earth summary, event log, and sensor status. **Daily check**: the form for contract ② |
| `js/trendchart.js` | Chart for one trend: draws the points, the line, the projection, and the threshold the engine sends, without copying thresholds or recomputing anything |
| `styles.css` | Console styles. Colors, fonts, and levels are variables at the top |
| `js/app.js` | Receives `{ type, data }` messages and renders them. It also keeps the event log (level changes per system), the alert with its *Acknowledge* button, and the data age |
| `js/hologram.js` | 3D dot body made of rounded cylinders, colored per system; click and rotate it |
| `js/planet.js` | 3D planet: landing page background and the *Vehicle link* panel in the console (changes with its options) |
| `js/stage.js` | Draw loop shared by the two canvases |

Levels are painted with the `data-level` attribute (`0` green, `1` amber, `2` orange, `3` red, empty = gray "No data"). A `null` level is never painted green.

Design decisions that can be adjusted in `js/app.js`:

- **Stale data** (`STALE_S = 15`): the measurement time is used, including for retries.
  After 15 s, the vital signs turn gray and the link reads *NO SIGNAL*.
- **No technical details on screen**: the console is for the crew, so it does not show endpoints, JSON, or where the data comes from. It only says whether sensor readings are arriving.
- **Alert**: shown for level 2 or 3. *Acknowledge* hides it only on that screen and records it in the log; it reappears if the level or the reason changes. It is not sent to the API.

## Integration behavior

- **Follow sensor:** follows RFID taps and recovers the state on reload. Telemetry
  only selects a crew member when none is selected, because with two boards at once
  it would switch every 2 s. Selecting a profile manually stops following the card
  until the button is pressed.
- **Daily check:** three steps (mood, blood pressure, and glucose), with the option to
  skip anything not measured and with range validation. On saving, it returns to the
  monitor with the updated assessment. Switching crew member clears the form so that
  answers are not attributed to the previous one.
- **Charts:** the live curves join measurements by their `ts`, deduplicate, and leave
  gaps when the signal is missing. Trend charts appear with 7 measurements and draw
  exactly the points and line from `trends` (checks and sets: per measurement;
  sensor: last minute, in seconds).
- **Log:** retrieves the events stored by the API. Acknowledgments and level changes
  observed in this console remain local to that page.
- **Earth summary:** only the selected crew member's summary is shown, and it can be
  copied. It is not transmitted to any external service, and nothing claims that
  anyone was notified.

Tests for the data utilities, with Node 20 or later and no packages to install:

```bash
node --test frontend/web/tests/*.test.js
```

The text on the page and in the sample data is made up, except for field names, which come from `contracts/`.
