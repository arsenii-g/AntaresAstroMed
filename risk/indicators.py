"""Risk level (0 to 3) of a single measurement, based on risk/thresholds.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from astromed_config import demo_mode

THRESHOLDS_PATH = Path(__file__).resolve().parent / "thresholds.json"


@dataclass(frozen=True)
class IndicatorResult:
    indicator: str
    system: str
    value: float | None
    level: int | None  # None = no data; never treated as green
    code: str | None  # e.g. "HR_HIGH"; None if in range or no data
    reason: str | None  # English text for the frontend; None if in range
    cut: float | None = None  # cut exceeded; None if in range or no data


def load_thresholds(path: str | None = None) -> dict:
    """Thresholds per indicator, with the demo ones on top if demo_mode()."""
    return _load(str(path or THRESHOLDS_PATH), demo_mode())


@lru_cache(maxsize=4)
def _load(path: str, demo: bool) -> dict:
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)
    indicators = data["indicators"]
    if demo:
        for name, override in data.get("demo", {}).items():
            indicators[name] = {**indicators[name], **override}
    return indicators


def level_for(indicator: str, value: float | None, thresholds: dict | None = None) -> IndicatorResult:
    """Compare a measurement with its thresholds and return its level and reason.

    >>> level_for("heart_rate_bpm", 118).level
    1
    """
    spec = (thresholds or load_thresholds())[indicator]
    system = spec["system"]
    value = as_number(value)

    if value is None:
        return IndicatorResult(indicator, system, None, None, None, f"{spec['label']}: no data")

    inclusive = spec.get("inclusive", False)
    high_level = _band(value, spec.get("high", []), above=True, inclusive=inclusive)
    low_level = _band(value, spec.get("low", []), above=False, inclusive=inclusive)

    if high_level == 0 and low_level == 0:
        return IndicatorResult(indicator, system, value, 0, None, None)

    if high_level >= low_level:
        level, direction, cut = high_level, "HIGH", spec["high"][high_level - 1]
        relation = "above"
    else:
        level, direction, cut = low_level, "LOW", spec["low"][low_level - 1]
        relation = "below"

    unit = spec["unit"]
    reason = f"{spec['label']} {with_unit(value, unit)}, {relation} {with_unit(cut, unit)}"
    return IndicatorResult(indicator, system, value, level, f"{spec['code']}_{direction}", reason, cut)


def restate(result: IndicatorResult, level: int, note: str, thresholds: dict | None = None) -> IndicatorResult:
    """The same result at another (lower) level, with a note at the end of the
    reason. The cut and the reason are recomputed for that level."""
    spec = (thresholds or load_thresholds())[result.indicator]
    if not level:
        return IndicatorResult(result.indicator, result.system, result.value, 0, None, None)
    direction = "HIGH" if (result.code or "").endswith("_HIGH") else "LOW"
    cuts = spec.get("high" if direction == "HIGH" else "low", [])
    # The cut for that level; if it is null, the closest one below (or the first one available).
    below = [c for c in cuts[:level] if c is not None]
    above = [c for c in cuts[level:] if c is not None]
    cut = below[-1] if below else above[0] if above else result.cut
    relation = "above" if direction == "HIGH" else "below"
    unit = spec["unit"]
    reason = f"{spec['label']} {with_unit(result.value, unit)}, {relation} {with_unit(cut, unit)} ({note})"
    return IndicatorResult(result.indicator, result.system, result.value, level, result.code, reason, cut)


def as_number(value):
    """The value if it is a real number (int or float, not bool); otherwise None.
    That way a stray "80" or [1] counts as no data instead of breaking the engine."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if value == value else None          # NaN is also no data


def _band(value: float, cuts: list, *, above: bool, inclusive: bool) -> int:
    """Highest level whose cut is exceeded. Null cuts are ignored."""
    level = 0
    for i, cut in enumerate(cuts, start=1):
        if cut is None:
            continue
        if above:
            hit = value >= cut if inclusive else value > cut
        else:
            hit = value <= cut if inclusive else value < cut
        if hit:
            level = i
    return level


def _fmt(number: float) -> str:
    """118 -> '118', 38.0 -> '38', 37.6 -> '37.6' (decimal point, English style)."""
    return f"{number:.1f}".rstrip("0").rstrip(".")


def with_unit(number: float, unit: str) -> str:
    """'118 bpm', '72%', '2/5': no space before % and /5."""
    sep = "" if unit.startswith(("%", "/")) else " "
    return f"{_fmt(number)}{sep}{unit}"
