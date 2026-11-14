"""Simulador de dos ESP32 (uno por tripulante) para el vídeo.

Cada placa simulada manda lo mismo que la real, con el mismo formato y la
misma lógica de reintentos: crew_checkin al empezar, telemetría cada 2 s y
una serie de flexiones (exercise_summary) cada pushup_every_s. La API guarda
los mensajes, llama al motor de riesgos y avisa a la web por WebSocket.

El chequeo manual (tensión, glucosa y ánimo) NO se simula: se mete a mano en
la web. Por eso el sistema neuro sale "No data" hasta el primer chequeo.

Configuración: simulator/config.json (ver simulator/README.md).
    mode "fixed":  cada tripulante se queda en el nivel que pongas (0 a 3),
                   para todos los sistemas o uno por sistema.
    mode "normal": el nivel de cada sistema va cambiando solo, con rampas
                   suaves entre niveles; las rectas de tendencia lo detectan.

Uso:
    python -m simulator.simulate                         # manda a la API del config
    python -m simulator.simulate --mode normal
    python -m simulator.simulate --level F3786E09=1 --level 336F8312=3
    python -m simulator.simulate --print --count 3        # JSON por pantalla, sin API
    python -m simulator.simulate --evaluate --fast --count 60   # motor local, sin API

Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
MAX_QUEUE = 50
MAX_BACKOFF_S = 30
SYSTEMS = ("cardiovascular", "musculoskeletal", "environment")   # neuro: solo chequeo manual

# Valor de cada medida en cada nivel (0, 1, 2, 3). Están en el centro de cada
# franja de risk/thresholds.json, para que el ruido no cambie de nivel.
#   cardiovascular: el nivel 2 sale de la temperatura (fiebre, 38-39,5 °C),
#   porque el motor rebaja a ámbar un pulso naranja tras hacer flexiones.
#   environment: temperatura de cabina; la humedad se queda en 30-60 %.
#   musculoskeletal: caída de flexiones frente a la media propia (10, 20 y 40 %).
ANCHORS = {
    "hr": (72, 108, 114, 160),
    "body": (36.7, 37.7, 38.6, 39.8),
    "cabin": (22.5, 26.0, 29.0, 33.5),
    "rh": (45, 52, 55, 50),
    "drop": (0.0, 0.15, 0.30, 0.50),
}
NOISE = {"hr": 3, "body": 0.05, "cabin": 0.15, "rh": 1}
DROP_CUTS = (10, 20, 40)      # pushup_drop_pct en risk/thresholds.json
FIRST_SET_REPS = 20
BASELINE_SETS = 3             # las 3 primeras series son las de siempre: su basal
MOVE_EVERY_S = 12             # se mueve cada 12 s: nunca llega a la inactividad de 30 s


# --- física de la cabina (las mismas fórmulas que el firmware) -----------------

def dew_point_c(temp_c: float, humidity_pct: float) -> float:
    """Punto de rocío con la fórmula de Magnus (a = 17,62; b = 243,12 °C)."""
    a, b = 17.62, 243.12
    gamma = math.log(max(humidity_pct, 1) / 100) + a * temp_c / (b + temp_c)
    return round(b * gamma / (a - gamma), 1)


def heat_index_c(temp_c: float, humidity_pct: float) -> float:
    """Índice de calor de NOAA (Rothfusz). Por debajo de 26,7 °C (80 °F) o de
    40 % de humedad es igual a la temperatura, como en el firmware."""
    t = temp_c * 9 / 5 + 32
    if t < 80 or humidity_pct < 40:
        return round(temp_c, 1)
    rh = humidity_pct
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
          - 6.83783e-3 * t * t - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh
          + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)
    return round((hi - 32) * 5 / 9, 1)


def condensation_risk(margin_c: float) -> str:
    if margin_c < 2:
        return "high"
    if margin_c <= 5:
        return "medium"
    return "low"


def local_alerts(msg: dict) -> list[str]:
    """Alertas de la placa, con los umbrales de firmware/uno_sensores/config.h
    y en el mismo orden fijo. No son los niveles del motor."""
    v, c, out = msg["vitals"], msg["cabin"], []
    hr, body = v["heart_rate_bpm"], v["body_temp_c"]
    if hr is not None and hr > 120:
        out.append("HR_HIGH")
    if hr is not None and hr < 45:
        out.append("HR_LOW")
    if body is not None and body > 38.0:
        out.append("BODY_TEMP_HIGH")
    if body is not None and body < 35.5:
        out.append("BODY_TEMP_LOW")
    if c["temp_c"] is not None and c["temp_c"] > 28:
        out.append("CABIN_TEMP_HIGH")
    if c["temp_c"] is not None and c["temp_c"] < 18:
        out.append("CABIN_TEMP_LOW")
    if c["heat_index_c"] is not None and c["heat_index_c"] > 32:
        out.append("HEAT_INDEX_HIGH")
    if c["condensation_risk"] == "high":
        out.append("CONDENSATION_HIGH")
    return out


# --- niveles ---------------------------------------------------------------------

def interpolate(anchors: tuple, severity: float) -> float:
    """Valor para un nivel continuo (1,5 = a medio camino entre ámbar y naranja)."""
    s = min(3.0, max(0.0, severity))
    i = min(2, int(s))
    return anchors[i] + (anchors[i + 1] - anchors[i]) * (s - i)


class Severity:
    """Nivel de un sistema a lo largo del tiempo.

    fixed:  siempre el mismo.
    normal: cada change_every_s elige un nivel nuevo (con level_weights) y va
            hacia él a ramp_s_per_level segundos por nivel.
    """

    def __init__(self, level: float, mode: str = "fixed", rng: random.Random | None = None,
                 normal: dict | None = None):
        self.mode = mode
        self.value = float(level)
        self.target = float(level)
        self.rng = rng or random.Random(0)
        self.normal = {"change_every_s": [40, 90], "ramp_s_per_level": 20,
                       "level_weights": [0.4, 0.3, 0.2, 0.1], **(normal or {})}
        self.next_change = self._wait()

    def _wait(self) -> float:
        lo, hi = self.normal["change_every_s"]
        return self.rng.uniform(lo, hi)

    def step(self, dt: float) -> float:
        if self.mode != "normal":
            return self.value
        self.next_change -= dt
        if self.next_change <= 0:
            self.target = float(self.rng.choices(range(4), weights=self.normal["level_weights"])[0])
            self.next_change = self._wait()
        rate = dt / max(1e-9, self.normal["ramp_s_per_level"])
        if self.value < self.target:
            self.value = min(self.target, self.value + rate)
        elif self.value > self.target:
            self.value = max(self.target, self.value - rate)
        return self.value


def drop_level(drop_pct: float) -> int:
    return sum(1 for cut in DROP_CUTS if drop_pct > cut)


def next_reps(previous: list[int], drop: float, rng: random.Random) -> int:
    """Repeticiones de la serie siguiente para que el motor vea la caída
    `drop` frente a la media de las series anteriores (su basal)."""
    if len(previous) < BASELINE_SETS:
        return FIRST_SET_REPS + (rng.choice((-1, 0, 1)) if previous else 0)
    baseline = sum(previous) / len(previous)
    if drop <= 0.05:
        # Nivel 0: oscila alrededor de su número de siempre, sin ir a la deriva.
        usual = round(sorted(previous)[len(previous) // 2])
        return max(1, usual + rng.choice((-1, 0, 0, 0, 1)))
    target = baseline * (1 - drop)
    want = drop_level(drop * 100)
    candidates = sorted({max(1, math.floor(target)), max(1, math.ceil(target))})
    same = [r for r in candidates if drop_level((baseline - r) / baseline * 100) == want]
    return min(same or candidates, key=lambda r: abs((baseline - r) / baseline - drop))


# --- una placa simulada ------------------------------------------------------------

@dataclass
class Device:
    crew_id: str
    device_id: str
    levels: dict                       # sistema -> Severity
    rng: random.Random
    interval_s: float = 2
    pushup_every_s: float = 20
    reps: list = field(default_factory=list)
    elapsed: float = 0.0
    last_move: float = 0.0
    next_pushup: float = 6.0           # el motor ignora las series de los 3 s siguientes a un fichaje

    def checkin(self, ts: datetime, action: str = "in") -> dict:
        return self._event(ts, "crew_checkin", "info", {"action": action})

    def tick(self, ts: datetime) -> tuple[list[dict], dict]:
        """Eventos y telemetría de este instante; luego avanza interval_s."""
        s = {name: sev.step(self.interval_s if self.elapsed else 0) for name, sev in self.levels.items()}
        events = []
        if self.elapsed >= self.next_pushup:
            reps = next_reps(self.reps, interpolate(ANCHORS["drop"], s["musculoskeletal"]), self.rng)
            self.reps.append(reps)
            duration = max(1, round(reps * 2.0))
            events.append(self._event(ts, "exercise_summary", "info", {
                "exercise": "pushup", "reps": reps, "duration_s": duration,
                "cadence_rpm": round(reps * 60 / duration, 1)}))
            self.next_pushup += self.pushup_every_s
            self.last_move = self.elapsed
        elif self.elapsed - self.last_move >= MOVE_EVERY_S:
            self.last_move = self.elapsed

        telemetry = self._telemetry(ts, s)
        self.elapsed += self.interval_s
        return events, telemetry

    def _telemetry(self, ts: datetime, s: dict) -> dict:
        noisy = lambda key, sev: interpolate(ANCHORS[key], sev) + self.rng.uniform(-NOISE[key], NOISE[key])
        hr = int(round(noisy("hr", s["cardiovascular"])))
        body = round(noisy("body", s["cardiovascular"]), 1)
        temp = round(noisy("cabin", s["environment"]), 1)
        rh = int(round(noisy("rh", s["environment"])))                      # el DHT11 da enteros
        dew = dew_point_c(temp, rh)
        still = self.elapsed - self.last_move
        msg = {
            "device_id": self.device_id,
            "ts": iso(ts),
            "met_s": int(self.elapsed),
            "crew_id": self.crew_id,
            "vitals": {"heart_rate_bpm": max(35, min(200, hr)), "hr_quality": round(self.rng.uniform(0.7, 0.95), 2),
                       "resp_rate_bpm": None, "body_temp_c": body if 30 <= body <= 45 else None},
            "motion": {"activity": "moving", "still_for_s": 0} if still < 3
                      else {"activity": "still", "still_for_s": int(still)},
            "cabin": {"temp_c": temp, "humidity_pct": rh, "dew_point_c": dew,
                      "heat_index_c": heat_index_c(temp, rh), "condensation_risk": condensation_risk(temp - dew)},
            "alerts": [],
        }
        msg["alerts"] = local_alerts(msg)
        return msg

    def _event(self, ts: datetime, kind: str, severity: str, data: dict) -> dict:
        return {"device_id": self.device_id, "ts": iso(ts), "crew_id": self.crew_id,
                "type": kind, "severity": severity, "data": data}


def build_devices(config: dict) -> list[Device]:
    mode = config.get("mode", "fixed")
    if mode not in ("fixed", "normal"):
        raise ValueError(f'mode must be "fixed" or "normal", not {mode!r}')
    normal = config.get("normal", {})
    seed = normal.get("seed", 1)
    devices = []
    for i, crew in enumerate(config["crew"]):
        rng = random.Random(f"{seed}-{crew['crew_id']}")
        level = crew.get("level", 0)
        per_system = level if isinstance(level, dict) else {name: level for name in SYSTEMS}
        for name in SYSTEMS:
            value = per_system.get(name, 0)
            if value not in (0, 1, 2, 3):
                raise ValueError(f"{crew['crew_id']}: level of {name} must be 0, 1, 2 or 3, not {value!r}")
        levels = {name: Severity(per_system.get(name, 0), mode, random.Random(f"{seed}-{crew['crew_id']}-{name}"), normal)
                  for name in SYSTEMS}
        devices.append(Device(crew["crew_id"], crew.get("device_id", f"esp32-sim-{i + 1}"), levels, rng,
                              config.get("interval_s", 2), config.get("pushup_every_s", 20)))
    return devices


# --- envío a la API (misma lógica que el ESP32) --------------------------------------

class Sender:
    """Cola de envío con la misma lógica de reintentos que el ESP32: 2xx y 409
    dan el mensaje por enviado; 2xx con {"ok": false}, 408, 429, 3xx, 5xx o sin
    respuesta en 4 s reintentan a 1, 2, 4… s hasta 30 s; otro 4xx lo descarta."""

    def __init__(self, url: str, api_key: str | None, timeout: float = 4.0, sleep=time.sleep):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.sleep = sleep
        self.queue: deque[tuple[str, dict]] = deque(maxlen=MAX_QUEUE)
        self.stats = {"sent": 0, "duplicate": 0, "dropped": 0, "retries": 0}

    def push(self, path: str, body: dict) -> None:
        self.queue.append((path, body))

    def flush(self, deadline_s: float = MAX_BACKOFF_S) -> None:
        while self.queue:
            path, body = self.queue[0]
            if self._post_with_backoff(path, body, deadline_s) is None:
                return
            self.queue.popleft()

    def _post_with_backoff(self, path: str, body: dict, deadline_s: float) -> int | None:
        wait, waited = 1, 0
        while True:
            status = self._post(path, body)
            if status is not None and 200 <= status < 300:
                self.stats["sent"] += 1
                return status
            if status == 409:
                self.stats["duplicate"] += 1
                return status
            if status is not None and 400 <= status < 500 and status not in (408, 429):
                self.stats["dropped"] += 1
                print(f"[sim] {path} → {status}: message dropped", file=sys.stderr)
                return status
            if waited + wait > deadline_s:
                return None
            self.stats["retries"] += 1
            self.sleep(wait)
            waited += wait
            wait = min(wait * 2, MAX_BACKOFF_S)

    def _post(self, path: str, body: dict) -> int | None:
        req = urllib.request.Request(
            self.url + path, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json",
                     **({"X-API-Key": self.api_key} if self.api_key else {})},
        )
        try:
            with _NO_REDIRECTS.open(req, timeout=self.timeout) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as err:
            return err.code
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError):
            return None
        try:
            reply = json.loads(raw) if raw else None
        except ValueError:
            reply = None
        if isinstance(reply, dict) and "ok" in reply and reply["ok"] is not True:
            return 500
        return status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_NO_REDIRECTS = urllib.request.build_opener(_NoRedirect)


def previous_sets(url: str, crew_id: str, now: datetime) -> list[int]:
    """Series de flexiones que la API ya tiene de los últimos 7 días. El motor
    las usa como basal, así que el simulador también, para que la caída sea
    la del nivel elegido aunque se arranque varias veces seguidas."""
    query = urllib.parse.urlencode({"crew_id": crew_id, "type": "exercise_summary",
                                    "from": iso(now - timedelta(days=7))})
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/v1/events?{query}", timeout=4) as resp:
            rows = json.loads(resp.read())
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError, ValueError):
        return []
    return [r["data"]["reps"] for r in rows if isinstance(r.get("data", {}).get("reps"), int)]


# --- bucle principal -------------------------------------------------------------------

def load_config(path: str | Path = CONFIG_PATH, overrides: argparse.Namespace | None = None) -> dict:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if overrides is None:
        return config
    if overrides.mode:
        config["mode"] = overrides.mode
    for item in overrides.level or []:
        crew_id, _, value = item.partition("=")
        crew = next((c for c in config["crew"] if c["crew_id"] == crew_id), None)
        if crew is None or not value.isdigit():
            sys.exit(f"--level needs CREW_ID=LEVEL with a crew_id from the config, not {item!r}")
        crew["level"] = int(value)
    if overrides.url:
        config["api_url"] = overrides.url
    if overrides.api_key:
        config["api_key"] = overrides.api_key
    return config


def run(args: argparse.Namespace) -> None:
    config = load_config(args.config, args)
    devices = build_devices(config)
    interval = config.get("interval_s", 2)
    offline = args.print or args.evaluate
    sender = None if offline else Sender(config["api_url"], config.get("api_key"))
    start = datetime.now(timezone.utc).replace(microsecond=0)
    if args.fast and args.count:
        start -= timedelta(seconds=args.count * interval)
    local = {d.crew_id: {"telemetry": [], "events": []} for d in devices}

    if sender:
        for d in devices:
            d.reps = previous_sets(config["api_url"], d.crew_id, start)
    print(f"[sim] mode={config.get('mode', 'fixed')} → "
          + ("print" if args.print else "local engine" if args.evaluate else config["api_url"]), file=sys.stderr)
    for d in devices:
        print(f"[sim] {d.crew_id} ({d.device_id}): " + ", ".join(
            f"{k}={v.value:g}" for k, v in d.levels.items()) + " · neuro: manual check", file=sys.stderr)

    def emit(path, msg, crew_id):
        if sender:
            sender.push(path, msg)
        elif args.print:
            print(json.dumps(msg, ensure_ascii=False), flush=True)
        else:
            local[crew_id]["events" if path.endswith("events") else "telemetry"].append(msg)

    # Fichaje: uno tras otro, 1 s de diferencia. La web sigue al último.
    for i, d in enumerate(devices):
        emit("/api/v1/events", d.checkin(start + timedelta(seconds=i)), d.crew_id)
    if sender:
        sender.flush()

    tick = 0
    clock0 = time.monotonic()
    try:
        while args.count is None or tick < args.count:
            # Con --fast, después de los fichajes (uno por segundo).
            now = (start + timedelta(seconds=len(devices) + tick * interval) if args.fast
                   else datetime.now(timezone.utc).replace(microsecond=0))
            for d in devices:
                events, telemetry = d.tick(now)
                for ev in events:
                    emit("/api/v1/events", ev, d.crew_id)
                emit("/api/v1/telemetry", telemetry, d.crew_id)
            if sender:
                sender.flush()
            if args.evaluate:
                for d in devices:
                    print(summary_line(d, local[d.crew_id], now), flush=True)
            tick += 1
            if not args.fast and (args.count is None or tick < args.count):
                # Ritmo fijo, como la placa: el tiempo de envío no retrasa el siguiente.
                time.sleep(max(0.0, clock0 + tick * interval - time.monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        if sender:
            ts = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=1)
            for d in devices:
                sender.push("/api/v1/events", d.checkin(ts, "out"))
            sender.flush(deadline_s=4)
            print(f"\n[sim] {sender.stats}", file=sys.stderr)


def summary_line(device: Device, history: dict, now: datetime) -> str:
    """Niveles que daría el motor con lo enviado, como los vería la web."""
    from risk import evaluate   # import tardío: el simulador no depende del motor

    recent = [m for m in history["telemetry"] if now - parse(m["ts"]) <= timedelta(seconds=60)]
    result = evaluate(recent, history["events"], [], now)
    t = history["telemetry"][-1]
    names = {"cardiovascular": "cardio", "neuro": "neuro", "musculoskeletal": "muscle", "environment": "cabin"}
    levels = " ".join(f"{names[k]}={_lvl(s['level'])}" for k, s in result["systems"].items())
    line = (f"{iso(now)[11:19]} {device.crew_id} hr={t['vitals']['heart_rate_bpm']} "
            f"temp={t['vitals']['body_temp_c']} cabin={t['cabin']['temp_c']}°C/{t['cabin']['humidity_pct']}% "
            f"reps={device.reps[-1] if device.reps else '—'} → overall={_lvl(result['overall_level'])} {levels}")
    for tr in result["trends"]:
        if tr["crosses_in"] is not None:
            unit = "s" if tr["basis"] == "time" else f" {tr['x_unit']}s"
            line += f"\n    trend: {tr['indicator']} reaches {tr['threshold']} in {tr['crosses_in']}{unit}"
    return line


def _lvl(level) -> str:
    return "—" if level is None else str(level)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AstroMed: two simulated ESP32 boards")
    p.add_argument("--config", default=str(CONFIG_PATH), help="config file (default: simulator/config.json)")
    p.add_argument("--mode", choices=("fixed", "normal"), help="override the mode in the config")
    p.add_argument("--level", action="append", metavar="CREW_ID=LEVEL",
                   help="override one crew member's level (0-3) for every system; repeatable")
    p.add_argument("--url", help="override api_url")
    p.add_argument("--api-key", help="override api_key")
    p.add_argument("--count", type=int, help="number of telemetry sends per board (default: until Ctrl+C)")
    p.add_argument("--fast", action="store_true", help="do not wait; timestamps still advance interval_s")
    p.add_argument("--print", action="store_true", help="print the JSON instead of sending it")
    p.add_argument("--evaluate", action="store_true", help="run the local engine instead of the API and print levels")
    return p.parse_args(argv)


if __name__ == "__main__":
    run(parse_args())
