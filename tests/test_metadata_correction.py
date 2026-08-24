from __future__ import annotations

from iea.ims_reader import IMSReader
from iea.metadata_correction import apply_metadata_correction
from iea.models import MetadataCorrection


def test_physical_correction_changes_calibration_but_never_pixel_shape(sample_ims) -> None:
    with IMSReader(sample_ims) as reader:
        source = reader.metadata
    assert source is not None
    original_values = (
        source.size_x,
        source.size_y,
        source.size_z,
        source.extent_x_um,
        source.voxel_size_x_um,
    )
    correction = MetadataCorrection(
        physical_width_um=500.0,
        physical_height_um=320.0,
        z_spacing_um=4.0,
    )

    corrected = apply_metadata_correction(source, correction)

    assert (corrected.size_x, corrected.size_y, corrected.size_z) == (
        source.size_x,
        source.size_y,
        source.size_z,
    )
    assert corrected.extent_x_um == 500.0
    assert corrected.extent_y_um == 320.0
    assert corrected.voxel_size_x_um == 500.0 / source.size_x
    assert corrected.voxel_size_y_um == 320.0 / source.size_y
    assert corrected.voxel_size_z_um == 4.0
    assert corrected.extent_z_um == 4.0 * source.size_z
    assert (
        source.size_x,
        source.size_y,
        source.size_z,
        source.extent_x_um,
        source.voxel_size_x_um,
    ) == original_values


def test_empty_correction_returns_original_metadata_object(sample_ims) -> None:
    with IMSReader(sample_ims) as reader:
        source = reader.metadata
    assert source is not None

    assert apply_metadata_correction(source, MetadataCorrection()) is source
