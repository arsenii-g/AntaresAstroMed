"""Trends: a least-squares line over the crew member's own real measurements,
projected forward.

There are two kinds of x axis, depending on how the data arrives:

- Per measurement (basis "count"): manual check (blood pressure, glucose,
  mood) and push-up sets. Each measurement is one step: the latest is x = 0,
  the previous one x = -1, and so on. Projected 7 measurements ahead. With
  one check per day, 7 checks are a week; in a demo you can enter 7 in a
  row and the line comes out just as well, because it does not depend on how
  much time passes between them.
- Per time (basis "time"): sensor telemetry (pulse, body temperature, cabin
  temperature and humidity). x = seconds relative to now, using the last
  minute of telemetry that the API passes in. Projected 60 s ahead.

Team criterion:
- At least 7 measurements with a value are needed to draw a line.
- The monitored threshold is the next one the line has not yet passed, in
  the direction of the slope. crosses_in says how many steps (or seconds)
  are left before the line crosses it, or None if it does not cross it
  within the horizon.
- The push-up threshold is expressed in repetitions: the baseline (average
  of the sets before the latest) minus the level's drop percentage.
- A low body temperature gives at most amber (low_max_level), so its
  downward trend only monitors the amber cut.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .indicators import as_number, load_thresholds


def _obj(value) -> dict:
    return value if isinstance(value, dict) else {}


MIN_POINTS = 7
HORIZON_COUNT = 7          # measurements ahead (checks or sets)
HORIZON_S = 60             # seconds ahead (telemetry)

CHECK_TRENDS = {
    "systolic_mmhg": lambda c: _obj(c.get("blood_pressure")).get("systolic"),
    "diastolic_mmhg": lambda c: _obj(c.get("blood_pressure")).get("diastolic"),
    "glucose_mg_dl": lambda c: c.get("glucose_mg_dl"),
    "mood": lambda c: c.get("mood"),
}
TELEMETRY_TRENDS = {
    "heart_rate_bpm": lambda m: _obj(m.get("vitals")).get("heart_rate_bpm"),
    "body_temp_c": lambda m: _obj(m.get("vitals")).get("body_temp_c"),
    "cabin_temp_c": lambda m: _obj(m.get("cabin")).get("temp_c"),
    "humidity_pct": lambda m: _obj(m.get("cabin")).get("humidity_pct"),
}
VALUE_LIMITS = {"mood": (1, 5), "pushup_reps": (0, None), "humidity_pct": (0, 100)}


@dataclass(frozen=True)
class Trend:
    indicator: str
    label: str
    unit: str
    basis: str                       # "count" or "time"
    x_unit: str                      # "check", "set" or "s"
    points: tuple                    # ((x, value), ...) used in the fit
    slope: float                     # per x_unit
    intercept: float                 # value of the line at x = 0
    horizon: float                   # how far ahead it is projected, in x_unit
    projected: float                 # value of the line at x = horizon
    threshold: float | None          # next cut in the direction of the slope
    threshold_level: int | None      # level that cut would lead to
    crosses_in: float | None         # x_unit until it crosses; None if it does not within the horizon

    def as_dict(self) -> dict:
        return {
            "indicator": self.indicator,
            "label": self.label,
            "unit": self.unit,
            "basis": self.basis,
            "x_unit": self.x_unit,
            "points": [list(p) for p in self.points],
            "slope": self.slope,
            "intercept": self.intercept,
            "horizon": self.horizon,
            "projected": self.projected,
            "threshold": self.threshold,
            "threshold_level": self.threshold_level,
            "crosses_in": self.crosses_in,
        }


def trends_for(telemetry: list[dict], checks: list[dict], events: list[dict],
               now: datetime, parse_ts) -> list[Trend]:
    """telemetry: last minute; checks and events: last 7 days. All already
    sorted by ts and without duplicates (engine.py does that)."""
    thresholds = load_thresholds()
    out = []

    for name, get in CHECK_TRENDS.items():
        values = [v for c in checks if (v := as_number(get(c))) is not None]
        trend = _fit(name, thresholds[name], _count_points(values), "count", "check", HORIZON_COUNT)
        if trend:
            out.append(trend)

    reps = [v for e in events if e.get("type") == "exercise_summary"
            and (v := as_number(_obj(e.get("data")).get("reps"))) is not None]
    if len(reps) >= MIN_POINTS:
        baseline = sum(reps[:-1]) / len(reps[:-1])
        drops = thresholds["pushup_drop_pct"].get("high", [])
        spec = {"label": "Push-ups per set", "unit": "reps", "high": [],
                "low": [None if d is None else round(baseline * (1 - d / 100), 1) for d in drops]}
        trend = _fit("pushup_reps", spec, _count_points(reps), "count", "set", HORIZON_COUNT)
        if trend:
            out.append(trend)

    for name, get in TELEMETRY_TRENDS.items():
        points = []
        for m in telemetry:
            value, ts = as_number(get(m)), parse_ts(m.get("ts"))
            if value is not None and ts is not None:
                points.append((round((ts - now).total_seconds(), 1), float(value)))
        trend = _fit(name, thresholds[name], points, "time", "s", HORIZON_S)
        if trend:
            out.append(trend)
    return out


def _count_points(values: list[float]) -> list[tuple[float, float]]:
    n = len(values)
    return [(float(i - (n - 1)), float(v)) for i, v in enumerate(values)]


def _fit(name, spec, points, basis, x_unit, horizon) -> Trend | None:
    if len(points) < MIN_POINTS:
        return None
    slope, intercept = _least_squares(points)
    high, low = list(spec.get("high", [])), list(spec.get("low", []))
    if "low_max_level" in spec:
        low = [cut if i < spec["low_max_level"] else None for i, cut in enumerate(low)]
    inclusive = spec.get("inclusive", False)

    now_value = intercept                       # the line at x = 0
    # Only the threshold in the worsening direction is monitored: a high pulse
    # that falls, or a low humidity that rises, is recovering and has no threshold.
    above_high = _next_cut(now_value, high, above=True, inclusive=inclusive) != _first_cut(high)
    below_low = _next_cut(now_value, low, above=False, inclusive=inclusive) != _first_cut(low)
    found = None
    if slope > 0 and not below_low:
        found = _next_cut(now_value, high, above=True, inclusive=inclusive)
    elif slope < 0 and not above_high:
        found = _next_cut(now_value, low, above=False, inclusive=inclusive)

    threshold = level = crosses = None
    if found:
        threshold, level = found
        when = (threshold - intercept) / slope
        if 0 <= when <= horizon:
            crosses = round(max(when, 0.1), 1)

    return Trend(
        indicator=name, label=spec["label"], unit=spec["unit"], basis=basis, x_unit=x_unit,
        points=tuple((x, round(v, 2)) for x, v in points),
        slope=round(slope, 4), intercept=round(intercept, 2), horizon=horizon,
        projected=round(_clip(name, intercept + slope * horizon), 1),
        threshold=threshold, threshold_level=level, crosses_in=crosses,
    )


def _next_cut(current, cuts, *, above, inclusive):
    """First cut the current value has not crossed yet, with its level."""
    for i, cut in enumerate(cuts, start=1):
        if cut is None:
            continue
        if above:
            crossed = current >= cut if inclusive else current > cut
        else:
            crossed = current <= cut if inclusive else current < cut
        if not crossed:
            return cut, i
    return None


def _first_cut(cuts):
    """The first cut in use, with its level (or None if there is none)."""
    return next(((cut, i) for i, cut in enumerate(cuts, start=1) if cut is not None), None)


def _least_squares(points):
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return 0.0, my
    slope = sum((x - mx) * (y - my) for x, y in points) / sxx
    return slope, my - slope * mx


def _clip(name, value):
    lo, hi = VALUE_LIMITS.get(name, (None, None))
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value
