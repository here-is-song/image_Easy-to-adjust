"""Pseudocolor and additive merge operations."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from numpy.typing import ArrayLike, NDArray


def convert_red_to_magenta(
    color: tuple[float, float, float], enabled: bool = True
) -> tuple[float, float, float]:
    """Convert red-like colors to magenta using the Phase 1 threshold."""

    r, g, b = color
    if enabled and r >= 0.8 and g <= 0.25 and b <= 0.25:
        return (1.0, 0.0, 1.0)
    return color


def apply_pseudocolor(
    grayscale: ArrayLike, color: tuple[float, float, float]
) -> NDArray[np.float32]:
    """Colorize a uint8 grayscale image as float RGB in the range 0..1."""

    intensity = np.asarray(grayscale, dtype=np.float32)
    if intensity.ndim != 2:
        raise ValueError("Pseudocolor input must be a 2D grayscale image.")
    rgb_color = np.clip(np.asarray(color, dtype=np.float32), 0.0, 1.0)
    return (intensity[..., None] / 255.0) * rgb_color


def additive_merge(images: Iterable[ArrayLike]) -> NDArray[np.uint8]:
    """Add float RGB channel images, clip to 0..1, and return uint8 RGB."""

    image_list = [np.asarray(image, dtype=np.float32) for image in images]
    if not image_list:
        raise ValueError("At least one pseudocolor image is required for a merge.")
    expected_shape = image_list[0].shape
    if len(expected_shape) != 3 or expected_shape[-1] != 3:
        raise ValueError("Merge inputs must have shape Y, X, 3.")
    if any(image.shape != expected_shape for image in image_list[1:]):
        raise ValueError("All merge inputs must have the same shape.")
    merged = np.sum(image_list, axis=0, dtype=np.float32)
    return np.rint(np.clip(merged, 0.0, 1.0) * 255.0).astype(np.uint8)
