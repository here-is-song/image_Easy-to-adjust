import numpy as np

from iea.display_adjustment import apply_display_adjustment
from iea.projection import maximum_intensity_projection


def test_maximum_intensity_projection():
    stack = np.asarray([[[1, 7], [3, 4]], [[9, 2], [5, 6]]], dtype=np.uint16)
    projection = maximum_intensity_projection(stack)
    np.testing.assert_array_equal(projection, np.asarray([[9, 7], [5, 6]], dtype=np.uint16))
    assert projection.dtype == np.uint16


def test_display_adjustment_expected_mapping_and_no_input_change():
    source = np.asarray([100, 600, 1100], dtype=np.uint16)
    original = source.copy()
    adjusted = apply_display_adjustment(source, 100, 1100)
    np.testing.assert_array_equal(adjusted, np.asarray([0, 128, 255], dtype=np.uint8))
    np.testing.assert_array_equal(source, original)
