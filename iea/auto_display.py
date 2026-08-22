"""Sampling-based, non-destructive automatic display adjustment strategies."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .image_dataset import DisplaySettings, ImageDataset

LOGGER = logging.getLogger(__name__)


class DisplayAdjustmentStrategy(Protocol):
    """Calculate one display mapping without modifying source voxels."""

    def calculate(self, dataset: ImageDataset, channel_index: int) -> DisplaySettings: ...


@dataclass(frozen=True)
class HistogramSamplingConfig:
    """Bounded sampling policy suitable for large Z stacks and lightweight PCs."""

    max_z_slices: int = 32
    max_samples_per_channel: int = 2_000_000
    minimum_samples_per_plane: int = 4_096


class UniformHistogramSampler:
    """Uniformly sample Z planes and XY pixels with bounded memory use."""

    def __init__(self, config: HistogramSamplingConfig | None = None) -> None:
        self.config = config or HistogramSamplingConfig()

    def sample(self, dataset: ImageDataset, channel_index: int) -> np.ndarray:
        metadata = dataset.metadata
        if metadata is None:
            raise ValueError("Dataset metadata is unavailable.")
        slice_count = min(metadata.size_z, max(1, self.config.max_z_slices))
        z_indices = np.unique(np.linspace(0, metadata.size_z - 1, slice_count, dtype=np.int64))
        target_per_plane = max(
            self.config.minimum_samples_per_plane,
            self.config.max_samples_per_channel // max(1, len(z_indices)),
        )
        samples: list[np.ndarray] = []
        for z_index in z_indices:
            plane = dataset.get_plane(0, channel_index, int(z_index))
            stride = max(1, math.ceil(math.sqrt(plane.size / target_per_plane)))
            sampled = np.asarray(plane[::stride, ::stride]).reshape(-1)
            samples.append(sampled)
        if not samples:
            return np.asarray([], dtype=np.dtype(metadata.dtype))
        combined = np.concatenate(samples)
        if combined.size > self.config.max_samples_per_channel:
            positions = np.linspace(
                0,
                combined.size - 1,
                self.config.max_samples_per_channel,
                dtype=np.int64,
            )
            combined = combined[positions]
        LOGGER.debug(
            "[AutoDisplay] channel=%d strategy=uniform-z-xy sampled_voxels=%d z_slices=%d",
            channel_index,
            combined.size,
            len(z_indices),
        )
        return np.asarray(combined)


@dataclass(frozen=True)
class HistogramModeResult:
    value: float
    used_fallback: bool
    reason: str | None = None


def find_first_significant_histogram_mode(samples: np.ndarray) -> HistogramModeResult:
    """Find an early stable background mode while resisting zero peaks and outliers."""

    values = np.asarray(samples).reshape(-1)
    if values.size == 0:
        return HistogramModeResult(0.0, True, "No sampled voxels; display minimum fell back to 0.")
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return HistogramModeResult(0.0, True, "No finite voxels; display minimum fell back to 0.")
    if np.all(finite == 0):
        return HistogramModeResult(0.0, False, "Channel samples are all zero.")

    positive = finite[finite > 0]
    zero_fraction = 1.0 - positive.size / finite.size
    minimum_positive_count = max(16, math.ceil(finite.size * 0.001))
    histogram_values = positive if zero_fraction >= 0.5 and positive.size >= minimum_positive_count else finite

    low_clip, high_clip = np.percentile(histogram_values, (0.05, 99.95))
    if not np.isfinite(low_clip) or not np.isfinite(high_clip) or high_clip <= low_clip:
        fallback = float(np.percentile(finite, 0.5))
        return HistogramModeResult(fallback, True, "Histogram range collapsed; P0.5 fallback was used.")

    dtype = values.dtype
    if np.issubdtype(dtype, np.uint8):
        bin_count = min(256, max(16, int(high_clip - low_clip) + 1))
    elif np.issubdtype(dtype, np.uint16):
        bin_count = 1_024
    else:
        bin_count = 512
    histogram, edges = np.histogram(histogram_values, bins=bin_count, range=(low_clip, high_clip))
    if not np.any(histogram):
        fallback = float(np.percentile(finite, 0.5))
        return HistogramModeResult(fallback, True, "Histogram contained no counts; P0.5 fallback was used.")

    kernel = np.asarray([1.0, 2.0, 3.0, 2.0, 1.0], dtype=np.float64)
    kernel /= np.sum(kernel)
    smoothed = np.convolve(histogram.astype(np.float64), kernel, mode="same")
    significance = max(3.0, float(np.max(smoothed)) * 0.02)
    candidates = [
        index
        for index in range(1, len(smoothed) - 1)
        if smoothed[index] >= significance
        and smoothed[index] >= smoothed[index - 1]
        and smoothed[index] >= smoothed[index + 1]
    ]
    if not candidates:
        fallback = float(np.percentile(finite, 0.5))
        return HistogramModeResult(fallback, True, "No significant local mode; P0.5 fallback was used.")
    first_mode = candidates[0]
    return HistogramModeResult(float((edges[first_mode] + edges[first_mode + 1]) / 2.0), False)


class ImarisLikeAutoDisplay:
    """First significant histogram mode / P99.8 / gamma 1.0 strategy."""

    def __init__(self, sampler: UniformHistogramSampler | None = None) -> None:
        self.sampler = sampler or UniformHistogramSampler()

    def calculate(self, dataset: ImageDataset, channel_index: int) -> DisplaySettings:
        metadata = dataset.metadata
        if metadata is None:
            raise ValueError("Dataset metadata is unavailable.")
        samples = self.sampler.sample(dataset, channel_index)
        mode = find_first_significant_histogram_mode(samples)
        if mode.used_fallback and mode.reason:
            LOGGER.warning("[AutoDisplay] channel=%d %s", channel_index, mode.reason)
        finite = samples[np.isfinite(samples)]
        if finite.size == 0 or np.all(finite == 0):
            display_max = 1.0
        else:
            display_max = float(np.percentile(finite, 99.8))
            if display_max <= mode.value:
                observed_max = float(np.max(finite))
                display_max = observed_max if observed_max > mode.value else mode.value + 1.0
        channel = metadata.channels[channel_index]
        result = DisplaySettings(
            minimum=float(mode.value),
            maximum=display_max,
            gamma=1.0,
            color=channel.color,
            opacity=1.0,
            source="OIB_AUTO",
        )
        LOGGER.info(
            "[AutoDisplay] CH%d min=%.6g max=%.6g gamma=%.6g source=%s",
            channel_index,
            result.minimum,
            result.maximum,
            result.gamma,
            "P0.5 fallback" if mode.used_fallback else "first significant histogram mode",
        )
        return result

    def calculate_all(self, dataset: ImageDataset) -> tuple[DisplaySettings, ...]:
        metadata = dataset.metadata
        if metadata is None:
            raise ValueError("Dataset metadata is unavailable.")
        settings = tuple(self.calculate(dataset, index) for index in range(metadata.channel_count))
        dataset.apply_display_settings(settings)
        return settings
