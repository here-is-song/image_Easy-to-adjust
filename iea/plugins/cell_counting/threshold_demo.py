"""Dependency-free threshold/connected-components cell segmenter demo."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from .api import CellCountingRequest, SegmentationOutput


def _otsu_threshold(image: np.ndarray, mask: np.ndarray) -> float:
    values = np.asarray(image, dtype=np.float32)[mask]
    if values.size == 0 or float(np.max(values)) <= float(np.min(values)):
        return 1.0
    histogram, edges = np.histogram(values, bins=256, range=(0.0, 1.0))
    probabilities = histogram.astype(np.float64) / max(1, histogram.sum())
    centers = (edges[:-1] + edges[1:]) * 0.5
    weights_background = np.cumsum(probabilities)
    weights_foreground = 1.0 - weights_background
    means_background = np.cumsum(probabilities * centers)
    total_mean = means_background[-1]
    valid = (weights_background > 0) & (weights_foreground > 0)
    variance = np.zeros_like(probabilities)
    numerator = (total_mean * weights_background - means_background) ** 2
    variance[valid] = numerator[valid] / (weights_background[valid] * weights_foreground[valid])
    return float(centers[int(np.argmax(variance))])


def _neighbour_sum(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, 1, mode="constant")
    height, width = mask.shape
    total = np.zeros(mask.shape, dtype=np.uint8)
    for y_offset in range(3):
        for x_offset in range(3):
            total += padded[y_offset : y_offset + height, x_offset : x_offset + width]
    return total


def _clean_binary(mask: np.ndarray) -> np.ndarray:
    eroded = _neighbour_sum(mask) >= 5
    opened = _neighbour_sum(eroded) > 0
    dilated = _neighbour_sum(opened) > 0
    return _neighbour_sum(dilated) >= 5


def _connected_components(mask: np.ndarray) -> np.ndarray:
    """Label 8-connected foreground without requiring SciPy or scikit-image."""

    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent = [0]

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(first: int, second: int) -> None:
        first_root = find(first)
        second_root = find(second)
        if first_root != second_root:
            parent[max(first_root, second_root)] = min(first_root, second_root)

    next_label = 1
    for y in range(height):
        for x in np.flatnonzero(mask[y]):
            neighbours: list[int] = []
            if x > 0 and labels[y, x - 1]:
                neighbours.append(int(labels[y, x - 1]))
            if y > 0:
                for neighbour_x in range(max(0, x - 1), min(width, x + 2)):
                    if labels[y - 1, neighbour_x]:
                        neighbours.append(int(labels[y - 1, neighbour_x]))
            if not neighbours:
                labels[y, x] = next_label
                parent.append(next_label)
                next_label += 1
            else:
                smallest = min(neighbours)
                labels[y, x] = smallest
                for neighbour in neighbours:
                    union(smallest, neighbour)
    if next_label == 1:
        return labels
    roots = np.arange(next_label, dtype=np.int32)
    for value in range(1, next_label):
        roots[value] = find(value)
    labels = roots[labels]
    unique = np.unique(labels[labels > 0])
    remap = np.zeros(next_label, dtype=np.int32)
    remap[unique] = np.arange(1, unique.size + 1, dtype=np.int32)
    return remap[labels]


def _filter_labels(
    labels: np.ndarray,
    minimum_area: int,
    maximum_area: int,
    exclude_border: bool,
    roi_mask: np.ndarray,
) -> np.ndarray:
    areas = np.bincount(labels.ravel())
    keep = (areas >= minimum_area) & (areas <= maximum_area)
    keep[0] = False
    if exclude_border:
        roi_boundary = roi_mask & (_neighbour_sum(roi_mask) < 9)
        border_labels = np.unique(labels[roi_boundary])
        keep[border_labels] = False
    filtered = labels.copy()
    filtered[~keep[labels]] = 0
    unique = np.unique(filtered[filtered > 0])
    remap = np.zeros(int(filtered.max(initial=0)) + 1, dtype=np.int32)
    remap[unique] = np.arange(1, unique.size + 1, dtype=np.int32)
    return remap[filtered]


class ThresholdConnectedComponentsPlugin:
    """Fast baseline for validating ROI and measurements before Cellpose."""

    plugin_id = "iea.threshold_connected_components.demo"
    display_name = "Threshold + connected components (Demo)"
    description = (
        "Combines selected detection channels, applies Otsu or a manual threshold, "
        "and counts area-filtered connected objects. Touching cells may remain merged."
    )

    def segment(
        self,
        normalized_channels: Mapping[int, np.ndarray],
        request: CellCountingRequest,
        roi_mask: np.ndarray,
    ) -> SegmentationOutput:
        combined = np.max(
            np.stack([normalized_channels[index] for index in request.detection_channel_indices]),
            axis=0,
        )
        threshold = (
            _otsu_threshold(combined, roi_mask)
            if request.threshold_mode == "otsu"
            else request.manual_threshold
        )
        threshold = float(np.clip(threshold * request.threshold_correction, 0.0, 1.0))
        foreground = _clean_binary((combined >= threshold) & roi_mask)
        foreground &= roi_mask
        labels = _connected_components(foreground)
        labels = _filter_labels(
            labels,
            request.minimum_area_px,
            request.maximum_area_px,
            request.exclude_border_objects,
            roi_mask,
        )
        return SegmentationOutput(
            labels=labels,
            threshold=threshold,
            notes=(
                "Demo segmenter: touching cells are not watershed-separated.",
                "Per-channel positivity uses normalized mean intensity inside each object.",
            ),
        )

