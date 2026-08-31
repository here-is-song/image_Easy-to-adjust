from dataclasses import replace

from iea.batch import adapt_settings_for_metadata
from iea.ims_reader import IMSReader
from iea.models import ChannelSelection, DisplayAdjustmentSettings, ExportSettings


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
        ChannelSelection(
            0,
            "Green",
            2.0,
            15.0,
            0.8,
            (0.1, 0.2, 0.3),
            export_single=True,
            include_in_merge=False,
        ),
        ChannelSelection(
            1,
            "Red/Marker",
            1.0,
            20.0,
            1.4,
            export_single=False,
            include_in_merge=True,
        ),
    )

    matched = adapt_settings_for_metadata(settings, selections, swapped_metadata)

    assert matched.settings.channel_indices == (1, 0)
    assert matched.settings.resolved_single_channel_indices == (1,)
    assert matched.settings.resolved_merge_channel_indices == (0,)
    assert matched.display_adjustments == {
        1: DisplayAdjustmentSettings(2.0, 15.0, 0.8, (0.1, 0.2, 0.3)),
        0: DisplayAdjustmentSettings(1.0, 20.0, 1.4),
    }
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
    assert matched.settings.resolved_single_channel_indices == (0,)
    assert matched.settings.resolved_merge_channel_indices == (0,)
    assert (matched.settings.z_start, matched.settings.z_end) == (2, 3)
    assert any("Missing marker" in warning for warning in matched.warnings)
    assert any("Z range" in warning for warning in matched.warnings)


def test_batch_maps_every_merge_group_by_channel_name(sample_ims):
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    green, red = metadata.channels
    swapped_metadata = replace(metadata, channels=(replace(red, index=0), replace(green, index=1)))
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        single_channel_indices=(0,),
        merge_channel_indices=(0, 1),
        merge_channel_groups=((0, 1),),
    )
    selections = (
        ChannelSelection(0, "Green", export_single=True, include_in_merge=True),
        ChannelSelection(1, "Red/Marker", export_single=False, include_in_merge=True),
    )

    matched = adapt_settings_for_metadata(settings, selections, swapped_metadata)

    assert matched.settings.resolved_single_channel_indices == (1,)
    assert matched.settings.resolved_merge_channel_groups == ((1, 0),)
    assert matched.settings.required_output_channel_indices == (1, 0)
