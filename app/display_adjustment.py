"""Non-destructive Imaris display-range conversion for figure output."""

from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


def apply_display_adjustment(
    image: ArrayLike,
    display_min: float,
    display_max: float,
) -> NDArray[np.uint8]:
    """Linearly map an image to uint8 using an Imaris-style ColorRange.

    The input is never modified. Values at or below ``display_min`` become 0,
    and values at or above ``display_max`` become 255.
    """

    if not np.isfinite(display_min) or not np.isfinite(display_max):
        raise ValueError("Display range must contain finite numbers.")
    if display_max <= display_min:
        raise ValueError("display_max must be greater than display_min.")
    source = np.asarray(image)
    normalized = (source.astype(np.float32, copy=False) - display_min) / (
        display_max - display_min
    )
    normalized = np.clip(normalized, 0.0, 1.0)
    return np.rint(normalized * 255.0).astype(np.uint8)


def resolve_display_range(
    display_min: float | None,
    display_max: float | None,
    selected_stack: ArrayLike,
) -> tuple[float, float]:
    """Use IMS ColorRange or fall back to min/max of the selected raw data."""

    if display_min is not None and display_max is not None and display_max > display_min:
        return float(display_min), float(display_max)
    stack = np.asarray(selected_stack)
    if stack.size == 0:
        raise ValueError("Cannot derive a display range from empty image data.")
    minimum = float(np.min(stack))
    maximum = float(np.max(stack))
    if maximum <= minimum:
        # A constant image has no meaningful linear range. One representable
        # intensity step keeps the result deterministic and black.
        maximum = minimum + 1.0
    return minimum, maximum
