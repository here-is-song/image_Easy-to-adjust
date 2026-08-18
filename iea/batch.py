"""Batch compatibility checks and per-file settings adaptation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .models import ChannelSelection, ExportSettings, IMSMetadata


@dataclass(frozen=True)
class MatchedBatchSettings:
    """Settings resolved against one target IMS file."""

    settings: ExportSettings
    display_ranges: dict[int, tuple[float, float]]
    warnings: tuple[str, ...]


def _normalized_channel_name(name: str) -> str:
    return " ".join(name.casefold().split())


def adapt_settings_for_metadata(
    base_settings: ExportSettings,
    selections: tuple[ChannelSelection, ...],
    metadata: IMSMetadata,
) -> MatchedBatchSettings:
    """Match channels by name and clamp the shared Z range for one batch file."""

    by_name: dict[str, list[int]] = {}
    for channel in metadata.channels:
        by_name.setdefault(_normalized_channel_name(channel.name), []).append(channel.index)

    matched_indices: list[int] = []
    display_ranges: dict[int, tuple[float, float]] = {}
    warnings: list[str] = []
    used_indices: set[int] = set()
    for selection in selections:
        candidates = [
            index for index in by_name.get(_normalized_channel_name(selection.name), []) if index not in used_indices
        ]
        if not candidates:
            warnings.append(f"Channel '{selection.name}' is missing and was skipped.")
            continue
        if selection.index in candidates:
            target_index = selection.index
        else:
            target_index = candidates[0]
        if len(candidates) > 1:
            warnings.append(f"Channel name '{selection.name}' is duplicated; target index {target_index} was used.")
        used_indices.add(target_index)
        matched_indices.append(target_index)
        if selection.display_range is not None:
            display_ranges[target_index] = selection.display_range

    z_start = min(max(1, base_settings.z_start), metadata.size_z)
    z_end = min(max(z_start, base_settings.z_end), metadata.size_z)
    if (z_start, z_end) != (base_settings.z_start, base_settings.z_end):
        warnings.append(
            f"Z range was adjusted from {base_settings.z_start}–{base_settings.z_end} to {z_start}–{z_end}."
        )

    return MatchedBatchSettings(
        settings=replace(
            base_settings,
            z_start=z_start,
            z_end=z_end,
            channel_indices=tuple(matched_indices),
        ),
        display_ranges=display_ranges,
        warnings=tuple(warnings),
    )
