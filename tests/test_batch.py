from dataclasses import replace

from iea.batch import adapt_settings_for_metadata
from iea.ims_reader import IMSReader
from iea.models import ChannelSelection, ExportSettings


def test_batch_channels_match_by_name_when_target_order_differs(sample_ims):
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    green, red = metadata.channels
    swapped_metadata = replace(
        metadata,
        channels=(
            replace(red, index=0),
            replace(green, index=1),
        ),
    )
    settings = ExportSettings(z_start=1, z_end=3, channel_indices=(0, 1))
    selections = (
        ChannelSelection(0, "Green", 2.0, 15.0),
        ChannelSelection(1, "Red/Marker", 1.0, 20.0),
    )

    matched = adapt_settings_for_metadata(settings, selections, swapped_metadata)

    assert matched.settings.channel_indices == (1, 0)
    assert matched.display_ranges == {1: (2.0, 15.0), 0: (1.0, 20.0)}
    assert not matched.warnings


def test_batch_reports_missing_channel_and_clamped_z_range(sample_ims):
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    settings = ExportSettings(z_start=2, z_end=99, channel_indices=(0, 1))
    selections = (
        ChannelSelection(0, "Green"),
        ChannelSelection(1, "Missing marker"),
    )

    matched = adapt_settings_for_metadata(settings, selections, metadata)

    assert matched.settings.channel_indices == (0,)
    assert (matched.settings.z_start, matched.settings.z_end) == (2, 3)
    assert any("Missing marker" in warning for warning in matched.warnings)
    assert any("Z range" in warning for warning in matched.warnings)
