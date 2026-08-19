"""Conservative objective detection for the calibrated laboratory FV1200."""

from __future__ import annotations

import logging
import math
import re

from .fv1200_calibration import (
    AMBIGUITY_ERROR_MARGIN,
    AUTO_CONFIRM_MAX_ERROR,
    FV1200_OBJECTIVES,
    HIGH_CONFIDENCE_MAX_ERROR,
    ObjectiveProfile,
)
from .models import IMSMetadata, ObjectiveDetectionResult

LOGGER = logging.getLogger(__name__)


def _unknown_result(
    measured_z_spacing_um: float | None,
    source: str,
    warning: str | None,
) -> ObjectiveDetectionResult:
    return ObjectiveDetectionResult(
        objective_key=None,
        model=None,
        magnification=None,
        na=None,
        immersion=None,
        measured_z_spacing_um=measured_z_spacing_um,
        expected_z_spacing_um=None,
        relative_error=None,
        confidence="Low",
        detection_source=source,
        warning=warning,
    )


def _result_from_profile(
    key: str,
    profile: ObjectiveProfile,
    measured_z_spacing_um: float | None,
    confidence: str,
    source: str,
    warning: str | None = None,
) -> ObjectiveDetectionResult:
    relative_error = (
        abs(measured_z_spacing_um - profile.expected_z_spacing_um) / profile.expected_z_spacing_um
        if measured_z_spacing_um is not None
        else None
    )
    return ObjectiveDetectionResult(
        objective_key=key,
        model=profile.model,
        magnification=profile.magnification,
        na=profile.na,
        immersion=profile.immersion,
        measured_z_spacing_um=measured_z_spacing_um,
        expected_z_spacing_um=profile.expected_z_spacing_um,
        relative_error=relative_error,
        confidence=confidence,
        detection_source=source,
        warning=warning,
    )


def _explicit_objective_key(metadata: IMSMetadata | None) -> str | None:
    if metadata is None:
        return None
    acquisition = metadata.acquisition
    magnification = acquisition.objective_magnification
    if magnification is not None:
        for key, profile in FV1200_OBJECTIVES.items():
            if math.isclose(magnification, profile.magnification, rel_tol=0.0, abs_tol=0.1):
                return key

    normalized_name = re.sub(r"[^A-Z0-9]", "", (acquisition.objective_name or "").upper())
    if not normalized_name:
        return None
    for key, profile in FV1200_OBJECTIVES.items():
        normalized_model = re.sub(r"[^A-Z0-9]", "", profile.model.upper())
        if normalized_model in normalized_name or key in normalized_name:
            return key
    return None


def _valid_z_spacing(value: float | None) -> float | None:
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def detect_objective(
    metadata: IMSMetadata | None,
    z_spacing_um: float | None = None,
    pixel_size_x_um: float | None = None,
    pixel_size_y_um: float | None = None,
    image_width_px: int | None = None,
    image_height_px: int | None = None,
) -> ObjectiveDetectionResult:
    """Detect one calibrated FV1200 objective without forcing an unreliable match.

    XY arguments are intentionally reserved for future calibration. Until the
    calibration profile contains XY targets they do not alter the result.
    """

    del pixel_size_x_um, pixel_size_y_um, image_width_px, image_height_px
    measured_z = _valid_z_spacing(z_spacing_um)
    if measured_z is None and metadata is not None:
        measured_z = _valid_z_spacing(metadata.voxel_size_z_um)

    explicit_key = _explicit_objective_key(metadata)
    if explicit_key is not None:
        profile = FV1200_OBJECTIVES[explicit_key]
        warning = None
        if measured_z is not None:
            error = abs(measured_z - profile.expected_z_spacing_um) / profile.expected_z_spacing_um
            if error > AUTO_CONFIRM_MAX_ERROR:
                warning = (
                    f"Z-spacing {measured_z:.6g} µm is inconsistent with the calibrated "
                    f"{explicit_key} value {profile.expected_z_spacing_um:.6g} µm."
                )
        return _result_from_profile(explicit_key, profile, measured_z, "High", "Metadata", warning)

    if measured_z is None:
        return _unknown_result(None, "None", "No valid objective metadata or Z-spacing is available.")

    candidates = sorted(
        (
            (abs(measured_z - profile.expected_z_spacing_um) / profile.expected_z_spacing_um, key, profile)
            for key, profile in FV1200_OBJECTIVES.items()
        ),
        key=lambda item: item[0],
    )
    LOGGER.debug("[ObjectiveDetector] measured Z spacing: %.6g µm", measured_z)
    for error, key, _profile in candidates:
        LOGGER.debug("[ObjectiveDetector] candidate %s relative error: %.2f%%", key, error * 100.0)

    best_error, best_key, best_profile = candidates[0]
    second_error = candidates[1][0]
    if best_error > AUTO_CONFIRM_MAX_ERROR:
        return _unknown_result(
            measured_z,
            "Z-spacing",
            f"No FV1200 calibration profile is within 7% of Z-spacing {measured_z:.6g} µm.",
        )

    confidence = "High" if best_error <= HIGH_CONFIDENCE_MAX_ERROR else "Medium"
    warning = None
    if second_error - best_error < AMBIGUITY_ERROR_MARGIN:
        if confidence == "High":
            confidence = "Medium"
            warning = "The best and second-best Z-spacing candidates are close; confidence was reduced."
        else:
            return _unknown_result(
                measured_z,
                "Z-spacing",
                "The best and second-best Z-spacing candidates are too close; manual selection is required.",
            )

    result = _result_from_profile(best_key, best_profile, measured_z, confidence, "Z-spacing", warning)
    LOGGER.debug(
        "[ObjectiveDetector] selected=%s confidence=%s source=%s",
        result.objective_key,
        result.confidence,
        result.detection_source,
    )
    return result


def apply_manual_objective(
    detected: ObjectiveDetectionResult,
    objective_key: str | None,
) -> ObjectiveDetectionResult:
    """Return the auto result or a traceable manual override without editing metadata."""

    if objective_key is None:
        return detected
    if objective_key == "Unknown":
        return _unknown_result(detected.measured_z_spacing_um, "Manual", "Objective was manually set to Unknown.")
    profile = FV1200_OBJECTIVES.get(objective_key)
    if profile is None:
        raise ValueError(f"Unknown FV1200 objective selection: {objective_key}")
    warning = None
    measured_z = detected.measured_z_spacing_um
    if measured_z is not None:
        error = abs(measured_z - profile.expected_z_spacing_um) / profile.expected_z_spacing_um
        if error > AUTO_CONFIRM_MAX_ERROR:
            warning = f"Manual selection {objective_key} differs from its calibrated Z-spacing by {error * 100:.2f}%."
    return _result_from_profile(objective_key, profile, measured_z, "Manual", "Manual", warning)
