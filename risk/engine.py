"""evaluate(): entry point of the risk engine.

Steps (team guide, section 5):
  1. Level per indicator against thresholds.json (indicators.py).
  2. Level per system: the worst of its indicators.
  3. Trends: least-squares line with at least 7 measurements. Checks and
     push-up sets, measurement by measurement, projected 7 measurements
     ahead; pulse, body temperature and cabin, in seconds, projected 60 s
     ahead (trends.py).
  4. Recommendations: one countermeasure for each amber or worse result, and
     one warning for each trend that crosses a threshold within its horizon.
  5. English summary for Earth when the overall level is 3 (summary.py).

Missing data is "no data", never green. All output texts are in English. If
a system has no data at all, its level is None.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .indicators import IndicatorResult, as_number, level_for, load_thresholds, restate, with_unit, _fmt
from .recommendations import recommendations_for, trend_recommendations
from .summary import earth_summary
from .trends import trends_for

SYSTEMS = ("cardiovascular", "neuro", "musculoskeletal", "environment")

# Maximum age of a reading to be considered valid (team criterion).
TELEMETRY_MAX_AGE = timedelta(seconds=60)   # arrives every 2 s: about 30 readings
CHECK_MAX_AGE = timedelta(hours=24)         # one manual check per day
HISTORY_WINDOW = timedelta(days=7)          # push-up baseline and trends


def evaluate(
    telemetry: list[dict],
    events: list[dict],
    manual_checks: list[dict],
    now: datetime,
) -> dict:
    """Evaluate the risk of one crew member.

    Args:
        telemetry: ① telemetry messages (contracts/telemetry.example.json),
            all with the same crew_id. Any field may be None.
        events: ① events (crew_checkin, inactivity, exercise_summary) with the
            same crew_id, from the last 7 days.
        manual_checks: ② manual checks with the same crew_id. For trends, the API
            must pass those from the last 7 days.
        now: current time, a datetime WITH a timezone: datetime.now(timezone.utc).
            Without one it raises ValueError: a local datetime.now() in UTC+1
            would make all telemetry look an hour old.

    Returns:
        The ③ assessment (contracts/assessment.example.json). The level of a
        system with no data, and overall_level if there is none, is None.

    Never raises exceptions for missing, incomplete or garbage data.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("evaluate(now=...) needs a timezone-aware datetime: datetime.now(timezone.utc)")
    now = now.astimezone(timezone.utc)
    telemetry = _sorted_recent(telemetry, now, TELEMETRY_MAX_AGE)
    checks_week = _sorted_recent(manual_checks, now, HISTORY_WINDOW)
    checks_today = [c for c in checks_week if _parse_ts(c.get("ts")) >= now - CHECK_MAX_AGE]
    events = _without_carried_sets(_sorted_recent(events, now, HISTORY_WINDOW))

    results = (
        _telemetry_indicators(telemetry, events, now)
        + _check_indicators(checks_today, checks_week)
        + _exercise_indicators(events)
    )
    trends = trends_for(telemetry, checks_week, events, now, _parse_ts)

    systems = {}
    for name in SYSTEMS:
        own = [r for r in results if r.system == name]
        known = [r.level for r in own if r.level is not None]
        flagged = sorted((r for r in own if r.level), key=lambda r: -r.level)
        missing = [r for r in own if r.level is None]
        systems[name] = {
            "level": max(known) if known else None,
            "reasons": [r.reason for r in flagged + missing],
        }

    levels = [s["level"] for s in systems.values() if s["level"] is not None]
    overall = max(levels) if levels else None
    crew_id = _find_crew_id(telemetry, events, checks_week)
    recommendations = recommendations_for(results)
    for text in trend_recommendations(trends, results):
        if text not in recommendations:
            recommendations.append(text)
    return {
        "crew_id": crew_id,
        "ts": _iso(now),
        "overall_level": overall,
        "systems": systems,
        "trends": [t.as_dict() for t in trends],
        "recommendations": recommendations,
        "earth_summary": earth_summary(crew_id, _iso(now), overall, systems, results, trends),
    }


# --- indicators ---------------------------------------------------------------

def _telemetry_indicators(telemetry: list[dict], events: list[dict], now: datetime) -> list[IndicatorResult]:
    motion = lambda m: _obj(m.get("motion"))
    cabin = lambda m: _obj(m.get("cabin"))

    def margin(m):
        temp, dew = as_number(cabin(m).get("temp_c")), as_number(cabin(m).get("dew_point_c"))
        if temp is None or dew is None:
            return None
        return round(temp - dew, 1)

    getters = {
        "still_for_s": lambda m: motion(m).get("still_for_s"),
        "cabin_temp_c": lambda m: cabin(m).get("temp_c"),
        "humidity_pct": lambda m: cabin(m).get("humidity_pct"),
        "heat_index_c": lambda m: cabin(m).get("heat_index_c"),
        "condensation_margin_c": margin,
    }
    # The most recent non-None value within the 60 s window.
    return [_heart_rate(telemetry, events, now), _body_temp(telemetry)] + [
        level_for(name, _latest(telemetry, get)) for name, get in getters.items()
    ]


def _vital(message: dict, name: str):
    return as_number(_obj(message.get("vitals")).get(name))


def _sustained(telemetry: list[dict], indicator: str) -> IndicatorResult:
    """Level of a vital sign with the sustained-readings rule (team criterion,
    see risk/README.md, section 3):

    - Amber on a single reading: warning early costs nothing.
    - Orange or red only if the last sustain_readings readings are at that
      level or worse. Until then, amber: never green, so a sensor glitch
      does not hide a real problem.
    - High and low readings mixed in the window: amber and check the
      sensor, because the signal is not reliable.
    """
    need = load_thresholds()[indicator].get("sustain_readings", 1)
    samples = [(m, level_for(indicator, v)) for m in telemetry if (v := _vital(m, indicator)) is not None]
    seconds = load_thresholds()[indicator].get("sustain_seconds", 0)
    first = max(0, len(samples) - need)
    # Firmware now sends every 2 s, while pulse windows still cover 10 s.
    # Count alone would confirm overlapping observations too early.
    while first > 0 and (_parse_ts(samples[-1][0]["ts"]) - _parse_ts(samples[first][0]["ts"])).total_seconds() < seconds:
        first -= 1
    samples = samples[first:]
    window = [r for _, r in samples]
    if not window:
        return level_for(indicator, None)
    latest = window[-1]
    flagged = [r for r in window if r.level]
    if len({r.code for r in flagged}) > 1:
        return restate(flagged[-1], 1, "inconsistent readings; check the sensor")
    worst = max(reversed(window), key=lambda r: r.level)      # on a tie, the most recent
    if worst.level < 2:
        return latest
    elapsed = (_parse_ts(samples[-1][0]["ts"]) - _parse_ts(samples[0][0]["ts"])).total_seconds()
    floor = min(r.level for r in window) if len(window) >= need and elapsed >= seconds else 0
    if floor >= 2:
        held = next(r for r in reversed(window) if r.level == floor)
        return restate(held, floor, f"sustained over {len(window)} readings")
    high = sum(1 for r in window if r.level >= 2)
    note = f"not sustained yet: {high} of {need} readings"
    if seconds and elapsed < seconds:
        note += f"; {elapsed:g} of {seconds:g} s"
    return restate(worst, 1, note)


def _body_temp(telemetry: list[dict]) -> IndicatorResult:
    """Body temperature: sustained readings (_sustained) and, in addition, a
    low reading gives at most low_max_level (amber). The thermistor sits on
    the wrist, and the skin cools down with the cabin even if the crew
    member is fine (Polar, see thresholds.json). A cold wrist calls for a
    thermometer, not for contacting Earth. A high reading (fever) keeps its
    levels."""
    result = _sustained(telemetry, "body_temp_c")
    spec = load_thresholds()["body_temp_c"]
    if result.code == "BODY_TEMP_LOW" and "low_max_level" in spec:
        result = restate(result, min(result.level, spec["low_max_level"]), spec.get("low_note", ""))
    return result


def _heart_rate(telemetry: list[dict], events: list[dict], now: datetime) -> IndicatorResult:
    """Pulse: sustained readings (_sustained) and, in addition, a grace margin
    after exercise (team criterion): if the crew member is moving or did
    push-ups within the last exercise_recovery_s, a high pulse at orange
    drops to amber, because a raised pulse from effort is normal. Red
    (more than 150 bpm) is not downgraded: that is no longer explained by a
    few push-ups.
    """
    result = _sustained(telemetry, "heart_rate_bpm")
    spec = load_thresholds()["heart_rate_bpm"]
    if result.level == 2 and result.code == "HR_HIGH" and _recovering(telemetry, events, now, spec):
        result = restate(result, 1, "after exercise; recheck at rest")
    return result


def _recovering(telemetry, events, now, spec) -> bool:
    moving = bool(telemetry) and _obj(telemetry[-1].get("motion")).get("activity") == "moving"
    window = timedelta(seconds=spec.get("exercise_recovery_s", 0))
    recent_set = any(
        e.get("type") == "exercise_summary" and (ts := _parse_ts(e.get("ts"))) is not None
        and now - window <= ts <= now + timedelta(seconds=5)
        for e in events
    )
    return moving or recent_set


def _check_indicators(today: list[dict], week: list[dict]) -> list[IndicatorResult]:
    """today: checks from the last 24 h (give the current value). week: those
    from the last 7 days (give the previous blood pressure reading and the
    mood average)."""
    bp = lambda c: _obj(c.get("blood_pressure"))
    return [
        _blood_pressure(today, week, "systolic_mmhg", lambda c: as_number(bp(c).get("systolic"))),
        _blood_pressure(today, week, "diastolic_mmhg", lambda c: as_number(bp(c).get("diastolic"))),
        level_for("glucose_mg_dl", _latest(today, lambda c: as_number(c.get("glucose_mg_dl")))),
        _mood(today, week),
    ]


def _blood_pressure(today: list[dict], week: list[dict], indicator: str, get) -> IndicatorResult:
    """The guide says to escalate with 140/90 "on two readings": level 2 needs
    two consecutive readings at level 2 or worse. The latest must be from
    the last 24 h; the previous one can be from any of the last 7 days.
    Level 3 counts with a single reading."""
    if _latest(today, get) is None:
        return level_for(indicator, None)
    values = [get(c) for c in week if get(c) is not None]
    last = level_for(indicator, values[-1])
    if last.level != 2:
        return last
    previous = level_for(indicator, values[-2]) if len(values) >= 2 else None
    if previous is not None and (previous.level or 0) >= 2:
        return last
    return IndicatorResult(
        last.indicator, last.system, last.value, 1, last.code,
        f"{last.reason} (first reading; confirm with a second one)", last.cut,
    )


def _mood(today: list[dict], week: list[dict]) -> IndicatorResult:
    """Mood against the fixed cuts and, in addition, against the crew member's
    own average: amber if today is personal_drop points or more below the
    average of the previous checks in the last 7 days (team criterion)."""
    get = lambda c: as_number(c.get("mood"))
    fixed = level_for("mood", _latest(today, get))
    if fixed.value is None or fixed.level:
        return fixed
    spec = load_thresholds()["mood"]
    values = [v for c in week if (v := get(c)) is not None]
    previous = values[:-1]
    if len(previous) < spec.get("personal_min_checks", 3):
        return fixed
    average = sum(previous) / len(previous)
    drop = average - fixed.value
    if drop < spec.get("personal_drop", 99):
        return fixed
    reason = (f"{spec['label']} {with_unit(fixed.value, spec['unit'])}, {_fmt(drop)} points "
              f"below own average {with_unit(average, spec['unit'])}")
    return IndicatorResult("mood", fixed.system, fixed.value, 1, f"{spec['code']}_LOW", reason,
                           round(average - spec["personal_drop"], 1))


def _exercise_indicators(events: list[dict]) -> list[IndicatorResult]:
    """Push-up drop of the latest set against the average of the previous ones
    in the last 7 days. With no previous sets there is no baseline and
    nothing is evaluated."""
    reps = [
        as_number(_obj(e.get("data")).get("reps"))
        for e in events
        if e.get("type") == "exercise_summary"
    ]
    reps = [r for r in reps if r is not None]
    if len(reps) < 2:
        return []
    baseline = sum(reps[:-1]) / len(reps[:-1])
    if baseline <= 0:
        return []
    drop = max(0.0, round((baseline - reps[-1]) / baseline * 100, 1))
    return [level_for("pushup_drop_pct", drop)]


# --- utilities -----------------------------------------------------------------

def _latest(messages: list[dict], get):
    for message in reversed(messages):
        value = get(message)
        if value is not None:
            return value
    return None


def _without_carried_sets(events: list[dict]) -> list[dict]:
    """Remove push-up sets that do not belong to this crew member. If someone
    swipes their card in the middle of a set, the board sends the summary
    right after the crew_checkin "in", with the crew_id of the person who
    just arrived (firmware: resetCrewState). That set belongs to the previous
    person and would spoil the new one's baseline, so a set arriving up to
    3 s after is dropped."""
    entries = [
        ts for e in events
        if e.get("type") == "crew_checkin" and _obj(e.get("data")).get("action") == "in"
        and (ts := _parse_ts(e.get("ts"))) is not None
    ]
    def carried(e):
        ts = _parse_ts(e.get("ts"))
        return (e.get("type") == "exercise_summary" and ts is not None
                and any(timedelta(0) <= ts - t <= timedelta(seconds=3) for t in entries))
    return [e for e in events if not carried(e)]


def _obj(value) -> dict:
    """value if it is a dict; otherwise (None, list, text...), an empty dict."""
    return value if isinstance(value, dict) else {}


def _sorted_recent(messages: list[dict] | None, now: datetime, max_age: timedelta) -> list[dict]:
    """Messages within the window, sorted by ts, without garbage and without
    duplicates. A duplicate is the same (device_id, ts, type), as on the
    board: if the API stores a retry twice, it counts once."""
    out, seen = [], set()
    for m in messages if isinstance(messages, list) else []:
        if not isinstance(m, dict):
            continue
        ts = _parse_ts(m.get("ts"))
        key = (m.get("device_id"), m.get("ts"), m.get("type"))
        if ts is None or not now - max_age <= ts <= now + timedelta(seconds=5) or _seen(key, seen):
            continue
        out.append((ts, m))
    out.sort(key=lambda pair: pair[0])
    return [m for _, m in out]


def _seen(key: tuple, seen: set) -> bool:
    try:
        if key in seen:
            return True
        seen.add(key)
    except TypeError:          # device_id or type that cannot be compared: not deduplicated
        pass
    return False


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, OverflowError):
        return None


def _find_crew_id(*sources: list[dict]) -> str | None:
    for messages in sources:
        for message in reversed(messages):
            if isinstance(message.get("crew_id"), str) and message["crew_id"]:
                return message["crew_id"]
    return None


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
