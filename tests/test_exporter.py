import json

import numpy as np
import tifffile
from PIL import Image

from app.exporter import export_merge, export_single_channels, write_export_info
from app.ims_reader import IMSReader
from app.models import ExportSettings


def test_single_channel_and_merge_tiff_exports(sample_ims, tmp_path):
    output_dir = tmp_path / "output"
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        add_scale_bar=False,
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
        add_scale_bar=False,
        red_to_magenta=True,
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
    assert len(payload["channels"]) == 2
    assert payload["channels"][1]["original_color"] == [1.0, 0.0, 0.0]
    assert payload["channels"][1]["output_color"] == [1.0, 0.0, 1.0]


def test_png_single_channel_and_merge_exports(sample_ims, tmp_path):
    output_dir = tmp_path / "png-output"
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        add_scale_bar=False,
        output_format="png",
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
