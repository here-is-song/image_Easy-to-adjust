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


# Full-frame horizontal/long-axis field of view at ScanZoom 1.0. The XY
# calibration is anchored to the laboratory's known 20X reference image:
# 1024 px × 0.621000488 µm/px = 635.9045 µm. Other objectives are scaled by
# the inverse magnification ratio and remain editable here for later rechecks.
FV1200_OBJECTIVES: dict[str, ObjectiveProfile] = {
    "10X": ObjectiveProfile("UPLSAPO10X", 10, 0.40, "Dry", 4.770, expected_fov_um=1271.8090),
    "20X": ObjectiveProfile("UPLSAPO20X", 20, 0.75, "Dry", 1.024, expected_fov_um=635.9045),
    "30X": ObjectiveProfile("UPLSAPO30XS", 30, 1.05, "Silicone Oil", 0.870, expected_fov_um=423.9363),
    "60X": ObjectiveProfile("UPLSAPO60XS", 60, 1.30, "Silicone Oil", 0.500, expected_fov_um=211.9682),
}

HIGH_CONFIDENCE_MAX_ERROR = 0.03
AUTO_CONFIRM_MAX_ERROR = 0.07
AMBIGUITY_ERROR_MARGIN = 0.05
