from dataclasses import replace

import pytest

from iea.ims_reader import IMSReader
from iea.objective_detector import apply_manual_objective, detect_objective


@pytest.mark.parametrize(
    ("z_spacing", "expected_key"),
    [
        (4.770, "10X"),
        (1.024, "20X"),
        (0.870, "30X"),
        (0.500, "60X"),
        (0.503, "60X"),
        (0.895, "30X"),
    ],
)
def test_calibrated_z_spacing_detects_expected_objective(z_spacing, expected_key):
    result = detect_objective(None, z_spacing_um=z_spacing)

    assert result.objective_key == expected_key
    assert result.confidence == "High"
    assert result.detection_source == "Z-spacing"
    assert result.relative_error is not None


@pytest.mark.parametrize("z_spacing", [1.50, None, 0.0])
def test_invalid_or_uncalibrated_z_spacing_returns_unknown(z_spacing):
    result = detect_objective(None, z_spacing_um=z_spacing)

    assert result.objective_key is None
    assert result.confidence == "Low"


def test_ambiguous_20x_30x_boundary_requires_manual_selection():
    result = detect_objective(None, z_spacing_um=0.955)

    assert result.objective_key is None
    assert result.confidence == "Low"
    assert result.warning is not None
    assert "manual selection" in result.warning


def test_explicit_metadata_has_priority_over_z_spacing(sample_ims):
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    metadata_30x = replace(
        metadata,
        acquisition=replace(
            metadata.acquisition,
            objective_name="UPLSAPO30XS",
            objective_magnification=30.0,
        ),
        objective_detection=None,
    )

    result = detect_objective(metadata_30x, z_spacing_um=0.870)

    assert result.objective_key == "30X"
    assert result.confidence == "High"
    assert result.detection_source == "Metadata"
    assert result.warning is None


def test_metadata_z_spacing_conflict_keeps_metadata_and_warns(sample_ims):
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    metadata_60x = replace(
        metadata,
        acquisition=replace(
            metadata.acquisition,
            objective_name="UPLSAPO60XS",
            objective_magnification=60.0,
        ),
        objective_detection=None,
    )

    result = detect_objective(metadata_60x, z_spacing_um=4.770)

    assert result.objective_key == "60X"
    assert result.detection_source == "Metadata"
    assert result.warning is not None
    assert "inconsistent" in result.warning


def test_manual_selection_overrides_but_preserves_detected_result():
    detected = detect_objective(None, z_spacing_um=0.870)

    selected = apply_manual_objective(detected, "60X")

    assert detected.objective_key == "30X"
    assert selected.objective_key == "60X"
    assert selected.detection_source == "Manual"
    assert selected.confidence == "Manual"
    assert selected.warning is not None
