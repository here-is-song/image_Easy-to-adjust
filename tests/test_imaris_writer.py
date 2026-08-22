from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from iea.image_dataset import DisplaySettings
from iea.imaris_writer import IMSWriterBackend
from iea.ims_reader import IMSReader
from tests.test_image_dataset import make_memory_dataset


@pytest.mark.skipif(not IMSWriterBackend.is_available(), reason="PyImarisWriter is not installed")
def test_official_writer_round_trip_preserves_voxels_and_display_metadata(tmp_path: Path) -> None:
    raw = np.arange(2 * 2 * 3 * 7 * 9, dtype=np.uint16).reshape((2, 2, 3, 7, 9))
    dataset = make_memory_dataset(raw, tmp_path / "source.oib")
    settings = (
        DisplaySettings(11.0, 140.0, 0.8, (0.0, 1.0, 0.0), source="TEST"),
        DisplaySettings(22.0, 280.0, 1.3, (1.0, 0.0, 1.0), source="TEST"),
    )
    dataset.apply_display_settings(settings)
    output = tmp_path / "roundtrip.ims.tmp"

    result = IMSWriterBackend(block_xy=64, thread_count=1).write(dataset, output, settings)

    assert result.blocks_written == 12
    assert result.display_min_written
    assert result.display_max_written
    assert result.gamma_written
    with IMSReader(output) as reader:
        assert reader.metadata is not None
        assert reader.metadata.dtype == "uint16"
        assert reader.metadata.channel_count == 2
        assert reader.metadata.time_point_count == 2
        for channel_index in range(2):
            np.testing.assert_array_equal(reader.read_z_range(channel_index, 1, 3), raw[0, channel_index])
            channel = reader.metadata.channels[channel_index]
            assert channel.display_min == pytest.approx(settings[channel_index].minimum)
            assert channel.display_max == pytest.approx(settings[channel_index].maximum)
            assert channel.display_gamma == pytest.approx(settings[channel_index].gamma)
            assert channel.color == pytest.approx(settings[channel_index].color)
    with h5py.File(output, "r") as h5_file:
        second_timepoint = np.asarray(
            h5_file["DataSet/ResolutionLevel 0/TimePoint 1/Channel 1/Data"][:3, :7, :9]
        )
    np.testing.assert_array_equal(second_timepoint, raw[1, 1])
