from __future__ import annotations

import math
from statistics import median
from typing import Sequence


def ewma(values: Sequence[float], alpha: float = 0.3) -> list[float]:
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    if not values:
        return []
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def moving_median(values: Sequence[float], window: int = 7) -> list[float]:
    if window <= 0:
        raise ValueError("window must be positive")
    return [
        float(median(values[max(0, index - window + 1) : index + 1]))
        for index in range(len(values))
    ]


def wilson_interval(
    successes: float,
    total: float,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    if total <= 0:
        return (0.0, 1.0)
    proportion = min(1.0, max(0.0, successes / total))
    z_squared = z * z
    denominator = 1 + z_squared / total
    centre = (proportion + z_squared / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt((proportion * (1 - proportion) + z_squared / (4 * total)) / total)
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def robust_z_score(value: float, history: Sequence[float]) -> float:
    if len(history) < 7:
        return 0.0
    centre = float(median(history))
    deviations = [abs(float(item) - centre) for item in history]
    scale = float(median(deviations))
    if scale == 0:
        nonzero = [deviation for deviation in deviations if deviation > 0]
        if not nonzero:
            return 0.0
        scale = float(median(nonzero))
    return 0.6744897501960817 * (float(value) - centre) / scale
