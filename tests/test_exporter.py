import json

import numpy as np
import pytest
import tifffile
from PIL import Image

from iea.exporter import (
    export_channels_and_merge,
    export_merge,
    export_single_channels,
    format_ppt_summary,
    render_single_channel,
    write_export_info,
    write_ppt_summary,
)
from iea.ims_reader import IMSReader
from iea.models import DisplayAdjustmentSettings, ExportSettings, ImageOutputSettings, ScaleBarSettings


def test_single_channel_and_merge_tiff_exports(sample_ims, tmp_path):
    output_dir = tmp_path / "output"
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        scale_bar=ScaleBarSettings(enabled=False),
        red_to_magenta=True,
    )
    with IMSReader(sample_ims) as reader:
        single_results = export_single_channels(reader, settings, output_dir)
        merge_result = export_merge(reader, settings, output_dir)

    assert len(single_results) == 2
    green = tifffile.imread(single_results[0].path)
    red = tifffile.imread(single_results[1].path)
    merge = tifffile.imread(merge_result.path)
    assert green.shape == red.shape == (4, 5)
    assert green.dtype == red.dtype == np.uint8
    assert merge.shape == (4, 5, 3)
    assert merge.dtype == np.uint8
    # Channel 1 is red-like and therefore contributes to R and B (magenta).
    assert np.all(merge[..., 0] == 255)
    assert np.all(merge[..., 1] > 0)
    assert np.all(merge[..., 2] == 255)
    assert single_results[1].path.name == "sample_Red_Marker.tif"


def test_single_channel_render_uses_gamma_override(sample_ims):
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0,),
        scale_bar=ScaleBarSettings(enabled=False),
    )
    adjustment = DisplayAdjustmentSettings(0.0, 20.0, gamma=2.0)

    with IMSReader(sample_ims) as reader:
        image, record = render_single_channel(reader, settings, 0, adjustment)

    assert np.all(image == 143)
    assert record.gamma == 2.0


def test_export_info_records_actual_export_settings(sample_ims, tmp_path):
    output_dir = tmp_path / "output"
    settings = ExportSettings(
        z_start=2,
        z_end=3,
        channel_indices=(0, 1),
        scale_bar=ScaleBarSettings(enabled=False),
        red_to_magenta=True,
        output=ImageOutputSettings(width_px=640, height_px=480, dpi=600),
    )
    with IMSReader(sample_ims) as reader:
        results = export_single_channels(reader, settings, output_dir)
        results.append(export_merge(reader, settings, output_dir))
        info_path = write_export_info(reader, settings, results, output_dir)

    payload = json.loads(info_path.read_text(encoding="utf-8"))
    assert payload["z_start_slice"] == 2
    assert payload["z_end_slice"] == 3
    assert payload["selected_thickness_um"] == 4.0
    assert payload["projection"] == "maximum"
    assert payload["output_width_px"] == 640
    assert payload["output_height_px"] == 480
    assert payload["output_dpi"] == 600
    assert len(payload["channels"]) == 2
    assert payload["channels"][1]["original_color"] == [1.0, 0.0, 0.0]
    assert payload["channels"][1]["output_color"] == [1.0, 0.0, 1.0]
    assert payload["channels"][0]["gamma"] == 0.5
    assert payload["channels"][1]["gamma"] == 2.0
    assert payload["acquisition"]["microscope_manufacturer"] == "Olympus"
    assert payload["acquisition"]["scan_speed_us_per_pixel"] == 10.0
    assert payload["objective_detection"]["objective_key"] == "10X"
    assert payload["objective_detection"]["detection_source"] == "Metadata"
    assert payload["selected_objective"]["objective_key"] == "10X"


def test_ppt_summary_uses_source_acquisition_and_selected_z_range(sample_ims, tmp_path):
    settings = ExportSettings(
        z_start=2,
        z_end=3,
        channel_indices=(0,),
        scale_bar=ScaleBarSettings(enabled=False),
    )
    expected = (
        "Date: 260806\n"
        "Microscope: Olympus FV1200\n"
        "Scan speed: 10 μsecond/pixel, Size: 5×4\n"
        "Objective lens: UPLSAPO10X (N.A.0.40), "
        "Z-sectioning interval: 2 μm, Z-stack thickness: 4 μm;"
    )

    with IMSReader(sample_ims) as reader:
        assert reader.metadata is not None
        assert format_ppt_summary(reader.metadata, settings) == expected
        summary_path = write_ppt_summary(reader, settings, tmp_path / "summary")

    assert summary_path.name == "sample_PPT_summary.txt"
    assert summary_path.read_text(encoding="utf-8") == expected


def test_ppt_summary_uses_manual_objective_override(sample_ims):
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0,),
        objective_override="60X",
        scale_bar=ScaleBarSettings(enabled=False),
    )

    with IMSReader(sample_ims) as reader:
        assert reader.metadata is not None
        summary = format_ppt_summary(reader.metadata, settings)

    assert "Objective lens: UPLSAPO60XS (N.A.1.30)" in summary


def test_png_single_channel_and_merge_exports(sample_ims, tmp_path):
    output_dir = tmp_path / "png-output"
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        scale_bar=ScaleBarSettings(enabled=False),
        output=ImageOutputSettings(format="png"),
    )
    with IMSReader(sample_ims) as reader:
        singles = export_single_channels(reader, settings, output_dir)
        merge = export_merge(reader, settings, output_dir)

    assert all(result.path.suffix == ".png" for result in [*singles, merge])
    with Image.open(singles[0].path) as green:
        green_array = np.asarray(green)
        assert green.mode == "RGB"
        assert green.size == (5, 4)
        assert np.all(green_array[..., 0] == 0)
        assert np.all(green_array[..., 1] > 0)
        assert np.all(green_array[..., 2] == 0)
    with Image.open(singles[1].path) as magenta:
        magenta_array = np.asarray(magenta)
        assert magenta.mode == "RGB"
        assert np.all(magenta_array[..., 0] == 255)
        assert np.all(magenta_array[..., 1] == 0)
        assert np.all(magenta_array[..., 2] == 255)
    assert singles[0].channel_records[0].output_color == (0.0, 1.0, 0.0)
    assert singles[1].channel_records[0].output_color == (1.0, 0.0, 1.0)
    with Image.open(merge.path) as rgb:
        assert rgb.mode == "RGB"
        assert rgb.size == (5, 4)


@pytest.mark.parametrize("output_format", ["tif", "png"])
def test_export_dimensions_and_dpi(sample_ims, tmp_path, output_format):
    output_dir = tmp_path / output_format
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        scale_bar=ScaleBarSettings(enabled=False),
        output=ImageOutputSettings(format=output_format, width_px=1000, height_px=800, dpi=300),
    )
    with IMSReader(sample_ims) as reader:
        result = export_merge(reader, settings, output_dir)

    with Image.open(result.path) as exported:
        assert exported.size == (1000, 800)
        assert exported.info["dpi"][0] == pytest.approx(300, rel=0.01)
        assert exported.info["dpi"][1] == pytest.approx(300, rel=0.01)


def test_combined_export_projects_each_channel_only_once(sample_ims, tmp_path, monkeypatch):
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        scale_bar=ScaleBarSettings(enabled=False),
    )
    with IMSReader(sample_ims) as reader:
        calls = []
        original_project = reader.project_z_range

        def counted_project(channel_index, z_start, z_end, chunk_depth=8):
            calls.append(channel_index)
            return original_project(channel_index, z_start, z_end, chunk_depth)

        monkeypatch.setattr(reader, "project_z_range", counted_project)
        results = export_channels_and_merge(reader, settings, tmp_path / "combined")

    assert calls == [0, 1]
    assert len(results) == 3


@pytest.mark.parametrize(
    ("resize_mode", "expect_margin"),
    [("fit", True), ("stretch", False), ("crop", False)],
)
def test_resize_modes_preserve_requested_canvas(sample_ims, tmp_path, resize_mode, expect_margin):
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        scale_bar=ScaleBarSettings(enabled=False),
        output=ImageOutputSettings(format="png", width_px=100, height_px=100, resize_mode=resize_mode),
    )
    with IMSReader(sample_ims) as reader:
        result = export_merge(reader, settings, tmp_path / resize_mode)

    with Image.open(result.path) as exported:
        array = np.asarray(exported)
    assert array.shape == (100, 100, 3)
    assert bool(np.all(array[0] == 0)) is expect_margin
