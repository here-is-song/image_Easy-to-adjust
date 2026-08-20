from dataclasses import replace

import pytest

from iea.fv1200_calibration import FV1200_OBJECTIVES
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
        voxel_size_x_um=FV1200_OBJECTIVES["30X"].expected_fov_um / metadata.size_x,
        voxel_size_y_um=FV1200_OBJECTIVES["30X"].expected_fov_um / metadata.size_y,
        extent_x_um=FV1200_OBJECTIVES["30X"].expected_fov_um,
        extent_y_um=FV1200_OBJECTIVES["30X"].expected_fov_um,
        acquisition=replace(
            metadata.acquisition,
            objective_name="UPLSAPO30XS",
            objective_magnification=30.0,
            scan_zoom=1.0,
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


@pytest.mark.parametrize(
    ("objective_key", "scan_zoom"),
    [("10X", 1.0), ("20X", 1.0), ("30X", 2.0), ("60X", 1.5)],
)
def test_xy_scale_and_image_size_detect_objective_without_z_stack(objective_key, scan_zoom):
    expected_fov = FV1200_OBJECTIVES[objective_key].expected_fov_um
    assert expected_fov is not None
    width = 1024
    height = 768
    pixel_size = expected_fov / scan_zoom / width

    result = detect_objective(
        None,
        pixel_size_x_um=pixel_size,
        pixel_size_y_um=pixel_size,
        image_width_px=width,
        image_height_px=height,
        scan_zoom=scan_zoom,
    )

    assert result.objective_key == objective_key
    assert result.confidence == "High"
    assert result.detection_source == "XY FOV"
    assert result.normalized_fov_um == pytest.approx(expected_fov)
    assert result.xy_relative_error == pytest.approx(0.0)


def test_single_layer_metadata_uses_xy_fov_instead_of_z_extent(sample_ims):
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    expected_fov = FV1200_OBJECTIVES["20X"].expected_fov_um
    assert expected_fov is not None
    single_layer = replace(
        metadata,
        size_z=1,
        voxel_size_x_um=expected_fov / metadata.size_x,
        voxel_size_y_um=expected_fov / metadata.size_y,
        extent_x_um=expected_fov,
        extent_y_um=expected_fov,
        acquisition=replace(
            metadata.acquisition,
            objective_name=None,
            objective_magnification=None,
            scan_zoom=1.0,
        ),
        objective_detection=None,
    )

    result = detect_objective(single_layer)

    assert result.objective_key == "20X"
    assert result.detection_source == "XY FOV"
    assert result.measured_z_spacing_um is None


def test_xy_detection_requires_physical_scale_and_scan_zoom():
    expected_fov = FV1200_OBJECTIVES["20X"].expected_fov_um
    assert expected_fov is not None
    pixel_size = expected_fov / 1024

    missing_zoom = detect_objective(
        None,
        pixel_size_x_um=pixel_size,
        image_width_px=1024,
    )
    pixels_only = detect_objective(
        None,
        image_width_px=1024,
        image_height_px=1024,
        scan_zoom=1.0,
    )

    assert missing_zoom.objective_key is None
    assert "ScanZoom is missing" in (missing_zoom.warning or "")
    assert pixels_only.objective_key is None
    assert "physical pixel size" in (pixels_only.warning or "")


def test_z_spacing_keeps_priority_when_xy_fov_conflicts():
    expected_60x_fov = FV1200_OBJECTIVES["60X"].expected_fov_um
    assert expected_60x_fov is not None

    result = detect_objective(
        None,
        z_spacing_um=1.024,
        pixel_size_x_um=expected_60x_fov / 1024,
        image_width_px=1024,
        scan_zoom=1.0,
    )

    assert result.objective_key == "20X"
    assert result.confidence == "Medium"
    assert result.detection_source == "Z-spacing"
    assert "XY FOV suggests 60X" in (result.warning or "")


def test_manual_selection_overrides_but_preserves_detected_result():
    detected = detect_objective(None, z_spacing_um=0.870)

    selected = apply_manual_objective(detected, "60X")

    assert detected.objective_key == "30X"
    assert selected.objective_key == "60X"
    assert selected.detection_source == "Manual"
    assert selected.confidence == "Manual"
    assert selected.warning is not None
