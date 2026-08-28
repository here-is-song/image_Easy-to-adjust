import numpy as np
import pytest

from iea.scalebar import (
    choose_auto_scale_bar_um,
    draw_scale_bar,
    format_scale_bar_length,
    scale_bar_pixels,
)


def test_scale_bar_pixel_length():
    assert scale_bar_pixels(scale_bar_um=50, voxel_size_x_um=0.25) == 200


def test_auto_scale_bar_uses_nearest_candidate():
    assert choose_auto_scale_bar_um(width_pixels=2048, voxel_size_x_um=0.284) == 100


@pytest.mark.parametrize(
    ("length_um", "expected"),
    [(500, "500 µm"), (1000, "1 mm"), (1500, "1.5 mm"), (5000, "5 mm")],
)
def test_scale_bar_label_uses_a_readable_unit(length_um, expected):
    assert format_scale_bar_length(length_um) == expected


def test_draw_scale_bar_preserves_shape_dtype_and_input():
    source = np.zeros((100, 200), dtype=np.uint8)
    output, chosen = draw_scale_bar(source, voxel_size_x_um=1.0, scale_bar_um=20)
    assert output.shape == source.shape
    assert output.dtype == np.uint8
    assert chosen == 20
    assert output.max() == 255
    assert source.max() == 0


def test_draw_scale_bar_accepts_manual_thickness_and_font_size():
    source = np.zeros((200, 300), dtype=np.uint8)
    output, _ = draw_scale_bar(
        source,
        voxel_size_x_um=1.0,
        scale_bar_um=50,
        thickness_px=7,
        font_size_px=24,
    )
    margin_y = max(4, round(source.shape[0] * 0.03))
    y_bar = source.shape[0] - margin_y - 7
    bar_columns = np.flatnonzero(output[y_bar] == 255)
    assert len(bar_columns) == 50
    assert np.all(output[y_bar : y_bar + 7, bar_columns[0] : bar_columns[-1] + 1] == 255)


def test_large_scale_bar_text_stays_complete_and_moves_bar_left():
    source = np.zeros((260, 500), dtype=np.uint8)
    small_text, _ = draw_scale_bar(
        source,
        voxel_size_x_um=1.0,
        scale_bar_um=20,
        thickness_px=10,
        font_size_px=20,
    )
    large_text, _ = draw_scale_bar(
        source,
        voxel_size_x_um=1.0,
        scale_bar_um=20,
        thickness_px=10,
        font_size_px=500,
    )

    margin_x = max(4, round(source.shape[1] * 0.03))
    margin_y = max(4, round(source.shape[0] * 0.03))
    y_bar = source.shape[0] - margin_y - 10
    small_bar = np.flatnonzero(small_text[y_bar] == 255)
    large_bar = np.flatnonzero(large_text[y_bar] == 255)
    large_pixels = np.argwhere(large_text == 255)

    assert len(small_bar) == len(large_bar) == 20
    assert large_bar[0] < small_bar[0]
    assert large_pixels[:, 1].min() >= margin_x
    assert large_pixels[:, 1].max() < source.shape[1] - margin_x
    assert large_pixels[:, 0].min() >= margin_y
    assert large_pixels[:, 0].max() < source.shape[0] - margin_y
