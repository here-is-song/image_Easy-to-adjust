"""Editable calibration profile for the laboratory Olympus FV1200 objectives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectiveProfile:
    model: str
    magnification: float
    na: float
    immersion: str
    expected_z_spacing_um: float
    expected_pixel_size_um: float | None = None
    expected_fov_um: float | None = None


FV1200_OBJECTIVES: dict[str, ObjectiveProfile] = {
    "10X": ObjectiveProfile("UPLSAPO10X", 10, 0.40, "Dry", 4.770),
    "20X": ObjectiveProfile("UPLSAPO20X", 20, 0.75, "Dry", 1.024),
    "30X": ObjectiveProfile("UPLSAPO30XS", 30, 1.05, "Silicone Oil", 0.870),
    "60X": ObjectiveProfile("UPLSAPO60XS", 60, 1.30, "Silicone Oil", 0.500),
}

HIGH_CONFIDENCE_MAX_ERROR = 0.03
AUTO_CONFIRM_MAX_ERROR = 0.07
AMBIGUITY_ERROR_MARGIN = 0.05
