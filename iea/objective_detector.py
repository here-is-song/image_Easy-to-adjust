"""Conservative objective detection for the calibrated laboratory FV1200."""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, replace

from .fv1200_calibration import (
    AMBIGUITY_ERROR_MARGIN,
    AUTO_CONFIRM_MAX_ERROR,
    FV1200_OBJECTIVES,
    HIGH_CONFIDENCE_MAX_ERROR,
    ObjectiveProfile,
)
from .models import IMSMetadata, ObjectiveDetectionResult

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _XYEvidence:
    """Physical image size normalized to the calibration's ScanZoom 1.0."""

    fov_x_um: float | None
    fov_y_um: float | None
    scan_zoom: float | None
    normalized_fov_um: float | None


def _unknown_result(
    measured_z_spacing_um: float | None,
    source: str,
    warning: str | None,
    xy: _XYEvidence | None = None,
) -> ObjectiveDetectionResult:
    evidence = xy or _XYEvidence(None, None, None, None)
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
        measured_fov_x_um=evidence.fov_x_um,
        measured_fov_y_um=evidence.fov_y_um,
        scan_zoom=evidence.scan_zoom,
        normalized_fov_um=evidence.normalized_fov_um,
    )


def _result_from_profile(
    key: str,
    profile: ObjectiveProfile,
    measured_z_spacing_um: float | None,
    confidence: str,
    source: str,
    warning: str | None = None,
    xy: _XYEvidence | None = None,
    xy_relative_error: float | None = None,
) -> ObjectiveDetectionResult:
    evidence = xy or _XYEvidence(None, None, None, None)
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
        measured_fov_x_um=evidence.fov_x_um,
        measured_fov_y_um=evidence.fov_y_um,
        scan_zoom=evidence.scan_zoom,
        normalized_fov_um=evidence.normalized_fov_um,
        expected_fov_um=profile.expected_fov_um,
        xy_relative_error=xy_relative_error,
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


def _valid_positive(value: float | int | None) -> float | None:
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    return numeric


def _join_warnings(*warnings: str | None) -> str | None:
    messages = [warning for warning in warnings if warning]
    return " ".join(messages) or None


def _xy_evidence(
    metadata: IMSMetadata | None,
    pixel_size_x_um: float | None,
    pixel_size_y_um: float | None,
    image_width_px: int | None,
    image_height_px: int | None,
    scan_zoom: float | None,
) -> _XYEvidence:
    pixel_x = _valid_positive(pixel_size_x_um)
    pixel_y = _valid_positive(pixel_size_y_um)
    width = _valid_positive(image_width_px)
    height = _valid_positive(image_height_px)
    zoom = _valid_positive(scan_zoom)
    if metadata is not None:
        pixel_x = pixel_x or _valid_positive(metadata.voxel_size_x_um)
        pixel_y = pixel_y or _valid_positive(metadata.voxel_size_y_um)
        width = width or _valid_positive(metadata.size_x)
        height = height or _valid_positive(metadata.size_y)
        zoom = zoom or _valid_positive(metadata.acquisition.scan_zoom)

    fov_x = pixel_x * width if pixel_x is not None and width is not None else None
    fov_y = pixel_y * height if pixel_y is not None and height is not None else None
    measured_axes = [value for value in (fov_x, fov_y) if value is not None]
    # The calibration represents the full/long scan axis at ScanZoom 1.0.
    normalized_fov = max(measured_axes) * zoom if measured_axes and zoom is not None else None
    return _XYEvidence(fov_x, fov_y, zoom, normalized_fov)


def _xy_relative_error(profile: ObjectiveProfile, xy: _XYEvidence) -> float | None:
    if xy.normalized_fov_um is None or profile.expected_fov_um is None:
        return None
    return abs(xy.normalized_fov_um - profile.expected_fov_um) / profile.expected_fov_um


def _detect_from_z(measured_z: float) -> ObjectiveDetectionResult:
    candidates = sorted(
        (
            (abs(measured_z - profile.expected_z_spacing_um) / profile.expected_z_spacing_um, key, profile)
            for key, profile in FV1200_OBJECTIVES.items()
        ),
        key=lambda item: item[0],
    )
    LOGGER.debug("[ObjectiveDetector] measured Z spacing: %.6g µm", measured_z)
    for error, key, _profile in candidates:
        LOGGER.debug("[ObjectiveDetector] Z candidate %s relative error: %.2f%%", key, error * 100.0)

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
    return _result_from_profile(best_key, best_profile, measured_z, confidence, "Z-spacing", warning)


def _detect_from_xy(measured_z: float | None, xy: _XYEvidence) -> ObjectiveDetectionResult:
    if xy.fov_x_um is None and xy.fov_y_um is None:
        return _unknown_result(
            measured_z,
            "None",
            "No valid XY physical pixel size and image dimensions are available.",
            xy,
        )
    if xy.scan_zoom is None:
        return _unknown_result(
            measured_z,
            "XY FOV",
            "XY physical size is available, but ScanZoom is missing; objective cannot be distinguished safely.",
            xy,
        )
    if xy.normalized_fov_um is None:
        return _unknown_result(measured_z, "XY FOV", "A normalized XY field of view could not be calculated.", xy)

    candidates = sorted(
        (
            (abs(xy.normalized_fov_um - profile.expected_fov_um) / profile.expected_fov_um, key, profile)
            for key, profile in FV1200_OBJECTIVES.items()
            if profile.expected_fov_um is not None
        ),
        key=lambda item: item[0],
    )
    if not candidates:
        return _unknown_result(measured_z, "XY FOV", "The FV1200 profile has no XY FOV calibration.", xy)

    LOGGER.debug(
        "[ObjectiveDetector] XY FOV: x=%s µm y=%s µm zoom=%s normalized=%.6g µm",
        xy.fov_x_um,
        xy.fov_y_um,
        xy.scan_zoom,
        xy.normalized_fov_um,
    )
    for error, key, _profile in candidates:
        LOGGER.debug("[ObjectiveDetector] XY candidate %s relative error: %.2f%%", key, error * 100.0)

    best_error, best_key, best_profile = candidates[0]
    second_error = candidates[1][0] if len(candidates) > 1 else math.inf
    if best_error > AUTO_CONFIRM_MAX_ERROR:
        return _unknown_result(
            measured_z,
            "XY FOV",
            f"No FV1200 calibration profile is within 7% of normalized XY FOV {xy.normalized_fov_um:.6g} µm.",
            xy,
        )

    confidence = "High" if best_error <= HIGH_CONFIDENCE_MAX_ERROR else "Medium"
    warning = None
    if second_error - best_error < AMBIGUITY_ERROR_MARGIN:
        if confidence == "High":
            confidence = "Medium"
            warning = "The best and second-best XY FOV candidates are close; confidence was reduced."
        else:
            return _unknown_result(
                measured_z,
                "XY FOV",
                "The best and second-best XY FOV candidates are too close; manual selection is required.",
                xy,
            )
    return _result_from_profile(
        best_key,
        best_profile,
        measured_z,
        confidence,
        "XY FOV",
        warning,
        xy,
        best_error,
    )


def detect_objective(
    metadata: IMSMetadata | None,
    z_spacing_um: float | None = None,
    pixel_size_x_um: float | None = None,
    pixel_size_y_um: float | None = None,
    image_width_px: int | None = None,
    image_height_px: int | None = None,
    scan_zoom: float | None = None,
) -> ObjectiveDetectionResult:
    """Detect one calibrated FV1200 objective from metadata, Z spacing, then XY FOV."""

    single_layer = metadata is not None and metadata.size_z == 1
    measured_z = None if single_layer else _valid_z_spacing(z_spacing_um)
    if measured_z is None and metadata is not None and not single_layer:
        measured_z = _valid_z_spacing(metadata.voxel_size_z_um)
    xy = _xy_evidence(
        metadata,
        pixel_size_x_um,
        pixel_size_y_um,
        image_width_px,
        image_height_px,
        scan_zoom,
    )
    xy_result = _detect_from_xy(measured_z, xy)

    explicit_key = _explicit_objective_key(metadata)
    if explicit_key is not None:
        profile = FV1200_OBJECTIVES[explicit_key]
        z_warning = None
        if measured_z is not None:
            error = abs(measured_z - profile.expected_z_spacing_um) / profile.expected_z_spacing_um
            if error > AUTO_CONFIRM_MAX_ERROR:
                z_warning = (
                    f"Z-spacing {measured_z:.6g} µm is inconsistent with the calibrated "
                    f"{explicit_key} value {profile.expected_z_spacing_um:.6g} µm."
                )
        xy_error = _xy_relative_error(profile, xy)
        xy_warning = None
        if xy_error is not None and xy_error > AUTO_CONFIRM_MAX_ERROR:
            xy_warning = (
                f"Normalized XY FOV {xy.normalized_fov_um:.6g} µm is inconsistent with the calibrated "
                f"{explicit_key} value {profile.expected_fov_um:.6g} µm."
            )
        return _result_from_profile(
            explicit_key,
            profile,
            measured_z,
            "High",
            "Metadata",
            _join_warnings(z_warning, xy_warning),
            xy,
            xy_error,
        )

    z_result = _detect_from_z(measured_z) if measured_z is not None else None
    if z_result is not None and z_result.objective_key is not None:
        if xy_result.objective_key == z_result.objective_key:
            confidence = (
                "High" if z_result.confidence == "High" and xy_result.confidence == "High" else "Medium"
            )
            result = replace(
                z_result,
                confidence=confidence,
                detection_source="Z-spacing + XY FOV",
                warning=_join_warnings(z_result.warning, xy_result.warning),
                measured_fov_x_um=xy_result.measured_fov_x_um,
                measured_fov_y_um=xy_result.measured_fov_y_um,
                scan_zoom=xy_result.scan_zoom,
                normalized_fov_um=xy_result.normalized_fov_um,
                expected_fov_um=xy_result.expected_fov_um,
                xy_relative_error=xy_result.xy_relative_error,
            )
        elif xy_result.objective_key is not None:
            conflict = (
                f"Z-spacing suggests {z_result.objective_key}, but normalized XY FOV suggests "
                f"{xy_result.objective_key}; verify the objective manually."
            )
            result = replace(
                z_result,
                confidence="Medium",
                warning=_join_warnings(z_result.warning, conflict),
                measured_fov_x_um=xy_result.measured_fov_x_um,
                measured_fov_y_um=xy_result.measured_fov_y_um,
                scan_zoom=xy_result.scan_zoom,
                normalized_fov_um=xy_result.normalized_fov_um,
                expected_fov_um=FV1200_OBJECTIVES[z_result.objective_key].expected_fov_um,
                xy_relative_error=_xy_relative_error(FV1200_OBJECTIVES[z_result.objective_key], xy),
            )
        else:
            result = replace(
                z_result,
                measured_fov_x_um=xy.fov_x_um,
                measured_fov_y_um=xy.fov_y_um,
                scan_zoom=xy.scan_zoom,
                normalized_fov_um=xy.normalized_fov_um,
            )
        LOGGER.debug(
            "[ObjectiveDetector] selected=%s confidence=%s source=%s",
            result.objective_key,
            result.confidence,
            result.detection_source,
        )
        return result

    if xy_result.objective_key is not None:
        if z_result is not None and z_result.warning:
            return replace(xy_result, warning=_join_warnings(z_result.warning, xy_result.warning))
        return xy_result

    if single_layer:
        reason = "Single-layer image: " + (xy_result.warning or "XY FOV evidence is unavailable.")
        result = _unknown_result(None, xy_result.detection_source, reason, xy)
    elif z_result is not None:
        result = replace(
            z_result,
            warning=_join_warnings(z_result.warning, xy_result.warning),
            measured_fov_x_um=xy.fov_x_um,
            measured_fov_y_um=xy.fov_y_um,
            scan_zoom=xy.scan_zoom,
            normalized_fov_um=xy.normalized_fov_um,
        )
    else:
        result = _unknown_result(
            None,
            xy_result.detection_source,
            _join_warnings("No valid objective metadata or Z-spacing is available.", xy_result.warning),
            xy,
        )
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
    xy = _XYEvidence(
        detected.measured_fov_x_um,
        detected.measured_fov_y_um,
        detected.scan_zoom,
        detected.normalized_fov_um,
    )
    if objective_key == "Unknown":
        return _unknown_result(
            detected.measured_z_spacing_um,
            "Manual",
            "Objective was manually set to Unknown.",
            xy,
        )
    profile = FV1200_OBJECTIVES.get(objective_key)
    if profile is None:
        raise ValueError(f"Unknown FV1200 objective selection: {objective_key}")
    z_warning = None
    measured_z = detected.measured_z_spacing_um
    if measured_z is not None:
        error = abs(measured_z - profile.expected_z_spacing_um) / profile.expected_z_spacing_um
        if error > AUTO_CONFIRM_MAX_ERROR:
            z_warning = (
                f"Manual selection {objective_key} differs from its calibrated Z-spacing by {error * 100:.2f}%."
            )
    xy_error = _xy_relative_error(profile, xy)
    xy_warning = None
    if xy_error is not None and xy_error > AUTO_CONFIRM_MAX_ERROR:
        xy_warning = f"Manual selection {objective_key} differs from its calibrated XY FOV by {xy_error * 100:.2f}%."
    return _result_from_profile(
        objective_key,
        profile,
        measured_z,
        "Manual",
        "Manual",
        _join_warnings(z_warning, xy_warning),
        xy,
        xy_error,
    )
