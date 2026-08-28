from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile

from iea.dataset_loader import open_microscopy_dataset
from iea.exporter import format_ppt_summary
from iea.models import ExportSettings, ScaleBarSettings


def test_plain_tiff_uses_mvx10_defaults_and_resolution_tags(tmp_path: Path) -> None:
    path = tmp_path / "mvx10-sample.tif"
    pixels = np.arange(1024 * 1024, dtype=np.uint16).reshape(1024, 1024)
    tifffile.imwrite(
        path,
        pixels,
        photometric="minisblack",
        resolution=(100, 200),
        resolutionunit="CENTIMETER",
        metadata=None,
    )

    with open_microscopy_dataset(path) as session:
        metadata = session.dataset.metadata
        assert metadata is not None
        assert metadata.source_format == "TIFF"
        assert (metadata.size_x, metadata.size_y, metadata.size_z) == (1024, 1024, 1)
        assert metadata.voxel_size_x_um == 100.0
        assert metadata.voxel_size_y_um == 50.0
        assert metadata.acquisition.microscope_manufacturer == "Olympus"
        assert metadata.acquisition.microscope_model == "MVX10"
        assert metadata.acquisition.objective_name == "MV PLAPO 2XC"
        assert metadata.acquisition.scan_zoom == 1.25
        assert any("display/print DPI" in warning for warning in metadata.warnings)
        np.testing.assert_array_equal(session.dataset.get_plane(0, 0, 0), pixels)
        assert session.relationship.cache_path is None
        assert session.relationship.cache_status == "not_applicable"

        summary = format_ppt_summary(
            metadata,
            ExportSettings(
                z_start=1,
                z_end=1,
                channel_indices=(0,),
                scale_bar=ScaleBarSettings(enabled=False),
            ),
        )

    assert "Microscope: Olympus MVX10" in summary
    assert "Size: 1024×1024" in summary
    assert "Objective lens: MV PLAPO 2XC, Zoom: 1.25X, single-layer image;" in summary


def test_rgb_tiff_preserves_rgb_sample_order(tmp_path: Path) -> None:
    path = tmp_path / "rgb.tiff"
    pixels = np.zeros((4, 5, 3), dtype=np.uint8)
    pixels[..., 0] = np.arange(20, dtype=np.uint8).reshape(4, 5)
    pixels[..., 1] = 100
    pixels[..., 2] = 200
    tifffile.imwrite(path, pixels, photometric="rgb", metadata=None)

    with open_microscopy_dataset(path) as session:
        metadata = session.dataset.metadata
        assert metadata is not None
        assert metadata.channel_count == 3
        assert [channel.name for channel in metadata.channels] == ["Red", "Green", "Blue"]
        assert [channel.color for channel in metadata.channels] == [
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        ]
        for channel_index in range(3):
            np.testing.assert_array_equal(
                session.dataset.get_plane(0, channel_index, 0),
                pixels[..., channel_index],
            )


def test_ome_tiff_reads_channel_z_and_physical_metadata(tmp_path: Path) -> None:
    path = tmp_path / "multichannel.ome.tif"
    pixels = np.arange(2 * 3 * 4 * 5, dtype=np.uint16).reshape(2, 3, 4, 5)
    tifffile.imwrite(
        path,
        pixels,
        ome=True,
        photometric="minisblack",
        metadata={
            "axes": "CZYX",
            "Channel": {"Name": ["DAPI", "Marker"]},
            "PhysicalSizeX": 0.5,
            "PhysicalSizeXUnit": "µm",
            "PhysicalSizeY": 0.75,
            "PhysicalSizeYUnit": "µm",
            "PhysicalSizeZ": 2.0,
            "PhysicalSizeZUnit": "µm",
        },
    )

    with open_microscopy_dataset(path) as session:
        metadata = session.dataset.metadata
        assert metadata is not None
        assert (metadata.channel_count, metadata.size_z, metadata.size_y, metadata.size_x) == (2, 3, 4, 5)
        assert [channel.name for channel in metadata.channels] == ["DAPI", "Marker"]
        assert metadata.voxel_size_x_um == 0.5
        assert metadata.voxel_size_y_um == 0.75
        assert metadata.voxel_size_z_um == 2.0
        np.testing.assert_array_equal(session.dataset.get_channel(1), pixels[1])


def test_plain_multipage_tiff_is_treated_as_z_stack(tmp_path: Path) -> None:
    path = tmp_path / "stack.tif"
    pixels = np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5)
    tifffile.imwrite(path, pixels, photometric="minisblack", metadata=None)

    with open_microscopy_dataset(path) as session:
        metadata = session.dataset.metadata
        assert metadata is not None
        assert (metadata.channel_count, metadata.size_z) == (1, 3)
        np.testing.assert_array_equal(session.dataset.get_channel(0), pixels)
