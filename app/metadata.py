"""Helpers for normalizing the many attribute encodings found in IMS files."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import numpy as np


def normalize_attribute(value: Any) -> Any:
    """Convert HDF5 attribute values into plain Python values.

    Imaris files in the wild use bytes, strings, NumPy scalars, and arrays of
    one-byte characters for the same logical fields. This function provides a
    single conversion point for the reader.
    """

    if isinstance(value, np.generic):
        return normalize_attribute(value.item())
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    if isinstance(value, str):
        return value.rstrip("\x00")
    if isinstance(value, np.ndarray):
        flat = value.reshape(-1)
        if flat.size == 0:
            return []
        converted = [normalize_attribute(item) for item in flat]
        if len(converted) == 1:
            return converted[0]
        if all(isinstance(item, str) and len(item) <= 1 for item in converted):
            return "".join(converted).rstrip("\x00")
        return converted
    if isinstance(value, (list, tuple)):
        return [normalize_attribute(item) for item in value]
    return value


def get_attribute(attributes: Mapping[str, Any], *names: str) -> Any | None:
    """Return an attribute by case-insensitive name."""

    lookup = {str(key).casefold(): key for key in attributes.keys()}
    for name in names:
        key = lookup.get(name.casefold())
        if key is not None:
            return normalize_attribute(attributes[key])
    return None


def parse_number_list(value: Any) -> list[float]:
    """Parse a numeric scalar/list or a whitespace-delimited string."""

    normalized = normalize_attribute(value)
    if normalized is None:
        return []
    if isinstance(normalized, (int, float)):
        return [float(normalized)]
    if isinstance(normalized, list):
        numbers: list[float] = []
        for item in normalized:
            numbers.extend(parse_number_list(item))
        return numbers
    if isinstance(normalized, str):
        tokens = re.split(r"[\s,;]+", normalized.strip())
        try:
            return [float(token) for token in tokens if token]
        except ValueError:
            return []
    return []


def parse_int(value: Any) -> int | None:
    """Parse one integer-like metadata value."""

    numbers = parse_number_list(value)
    if not numbers:
        return None
    number = numbers[0]
    if not np.isfinite(number) or number <= 0 or not float(number).is_integer():
        return None
    return int(number)


def unit_scale_to_um(unit: str) -> float | None:
    """Return the conversion factor from a common length unit to micrometres."""

    compact = unit.strip().casefold().replace("μ", "u").replace("µ", "u")
    factors = {
        "um": 1.0,
        "micrometer": 1.0,
        "micrometers": 1.0,
        "micrometre": 1.0,
        "micrometres": 1.0,
        "nm": 0.001,
        "mm": 1000.0,
        "m": 1_000_000.0,
    }
    return factors.get(compact)
