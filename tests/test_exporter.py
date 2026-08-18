import json

import numpy as np
import pytest
import tifffile
from PIL import Image

from iea.exporter import (
    export_channels_and_merge,
    export_merge,
    export_single_channels,
    write_export_info,
)
from iea.ims_reader import IMSReader
from iea.models import ExportSettings, ImageOutputSettings, ScaleBarSettings


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
    with Image.open(singles[0].path) as grayscale:
        assert grayscale.mode == "L"
        assert grayscale.size == (5, 4)
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
