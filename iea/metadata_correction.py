"""Apply user-entered physical calibration without modifying source files."""

from __future__ import annotations

from dataclasses import replace

from .models import IMSMetadata, MetadataCorrection
from .objective_detector import detect_objective


def apply_metadata_correction(
    metadata: IMSMetadata,
    correction: MetadataCorrection | None,
) -> IMSMetadata:
    """Return effective metadata with corrected physical dimensions."""

    if correction is None or correction.is_empty:
        return metadata
    width_um = correction.physical_width_um
    height_um = correction.physical_height_um
    z_spacing_um = correction.z_spacing_um
    corrected = replace(
        metadata,
        voxel_size_x_um=(width_um / metadata.size_x if width_um is not None else metadata.voxel_size_x_um),
        voxel_size_y_um=(height_um / metadata.size_y if height_um is not None else metadata.voxel_size_y_um),
        voxel_size_z_um=(z_spacing_um if z_spacing_um is not None else metadata.voxel_size_z_um),
        extent_x_um=(width_um if width_um is not None else metadata.extent_x_um),
        extent_y_um=(height_um if height_um is not None else metadata.extent_y_um),
        extent_z_um=(
            z_spacing_um * metadata.size_z if z_spacing_um is not None else metadata.extent_z_um
        ),
        objective_detection=None,
    )
    return replace(corrected, objective_detection=detect_objective(corrected))
