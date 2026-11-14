"""Nivel de riesgo (0 a 3) de una sola medida, según risk/thresholds.json."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

THRESHOLDS_PATH = Path(__file__).resolve().parent / "thresholds.json"


@dataclass(frozen=True)
class IndicatorResult:
    indicator: str
    system: str
    value: float | None
    level: int | None  # None = sin dato; nunca se trata como verde
    code: str | None  # p. ej. "HR_HIGH"; None si está en rango o sin dato
    reason: str | None  # texto en inglés para el frontend; None si está en rango
    cut: float | None = None  # corte superado; None si está en rango o sin dato


def demo_mode() -> bool:
    """SPACEHEALTH_DEMO=1 activa los cortes de demo de thresholds.json."""
    return os.environ.get("SPACEHEALTH_DEMO") == "1"


def load_thresholds(path: str | None = None) -> dict:
    """Umbrales por indicador, con los de demo encima si demo_mode()."""
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
    """Compara una medida con sus umbrales y devuelve su nivel y su motivo.

    >>> level_for("heart_rate_bpm", 118).level
    1
    """
    spec = (thresholds or load_thresholds())[indicator]
    system = spec["system"]

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


def _band(value: float, cuts: list, *, above: bool, inclusive: bool) -> int:
    """Nivel más alto cuyo corte se supera. Los cortes null no cuentan."""
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
    """118 -> '118', 38.0 -> '38', 37.6 -> '37.6' (punto decimal, en inglés)."""
    return f"{number:.1f}".rstrip("0").rstrip(".")


def with_unit(number: float, unit: str) -> str:
    """'118 bpm', '72%', '2/5': sin espacio delante de % y de /5."""
    sep = "" if unit.startswith(("%", "/")) else " "
    return f"{_fmt(number)}{sep}{unit}"
