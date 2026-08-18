import numpy as np

from app.scalebar import choose_auto_scale_bar_um, draw_scale_bar, scale_bar_pixels


def test_scale_bar_pixel_length():
    assert scale_bar_pixels(scale_bar_um=50, voxel_size_x_um=0.25) == 200


def test_auto_scale_bar_uses_nearest_candidate():
    assert choose_auto_scale_bar_um(width_pixels=2048, voxel_size_x_um=0.284) == 100


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
    assert np.all(output[y_bar : y_bar + 7, -59:-8] == 255)
