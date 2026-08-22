from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np

from iea.dataset_loader import open_microscopy_dataset
from iea.image_dataset import DisplaySettings, ImageDataset
from iea.memory_backend import MemoryPixelBackend
from iea.models import ChannelMetadata, IMSMetadata


def make_memory_dataset(data: np.ndarray, path: Path | None = None) -> ImageDataset:
    channel_count = data.shape[1]
    channels = tuple(
        ChannelMetadata(
            index=index,
            name=f"Channel {index}",
            color=((0.0, 1.0, 0.0), (1.0, 0.0, 1.0))[index % 2],
            display_min=0.0,
            display_max=float(np.max(data[:, index])) or 1.0,
            display_gamma=1.0,
            dataset_path="",
            axis_order=("Z", "Y", "X"),
        )
        for index in range(channel_count)
    )
    metadata = IMSMetadata(
        source_path=path or Path("memory.ims"),
        size_x=data.shape[4],
        size_y=data.shape[3],
        size_z=data.shape[2],
        voxel_size_x_um=0.5,
        voxel_size_y_um=0.5,
        voxel_size_z_um=1.5,
        origin_x_um=0.0,
        origin_y_um=0.0,
        origin_z_um=0.0,
        extent_x_um=data.shape[4] * 0.5,
        extent_y_um=data.shape[3] * 0.5,
        extent_z_um=data.shape[2] * 1.5,
        unit="um",
        dtype=str(data.dtype),
        time_point_count=data.shape[0],
        channels=channels,
    )
    return ImageDataset(MemoryPixelBackend(data, metadata, path or "memory.ims"), "MEMORY").open()


def test_common_dataset_reads_blocks_and_chunked_mip() -> None:
    data = np.arange(1 * 2 * 5 * 4 * 3, dtype=np.uint16).reshape((1, 2, 5, 4, 3))
    dataset = make_memory_dataset(data)

    block = dataset.get_block(0, 1, 1, 4, 1, 4, 0, 2)
    projection, data_min, data_max = dataset.project_z_range(1, 1, 5, chunk_depth=2)

    np.testing.assert_array_equal(block, data[0, 1, 1:4, 1:4, 0:2])
    np.testing.assert_array_equal(projection, np.max(data[0, 1], axis=0))
    assert data_min == float(np.min(data[0, 1]))
    assert data_max == float(np.max(data[0, 1]))


def test_display_settings_never_modify_raw_voxels() -> None:
    data = np.arange(24, dtype=np.uint16).reshape((1, 1, 2, 3, 4))
    original = data.copy()
    dataset = make_memory_dataset(data)

    dataset.apply_display_settings(
        (DisplaySettings(3.0, 20.0, 0.7, (0.0, 1.0, 0.0), source="TEST"),)
    )

    np.testing.assert_array_equal(dataset.get_channel(0), original[0, 0])
    np.testing.assert_array_equal(data, original)
    assert dataset.metadata is not None
    assert dataset.metadata.channels[0].display_gamma == 0.7


def test_ims_pyramid_selects_the_smallest_level_that_covers_the_viewport(
    sample_ims: Path,
) -> None:
    with h5py.File(sample_ims, "r+") as h5_file:
        channel = h5_file.create_group("DataSet/ResolutionLevel 1/TimePoint 0/Channel 0")
        channel.attrs["ImageSizeX"] = np.bytes_("3")
        channel.attrs["ImageSizeY"] = np.bytes_("2")
        channel.attrs["ImageSizeZ"] = np.bytes_("2")
        low_resolution = np.asarray(
            [
                [[1, 2, 3], [4, 5, 6]],
                [[7, 8, 9], [10, 11, 12]],
            ],
            dtype=np.uint16,
        )
        channel.create_dataset("Data", data=low_resolution)

    with open_microscopy_dataset(sample_ims) as session:
        dataset = session.dataset
        levels = dataset.resolution_levels()
        low_level = dataset.choose_resolution_level(3, 2)
        full_level = dataset.choose_resolution_level(4, 3)
        projection, data_min, data_max = dataset.project_z_range_at_resolution(
            0,
            1,
            3,
            low_level,
        )

    assert [(level.index, level.size_x, level.size_y, level.size_z) for level in levels] == [
        (0, 5, 4, 3),
        (1, 3, 2, 2),
    ]
    assert low_level.index == 1
    assert full_level.index == 0
    np.testing.assert_array_equal(projection, np.max(low_resolution, axis=0))
    assert data_min == 1.0
    assert data_max == 12.0
