from __future__ import annotations

from pathlib import Path

import numpy as np

from iea.plugins.cell_counting import (
    CellCountingRequest,
    NormalizedROI,
    SegmentationOutput,
    load_cell_counting_plugins,
    run_cell_counting,
    write_cell_count_csv,
)


def _synthetic_channels() -> dict[int, np.ndarray]:
    detection = np.zeros((80, 90), dtype=np.uint16)
    detection[10:20, 12:22] = 1000
    detection[42:54, 55:67] = 1000
    green = np.zeros_like(detection)
    green[10:20, 12:22] = 800
    red = np.zeros_like(detection)
    red[42:54, 55:67] = 900
    return {0: green, 1: red, 2: detection}


def _request(**overrides: object) -> CellCountingRequest:
    values: dict[str, object] = {
        "detection_channel_indices": (2,),
        "measurement_channel_indices": (0, 1, 2),
        "z_start": 1,
        "z_end": 1,
        "minimum_area_px": 20,
        "maximum_area_px": 500,
        "positive_threshold": 0.5,
        "exclude_border_objects": False,
    }
    values.update(overrides)
    return CellCountingRequest(**values)  # type: ignore[arg-type]


def _run(request: CellCountingRequest):
    plugin = next(iter(load_cell_counting_plugins().values()))
    return run_cell_counting(
        Path("synthetic.ims"),
        _synthetic_channels(),
        {0: "Green marker", 1: "Red marker", 2: "DRAQ5"},
        {0: (0.0, 1.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (0.0, 0.0, 1.0)},
        request,
        plugin,
    )


def test_demo_segments_once_and_measures_multiple_channels() -> None:
    result = _run(_request())

    assert result.total_count == 2
    assert result.labels.dtype == np.int32
    assert set(np.unique(result.labels)) == {0, 1, 2}
    assert result.overlay_rgb.shape == (80, 90, 3)
    assert [summary.positive_count for summary in result.channel_summaries] == [1, 1, 2]
    assert all(len(cell.channel_means) == 3 for cell in result.measurements)


def test_manual_and_automatic_roi_are_applied_before_counting() -> None:
    manual = _run(
        _request(
            roi_mode="manual",
            manual_roi=NormalizedROI(0.0, 0.0, 0.45, 0.45),
        )
    )
    automatic = _run(_request(roi_mode="auto"))

    assert manual.total_count == 1
    assert manual.roi_bounds_px == (0, 0, 40, 36)
    assert automatic.total_count == 2
    assert automatic.roi_bounds_px != (0, 0, 90, 80)


def test_cellpose_compatible_plugin_only_needs_to_return_integer_labels() -> None:
    class FakeCellposePlugin:
        plugin_id = "test.cellpose"
        display_name = "Fake Cellpose"
        description = "Test double"

        def segment(self, normalized_channels, request, roi_mask):
            labels = np.zeros(roi_mask.shape, dtype=np.int32)
            labels[10:20, 12:22] = 1
            labels[42:54, 55:67] = 2
            return SegmentationOutput(labels, None)

    result = run_cell_counting(
        Path("synthetic.ims"),
        _synthetic_channels(),
        {0: "Green", 1: "Red", 2: "DRAQ5"},
        {0: (0.0, 1.0, 0.0), 1: (1.0, 0.0, 0.0), 2: (0.0, 0.0, 1.0)},
        _request(),
        FakeCellposePlugin(),
    )

    assert result.total_count == 2
    assert result.plugin_id == "test.cellpose"


def test_per_cell_csv_contains_every_measurement_channel(tmp_path: Path) -> None:
    result = _run(_request())
    output = write_cell_count_csv(result, tmp_path / "cells.csv")
    text = output.read_text(encoding="utf-8-sig")

    assert "Green marker_mean_normalized" in text
    assert "Red marker_positive" in text
    assert len(text.splitlines()) == result.total_count + 1

