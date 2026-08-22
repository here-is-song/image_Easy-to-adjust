"""Stable cell-counting interfaces shared by demo and future Cellpose plugins."""

from __future__ import annotations

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class NormalizedROI:
    """Axis-aligned ROI stored as fractions of the full-resolution image."""

    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0

    def bounds(self, image_width: int, image_height: int) -> tuple[int, int, int, int]:
        x0 = min(image_width - 1, max(0, round(self.x * image_width)))
        y0 = min(image_height - 1, max(0, round(self.y * image_height)))
        x1 = min(image_width, max(x0 + 1, round((self.x + self.width) * image_width)))
        y1 = min(image_height, max(y0 + 1, round((self.y + self.height) * image_height)))
        return x0, y0, x1, y1


@dataclass(frozen=True)
class CellCountingRequest:
    """Format-neutral settings for one 2D projected-cell counting run."""

    detection_channel_indices: tuple[int, ...]
    measurement_channel_indices: tuple[int, ...]
    z_start: int
    z_end: int
    roi_mode: str = "full"
    manual_roi: NormalizedROI = NormalizedROI()
    threshold_mode: str = "otsu"
    manual_threshold: float = 0.35
    threshold_correction: float = 1.0
    positive_threshold: float = 0.25
    minimum_area_px: int = 20
    maximum_area_px: int = 100_000
    exclude_border_objects: bool = True


@dataclass(frozen=True)
class SegmentationOutput:
    """Cellpose-compatible integer label image returned by a segmenter plugin."""

    labels: np.ndarray
    threshold: float | None
    notes: tuple[str, ...] = ()


@runtime_checkable
class CellSegmenterPlugin(Protocol):
    """Replaceable segmentation stage; Cellpose can implement this unchanged."""

    plugin_id: str
    display_name: str
    description: str

    def segment(
        self,
        normalized_channels: Mapping[int, np.ndarray],
        request: CellCountingRequest,
        roi_mask: np.ndarray,
    ) -> SegmentationOutput: ...


@dataclass(frozen=True)
class CellCountMeasurement:
    object_id: int
    centroid_x_px: float
    centroid_y_px: float
    area_px: int
    channel_means: tuple[float, ...]
    channel_maxima: tuple[float, ...]
    channel_positive: tuple[bool, ...]


@dataclass(frozen=True)
class ChannelCountSummary:
    channel_index: int
    channel_name: str
    positive_count: int
    positive_percent: float
    mean_object_intensity: float


@dataclass(frozen=True)
class CellCountingResult:
    source_path: Path
    plugin_id: str
    plugin_name: str
    labels: np.ndarray
    overlay_rgb: np.ndarray
    roi_bounds_px: tuple[int, int, int, int]
    threshold: float | None
    measurements: tuple[CellCountMeasurement, ...]
    channel_summaries: tuple[ChannelCountSummary, ...]
    measurement_channel_indices: tuple[int, ...]
    measurement_channel_names: tuple[str, ...]
    notes: tuple[str, ...] = ()

    @property
    def total_count(self) -> int:
        return len(self.measurements)


def _normalize_channel(image: np.ndarray, roi_mask: np.ndarray) -> np.ndarray:
    values = np.asarray(image, dtype=np.float32)
    finite = values[np.isfinite(values) & roi_mask]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.float32)
    low, high = np.percentile(finite, (1.0, 99.8))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(finite))
        high = float(np.max(finite))
    if high <= low:
        return np.zeros(values.shape, dtype=np.float32)
    return np.clip((values - low) / (high - low), 0.0, 1.0).astype(np.float32, copy=False)


def _rectangular_mask(shape: tuple[int, int], roi: NormalizedROI) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    height, width = shape
    x0, y0, x1, y1 = roi.bounds(width, height)
    mask = np.zeros(shape, dtype=bool)
    mask[y0:y1, x0:x1] = True
    return mask, (x0, y0, x1, y1)


def _auto_roi(
    normalized_channels: Mapping[int, np.ndarray],
    detection_indices: tuple[int, ...],
) -> NormalizedROI:
    combined = np.max(np.stack([normalized_channels[index] for index in detection_indices]), axis=0)
    foreground = combined >= max(0.05, float(np.percentile(combined, 75.0)) * 0.5)
    coordinates = np.argwhere(foreground)
    if coordinates.size == 0:
        return NormalizedROI()
    height, width = combined.shape
    y0, x0 = coordinates.min(axis=0)
    y1, x1 = coordinates.max(axis=0) + 1
    padding_x = max(2, round((x1 - x0) * 0.05))
    padding_y = max(2, round((y1 - y0) * 0.05))
    x0 = max(0, x0 - padding_x)
    y0 = max(0, y0 - padding_y)
    x1 = min(width, x1 + padding_x)
    y1 = min(height, y1 + padding_y)
    return NormalizedROI(x0 / width, y0 / height, (x1 - x0) / width, (y1 - y0) / height)


def _label_boundaries(labels: np.ndarray) -> np.ndarray:
    boundary = np.zeros(labels.shape, dtype=bool)
    boundary[1:, :] |= labels[1:, :] != labels[:-1, :]
    boundary[:-1, :] |= labels[:-1, :] != labels[1:, :]
    boundary[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    boundary[:, :-1] |= labels[:, :-1] != labels[:, 1:]
    return boundary & (labels > 0)


def _make_overlay(
    normalized_channels: Mapping[int, np.ndarray],
    channel_colors: Mapping[int, tuple[float, float, float]],
    labels: np.ndarray,
    roi_bounds: tuple[int, int, int, int],
    measurements: tuple[CellCountMeasurement, ...],
) -> np.ndarray:
    rgb = np.zeros((*labels.shape, 3), dtype=np.float32)
    for index, image in normalized_channels.items():
        color = np.asarray(channel_colors[index], dtype=np.float32)
        rgb += image[..., None] * color
    output = np.clip(rgb * 255.0, 0, 255).astype(np.uint8)
    output[_label_boundaries(labels)] = (0, 255, 255)
    for measurement in measurements:
        x = int(round(measurement.centroid_x_px))
        y = int(round(measurement.centroid_y_px))
        output[max(0, y - 1) : y + 2, max(0, x - 1) : x + 2] = (255, 255, 0)
    x0, y0, x1, y1 = roi_bounds
    output[y0 : min(y0 + 2, y1), x0:x1] = (255, 128, 0)
    output[max(y0, y1 - 2) : y1, x0:x1] = (255, 128, 0)
    output[y0:y1, x0 : min(x0 + 2, x1)] = (255, 128, 0)
    output[y0:y1, max(x0, x1 - 2) : x1] = (255, 128, 0)
    return output


def run_cell_counting(
    source_path: Path,
    raw_channels: Mapping[int, np.ndarray],
    channel_names: Mapping[int, str],
    channel_colors: Mapping[int, tuple[float, float, float]],
    request: CellCountingRequest,
    plugin: CellSegmenterPlugin,
) -> CellCountingResult:
    """Segment once, then measure every requested marker on the same objects."""

    required = set(request.detection_channel_indices) | set(request.measurement_channel_indices)
    if not request.detection_channel_indices:
        raise ValueError("At least one detection channel is required.")
    if not request.measurement_channel_indices:
        raise ValueError("At least one measurement channel is required.")
    if not required.issubset(raw_channels):
        raise ValueError("One or more requested channels were not loaded.")
    shapes = {np.asarray(raw_channels[index]).shape for index in required}
    if len(shapes) != 1 or len(next(iter(shapes))) != 2:
        raise ValueError("Cell counting requires equally sized 2D channel projections.")
    shape = next(iter(shapes))
    initial_mask = np.ones(shape, dtype=bool)
    normalized = {index: _normalize_channel(raw_channels[index], initial_mask) for index in required}
    if request.roi_mode == "auto":
        roi = _auto_roi(normalized, request.detection_channel_indices)
    elif request.roi_mode == "manual":
        roi = request.manual_roi
    elif request.roi_mode == "full":
        roi = NormalizedROI()
    else:
        raise ValueError(f"Unsupported ROI mode: {request.roi_mode}.")
    roi_mask, roi_bounds = _rectangular_mask(shape, roi)
    normalized = {index: _normalize_channel(raw_channels[index], roi_mask) for index in required}
    segmented = plugin.segment(normalized, request, roi_mask)
    labels = np.asarray(segmented.labels, dtype=np.int32)
    if labels.shape != shape or labels.ndim != 2 or np.any(labels < 0):
        raise ValueError("The segmentation plugin returned an invalid label image.")
    labels = labels.copy()
    labels[~roi_mask] = 0
    object_count = int(labels.max(initial=0))
    areas = np.bincount(labels.ravel(), minlength=object_count + 1).astype(np.int64)
    y_grid, x_grid = np.indices(shape)
    x_sums = np.bincount(labels.ravel(), weights=x_grid.ravel(), minlength=object_count + 1)
    y_sums = np.bincount(labels.ravel(), weights=y_grid.ravel(), minlength=object_count + 1)
    per_channel_means: list[np.ndarray] = []
    per_channel_maxima: list[np.ndarray] = []
    for channel_index in request.measurement_channel_indices:
        image = normalized[channel_index]
        sums = np.bincount(labels.ravel(), weights=image.ravel(), minlength=object_count + 1)
        maxima = np.zeros(object_count + 1, dtype=np.float32)
        np.maximum.at(maxima, labels.ravel(), image.ravel())
        per_channel_means.append(np.divide(sums, areas, out=np.zeros_like(sums), where=areas > 0))
        per_channel_maxima.append(maxima)
    measurements = tuple(
        CellCountMeasurement(
            object_id=object_id,
            centroid_x_px=float(x_sums[object_id] / areas[object_id]),
            centroid_y_px=float(y_sums[object_id] / areas[object_id]),
            area_px=int(areas[object_id]),
            channel_means=tuple(float(values[object_id]) for values in per_channel_means),
            channel_maxima=tuple(float(values[object_id]) for values in per_channel_maxima),
            channel_positive=tuple(
                bool(values[object_id] >= request.positive_threshold) for values in per_channel_means
            ),
        )
        for object_id in range(1, object_count + 1)
        if areas[object_id] > 0
    )
    summaries = tuple(
        ChannelCountSummary(
            channel_index=channel_index,
            channel_name=channel_names[channel_index],
            positive_count=sum(item.channel_positive[position] for item in measurements),
            positive_percent=(
                100.0 * sum(item.channel_positive[position] for item in measurements) / len(measurements)
                if measurements
                else 0.0
            ),
            mean_object_intensity=(
                float(np.mean([item.channel_means[position] for item in measurements]))
                if measurements
                else 0.0
            ),
        )
        for position, channel_index in enumerate(request.measurement_channel_indices)
    )
    overlay = _make_overlay(normalized, channel_colors, labels, roi_bounds, measurements)
    return CellCountingResult(
        source_path=Path(source_path),
        plugin_id=plugin.plugin_id,
        plugin_name=plugin.display_name,
        labels=labels,
        overlay_rgb=overlay,
        roi_bounds_px=roi_bounds,
        threshold=segmented.threshold,
        measurements=measurements,
        channel_summaries=summaries,
        measurement_channel_indices=request.measurement_channel_indices,
        measurement_channel_names=tuple(channel_names[index] for index in request.measurement_channel_indices),
        notes=segmented.notes,
    )


def write_cell_count_csv(result: CellCountingResult, path: str | Path) -> Path:
    """Export one row per detected object for downstream statistics."""

    output_path = Path(path)
    headers = ["object_id", "centroid_x_px", "centroid_y_px", "area_px"]
    for name in result.measurement_channel_names:
        headers.extend((f"{name}_mean_normalized", f"{name}_max_normalized", f"{name}_positive"))
    with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for measurement in result.measurements:
            row: list[object] = [
                measurement.object_id,
                f"{measurement.centroid_x_px:.3f}",
                f"{measurement.centroid_y_px:.3f}",
                measurement.area_px,
            ]
            for mean, maximum, positive in zip(
                measurement.channel_means,
                measurement.channel_maxima,
                measurement.channel_positive,
                strict=True,
            ):
                row.extend((f"{mean:.6f}", f"{maximum:.6f}", int(positive)))
            writer.writerow(row)
    return output_path

