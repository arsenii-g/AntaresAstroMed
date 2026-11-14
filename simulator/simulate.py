"""Simulador del ESP32: genera telemetría ① y eventos ① como los manda la placa.

Sirve para probar la API, el motor y el frontend sin hardware.

Uso:
    python -m simulator.simulate                        # JSON por pantalla, cada 5 s
    python -m simulator.simulate --scenario empeora --fast --evaluate
    python -m simulator.simulate --url http://localhost:8000 --api-key demo

Escenarios:
    sano      constantes normales, cabina en rango.
    empeora   en 5 minutos sube el pulso, la temperatura corporal y la cabina
              se calienta y humedece, hasta pasar por ámbar, naranja y rojo.
    sin-datos sin tripulante fichado y el DHT11 fallando: todo llega null.
    demo      sigue el guion de la demo (guía, sección 10) en 2 minutos:
              ficha el tripulante, se queda quieto hasta dar ámbar por
              inactividad, hace flexiones y vuelve a verde, y a los 100 s
              ficha un segundo tripulante con el pulso en rojo. Activa
              SPACEHEALTH_DEMO=1 (inactividad a 30 s).

Con --history-days N genera antes N días de chequeos manuales y series de
flexiones (sano: estables; empeora y demo: van a peor) para que se vean las
tendencias a 7 días.

Con --url se comporta como el ESP32 ante las respuestas de la API
(contracts/README.md): 2xx y 409 dan el mensaje por enviado, otro 4xx lo
descarta y 5xx o sin respuesta reintenta a 1, 2, 4… s hasta 30 s, con hasta
50 mensajes en cola.

Solo usa la biblioteca estándar.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone

DEVICE_ID = "esp32-sim"
CREW_ID = "F3786E09"
INTERVAL_S = 5            # la placa manda telemetría cada 5 s
WORSEN_TICKS = 60         # "empeora" llega al peor punto en 60 envíos (5 min)
PUSHUP_EVERY = 24         # una serie de flexiones cada 2 min
MAX_QUEUE = 50
MAX_BACKOFF_S = 30

SCENARIOS = ("sano", "empeora", "sin-datos", "demo")

# Guion de la demo, en envíos de 5 s (criterio propio, ajustado a la sección 10 de la guía).
DEMO_CREW_B = "C42A9B17"
DEMO_CHECKIN_TICK = 3        # 15 s: "Identificación"
DEMO_PUSHUP_TICK = 15        # 75 s: "Contramedida verificada"
DEMO_MOVING_TICKS = 4        # se mueve 20 s tras las flexiones
DEMO_SWITCH_TICK = 20        # 100 s: "Escalado", segundo perfil en rojo
DEMO_INACTIVITY_S = 30       # threshold_s del evento inactivity en la demo


# --- física de la cabina ------------------------------------------------------

def dew_point_c(temp_c: float, humidity_pct: float) -> float:
    """Punto de rocío con la fórmula de Magnus (a = 17,62; b = 243,12 °C)."""
    a, b = 17.62, 243.12
    gamma = math.log(humidity_pct / 100) + a * temp_c / (b + temp_c)
    return round(b * gamma / (a - gamma), 1)


def heat_index_c(temp_c: float, humidity_pct: float) -> float:
    """Índice de calor de NOAA (ecuación de Rothfusz). Por debajo de 26,7 °C
    (80 °F) NOAA no la aplica y el índice se da igual a la temperatura."""
    t = temp_c * 9 / 5 + 32
    if t < 80:
        return round(temp_c, 1)
    rh = humidity_pct
    hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
          - 6.83783e-3 * t * t - 5.481717e-2 * rh * rh + 1.22874e-3 * t * t * rh
          + 8.5282e-4 * t * rh * rh - 1.99e-6 * t * t * rh * rh)
    return round((hi - 32) * 5 / 9, 1)


def condensation_risk(margin_c: float) -> str:
    if margin_c < 2:
        return "high"
    if margin_c < 5:
        return "medium"
    return "low"


# --- escenarios ------------------------------------------------------------------

def _ramp(tick: int, start: float, end: float) -> float:
    k = min(1.0, tick / WORSEN_TICKS)
    return start + (end - start) * k


def scenario_values(scenario: str, tick: int, rng: random.Random) -> dict:
    """Valores "reales" del instante tick para un escenario."""
    if scenario == "sano":
        return {
            "hr": 72 + rng.uniform(-4, 4),
            "body": 36.7 + rng.uniform(-0.1, 0.1),
            "cabin": 23.0 + rng.uniform(-0.2, 0.2),
            "rh": 45 + rng.uniform(-2, 2),
        }
    if scenario == "empeora":
        return {
            "hr": _ramp(tick, 75, 155) + rng.uniform(-2, 2),
            "body": _ramp(tick, 36.8, 39.7) + rng.uniform(-0.05, 0.05),
            "cabin": _ramp(tick, 23.0, 30.0) + rng.uniform(-0.1, 0.1),
            "rh": _ramp(tick, 45, 78) + rng.uniform(-1, 1),
        }
    if scenario == "demo":
        crew_b = tick >= DEMO_SWITCH_TICK
        return {
            "hr": (156 if crew_b else 72) + rng.uniform(-2, 2),
            "body": (37.0 if crew_b else 36.7) + rng.uniform(-0.05, 0.05),
            "cabin": 23.0 + rng.uniform(-0.2, 0.2),
            "rh": 45 + rng.uniform(-2, 2),
        }
    raise ValueError(f"escenario desconocido: {scenario}")


def demo_crew(tick: int) -> str | None:
    if tick < DEMO_CHECKIN_TICK:
        return None
    return DEMO_CREW_B if tick >= DEMO_SWITCH_TICK else CREW_ID


def demo_motion(tick: int) -> dict:
    """Quieto desde que ficha; flexiones y 20 s moviéndose; luego quieto otra vez."""
    if tick < DEMO_CHECKIN_TICK:
        return {"activity": "still", "still_for_s": 0}
    after = DEMO_PUSHUP_TICK + DEMO_MOVING_TICKS
    if DEMO_PUSHUP_TICK <= tick < after:
        return {"activity": "moving", "still_for_s": 0}
    since = after if tick >= after else DEMO_CHECKIN_TICK
    return {"activity": "still", "still_for_s": (tick - since) * INTERVAL_S}


def make_telemetry(scenario: str, tick: int, ts: datetime, rng: random.Random) -> dict:
    """Un mensaje ① de telemetría con los mismos nulls que manda la placa."""
    base = {
        "device_id": DEVICE_ID,
        "ts": _iso(ts),
        "met_s": tick * INTERVAL_S,
        "crew_id": None,
        "vitals": {"heart_rate_bpm": None, "hr_quality": 0, "resp_rate_bpm": None, "body_temp_c": None},
        "motion": {"activity": "still", "still_for_s": tick * INTERVAL_S},
        "cabin": {k: None for k in ("temp_c", "humidity_pct", "dew_point_c", "heat_index_c", "condensation_risk")},
        "alerts": [],
    }
    if scenario == "sin-datos":
        return base

    v = scenario_values(scenario, tick, rng)
    moving = tick % PUSHUP_EVERY == 0 and tick > 0
    temp = round(v["cabin"], 1)
    rh = int(round(v["rh"]))                       # el DHT11 da enteros
    dew = dew_point_c(temp, rh)
    hi = heat_index_c(temp, rh)
    quality = round(rng.uniform(0.6, 0.95), 2)
    body = round(v["body"], 1)

    base["crew_id"] = demo_crew(tick) if scenario == "demo" else CREW_ID
    base["vitals"] = {
        "heart_rate_bpm": int(round(v["hr"])) if quality >= 0.4 else None,
        "hr_quality": quality,
        "resp_rate_bpm": None,                      # nunca se mide
        "body_temp_c": body if 30 <= body <= 45 else None,
    }
    if scenario == "demo":
        base["motion"] = demo_motion(tick)
    else:
        base["motion"] = {"activity": "moving" if moving else "still",
                          "still_for_s": 0 if moving else (tick % PUSHUP_EVERY) * INTERVAL_S}
    base["cabin"] = {"temp_c": temp, "humidity_pct": rh, "dew_point_c": dew,
                     "heat_index_c": hi, "condensation_risk": condensation_risk(temp - dew)}
    base["alerts"] = _local_alerts(base)
    return base


def make_events(scenario: str, tick: int, ts: datetime, rng: random.Random) -> list[dict]:
    """crew_checkin al empezar y una serie de flexiones cada PUSHUP_EVERY envíos.
    En "empeora" cada serie sale con menos repeticiones."""
    if scenario == "sin-datos":
        return []
    if scenario == "demo":
        return demo_events(tick, ts)
    events = []
    if tick == 0:
        events.append(_event(ts, "crew_checkin", "info", {"action": "in"}))
    if tick > 0 and tick % PUSHUP_EVERY == 0:
        series = tick // PUSHUP_EVERY
        reps = 20 + rng.randint(-1, 1) if scenario == "sano" else max(4, 20 - 5 * (series - 1))
        events.append(_event(ts, "exercise_summary", "info", {
            "exercise": "pushup", "reps": reps,
            "duration_s": reps * 2, "cadence_rpm": 30.0,
        }))
    return events


def demo_events(tick: int, ts: datetime) -> list[dict]:
    events = []
    if tick == DEMO_CHECKIN_TICK:
        events.append(_event(ts, "crew_checkin", "info", {"action": "in"}))
    still = demo_motion(tick)["still_for_s"]
    previous = demo_motion(tick - 1)["still_for_s"] if tick else 0
    if demo_crew(tick) and previous < DEMO_INACTIVITY_S <= still:
        events.append(_event(ts, "inactivity", "medium",
                             {"still_for_s": still, "threshold_s": DEMO_INACTIVITY_S}, demo_crew(tick)))
    if tick == DEMO_PUSHUP_TICK:
        events.append(_event(ts, "exercise_summary", "info",
                             {"exercise": "pushup", "reps": 20, "duration_s": 40, "cadence_rpm": 30.0}))
    if tick == DEMO_SWITCH_TICK:
        # Al cambiar de tarjeta: out del anterior y in del nuevo 1 s más tarde.
        events.append(_event(ts, "crew_checkin", "info", {"action": "out"}, CREW_ID))
        events.append(_event(ts + timedelta(seconds=1), "crew_checkin", "info", {"action": "in"}, DEMO_CREW_B))
    return events


def make_history(scenario: str, days: int, start: datetime, rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Días anteriores a start: un chequeo manual a las 08:00 y una serie de
    flexiones a las 18:00. En "sano" todo es estable; en "empeora" y "demo"
    la glucosa, la tensión y el ánimo empeoran y las flexiones caen."""
    checks, events = [], []
    worse = scenario in ("empeora", "demo")
    if scenario == "sin-datos":
        return checks, events
    for d in range(days, 0, -1):
        day = (start - timedelta(days=d)).replace(hour=8, minute=0, second=0)
        k = (days - d) / max(1, days - 1)            # 0 el primer día, 1 el último
        checks.append({
            "crew_id": CREW_ID, "ts": _iso(day),
            "blood_pressure": {
                "systolic": int(round((112 + 14 * k if worse else 115) + rng.uniform(-2, 2))),
                "diastolic": int(round((72 + 6 * k if worse else 75) + rng.uniform(-2, 2))),
            },
            "glucose_mg_dl": int(round((86 + 12 * k if worse else 90) + rng.uniform(-2, 2))),
            "mood": int(round(4 - 1.0 * k)) if worse else 4,
        })
        reps = int(round((20 - 4 * k if worse else 20) + rng.uniform(-0.5, 0.5)))
        events.append(_event(day.replace(hour=18), "exercise_summary", "info",
                             {"exercise": "pushup", "reps": reps, "duration_s": reps * 2, "cadence_rpm": 30.0}))
    return checks, events


def _event(ts: datetime, kind: str, severity: str, data: dict, crew_id: str | None = CREW_ID) -> dict:
    return {"device_id": DEVICE_ID, "ts": _iso(ts), "crew_id": crew_id,
            "type": kind, "severity": severity, "data": data}


def _local_alerts(msg: dict) -> list[str]:
    """Alertas que levanta la placa por su cuenta (no son los niveles del motor)."""
    v, c, out = msg["vitals"], msg["cabin"], []
    hr, body = v["heart_rate_bpm"], v["body_temp_c"]
    if hr is not None and hr > 120:
        out.append("HR_HIGH")
    if hr is not None and hr < 45:
        out.append("HR_LOW")
    if body is not None and body >= 38.0:
        out.append("BODY_TEMP_HIGH")
    if body is not None and body < 35.5:
        out.append("BODY_TEMP_LOW")
    if c["temp_c"] is not None and c["temp_c"] > 27:
        out.append("CABIN_TEMP_HIGH")
    if c["temp_c"] is not None and c["temp_c"] < 18:
        out.append("CABIN_TEMP_LOW")
    if c["heat_index_c"] is not None and c["heat_index_c"] >= 32.2:
        out.append("HEAT_INDEX_HIGH")
    if c["condensation_risk"] == "high":
        out.append("CONDENSATION_HIGH")
    return out


# --- envío a la API ----------------------------------------------------------------

class Sender:
    """Cola de envío con la misma lógica de reintentos que el ESP32."""

    def __init__(self, url: str, api_key: str | None, timeout: float = 3.0, sleep=time.sleep):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.sleep = sleep
        self.queue: deque[tuple[str, dict]] = deque(maxlen=MAX_QUEUE)
        self.stats = {"sent": 0, "duplicate": 0, "dropped": 0, "retries": 0}

    def push(self, path: str, body: dict) -> None:
        self.queue.append((path, body))

    def flush(self, deadline_s: float = MAX_BACKOFF_S) -> None:
        """Envía en orden. Si un 5xx persiste más de deadline_s, deja la cola
        para el siguiente ciclo, como hace la placa."""
        while self.queue:
            path, body = self.queue[0]
            status = self._post_with_backoff(path, body, deadline_s)
            if status is None:
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
            if status is not None and 400 <= status < 500:
                self.stats["dropped"] += 1
                print(f"[sim] {path} → {status}: mensaje descartado", file=sys.stderr)
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
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status
        except urllib.error.HTTPError as err:
            return err.code
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return None


# --- bucle principal -----------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    if args.scenario == "demo":
        os.environ["SPACEHEALTH_DEMO"] = "1"
    rng = random.Random(args.seed)
    start = datetime.now(timezone.utc).replace(microsecond=0)
    sender = Sender(args.url, args.api_key) if args.url else None
    checks, history_e = make_history(args.scenario, args.history_days, start, rng)
    history_t: list[dict] = []

    # La historia sale primero: chequeos a /checks (los manda la web, no la placa).
    for msg in checks:
        _emit(sender, args, "/api/v1/checks", msg)
    for msg in history_e:
        _emit(sender, args, "/api/v1/events", msg)
    if sender:
        sender.flush()

    tick = 0
    last_crew = None
    while args.count is None or tick < args.count:
        ts = start + timedelta(seconds=tick * INTERVAL_S) if args.fast else datetime.now(timezone.utc).replace(microsecond=0)
        telemetry = make_telemetry(args.scenario, tick, ts, rng)
        events = make_events(args.scenario, tick, ts, rng)

        for ev in events:
            _emit(sender, args, "/api/v1/events", ev)
        _emit(sender, args, "/api/v1/telemetry", telemetry)
        if sender:
            sender.flush()

        if args.evaluate:
            history_t.append(telemetry)
            history_e.extend(events)
            crew = telemetry["crew_id"]
            print(_summary(tick, telemetry, history_t, history_e, checks, ts, crew != last_crew), flush=True)
            last_crew = crew

        tick += 1
        if not args.fast and (args.count is None or tick < args.count):
            time.sleep(INTERVAL_S)

    if sender:
        print(f"[sim] {sender.stats}", file=sys.stderr)


def _emit(sender, args, path, msg) -> None:
    if sender:
        sender.push(path, msg)
    elif not args.evaluate:
        print(json.dumps(msg, ensure_ascii=False), flush=True)


def _summary(tick, telemetry, history_t, history_e, checks, now, show_trends) -> str:
    """Una línea con los niveles, como los recibiría la web. La API pasa al
    motor solo los mensajes de un crew_id, así que aquí se filtra igual."""
    from risk import evaluate   # import tardío: el simulador no depende del motor

    crew = telemetry["crew_id"]
    if crew is None:
        return f"t={tick * INTERVAL_S:>4}s sin fichar: la API no llama al motor sin crew_id"
    mine = lambda msgs: [m for m in msgs if m.get("crew_id") == crew]
    result = evaluate(mine(history_t[-20:]), mine(history_e), mine(checks), now)
    names = {"cardiovascular": "cardio", "neuro": "neuro", "musculoskeletal": "músculo", "environment": "cabina"}
    levels = " ".join(f"{names[k]}={_lvl(s['level'])}" for k, s in result["systems"].items())
    v, c = telemetry["vitals"], telemetry["cabin"]
    line = (f"t={tick * INTERVAL_S:>4}s {crew or 'sin fichar':>9} pulso={v['heart_rate_bpm']} "
            f"temp={v['body_temp_c']} quieto={telemetry['motion']['still_for_s']}s "
            f"cabina={c['temp_c']}°C/{c['humidity_pct']}% → global={_lvl(result['overall_level'])} {levels}")
    if result["recommendations"]:
        line += f"\n        recomienda: {result['recommendations'][0]}"
    if show_trends:
        for t in result["trends"]:
            if t["crosses_threshold_in_days"] is not None:
                line += (f"\n        tendencia: {t['indicator']} cruza {t['threshold']} "
                         f"en {t['crosses_threshold_in_days']} días")
    if result.get("earth_summary") and show_trends:
        line += "\n" + "\n".join("        | " + l for l in result["earth_summary"].splitlines())
    return line


def _lvl(level) -> str:
    return "—" if level is None else str(level)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simulador del ESP32 de SpaceHealth")
    p.add_argument("--scenario", choices=SCENARIOS, default="sano")
    p.add_argument("--count", type=int, default=None, help="número de envíos (por defecto, sin fin)")
    p.add_argument("--fast", action="store_true", help="no espera 5 s; las horas avanzan igual de 5 en 5 s")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--url", help="base de la API, p. ej. http://localhost:8000")
    p.add_argument("--api-key", help="se manda en la cabecera X-API-Key")
    p.add_argument("--evaluate", action="store_true", help="pasa los datos por el motor y muestra los niveles")
    p.add_argument("--history-days", type=int, default=0, help="días de chequeos y flexiones previos (p. ej. 7)")
    return p.parse_args(argv)


if __name__ == "__main__":
    try:
        run(parse_args())
    except KeyboardInterrupt:
        pass
