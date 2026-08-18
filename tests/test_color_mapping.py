import numpy as np

from iea.color_mapping import additive_merge, apply_pseudocolor, convert_red_to_magenta


def test_red_becomes_magenta_but_green_is_unchanged():
    assert convert_red_to_magenta((1.0, 0.0, 0.0)) == (1.0, 0.0, 1.0)
    assert convert_red_to_magenta((0.0, 1.0, 0.0)) == (0.0, 1.0, 0.0)


def test_additive_merge_clips_rgb():
    grayscale = np.asarray([[255]], dtype=np.uint8)
    red = apply_pseudocolor(grayscale, (1.0, 0.0, 0.0))
    green = apply_pseudocolor(grayscale, (0.0, 1.0, 0.0))
    merged = additive_merge([red, green, red])
    np.testing.assert_array_equal(merged, np.asarray([[[255, 255, 0]]], dtype=np.uint8))
