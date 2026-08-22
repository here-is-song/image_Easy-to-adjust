from __future__ import annotations

import numpy as np

from iea.auto_display import HistogramSamplingConfig, ImarisLikeAutoDisplay, UniformHistogramSampler
from tests.test_image_dataset import make_memory_dataset


def test_auto_display_finds_background_mode_and_resists_bright_outliers() -> None:
    rng = np.random.default_rng(20260821)
    plane = rng.normal(1200, 25, size=(8, 96, 96)).clip(0, 65535).astype(np.uint16)
    plane[:, 30:60, 30:60] = rng.normal(6000, 400, size=(8, 30, 30)).clip(0, 65535)
    plane.reshape(-1)[-5:] = 65535
    data = plane[np.newaxis, np.newaxis]
    original = data.copy()
    dataset = make_memory_dataset(data)
    strategy = ImarisLikeAutoDisplay(
        UniformHistogramSampler(
            HistogramSamplingConfig(max_z_slices=8, max_samples_per_channel=200_000)
        )
    )

    setting = strategy.calculate_all(dataset)[0]

    assert 1100 <= setting.minimum <= 1300
    assert 5500 <= setting.maximum < 65535
    assert setting.gamma == 1.0
    assert setting.source == "OIB_AUTO"
    np.testing.assert_array_equal(data, original)


def test_auto_display_handles_an_all_zero_channel() -> None:
    data = np.zeros((1, 1, 1, 8, 8), dtype=np.uint16)
    dataset = make_memory_dataset(data)

    setting = ImarisLikeAutoDisplay().calculate(dataset, 0)

    assert setting.minimum == 0.0
    assert setting.maximum == 1.0
    assert setting.gamma == 1.0
