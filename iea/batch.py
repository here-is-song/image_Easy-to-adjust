"""Batch compatibility checks and per-file settings adaptation."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .models import ChannelSelection, DisplayAdjustmentSettings, ExportSettings, IMSMetadata


@dataclass(frozen=True)
class MatchedBatchSettings:
    """Settings resolved against one target IMS file."""

    settings: ExportSettings
    display_adjustments: dict[int, DisplayAdjustmentSettings]
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
    matched_single_indices: list[int] = []
    matched_merge_indices: list[int] = []
    display_adjustments: dict[int, DisplayAdjustmentSettings] = {}
    warnings: list[str] = []
    used_indices: set[int] = set()
    index_mapping: dict[int, int] = {}
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
        index_mapping[selection.index] = target_index
        matched_indices.append(target_index)
        if selection.export_single:
            matched_single_indices.append(target_index)
        if selection.include_in_merge:
            matched_merge_indices.append(target_index)
        display_adjustments[target_index] = selection.display_adjustment

    z_start = min(max(1, base_settings.z_start), metadata.size_z)
    z_end = min(max(z_start, base_settings.z_end), metadata.size_z)
    if (z_start, z_end) != (base_settings.z_start, base_settings.z_end):
        warnings.append(
            f"Z range was adjusted from {base_settings.z_start}–{base_settings.z_end} to {z_start}–{z_end}."
        )

    if base_settings.merge_channel_groups is None:
        matched_merge_groups = None
        primary_merge_indices = tuple(matched_merge_indices)
    else:
        groups: list[tuple[int, ...]] = []
        for group in base_settings.resolved_merge_channel_groups:
            if all(index in index_mapping for index in group):
                groups.append(tuple(index_mapping[index] for index in group))
        matched_merge_groups = tuple(groups)
        primary_merge_indices = groups[0] if groups else ()

    return MatchedBatchSettings(
        settings=replace(
            base_settings,
            z_start=z_start,
            z_end=z_end,
            channel_indices=tuple(matched_indices),
            single_channel_indices=tuple(matched_single_indices),
            merge_channel_indices=primary_merge_indices,
            merge_channel_groups=matched_merge_groups,
        ),
        display_adjustments=display_adjustments,
        warnings=tuple(warnings),
    )
