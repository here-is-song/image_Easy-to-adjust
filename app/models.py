"""Data models shared by IMS parsing and figure export modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ChannelMetadata:
    """Metadata needed to display and export one IMS channel."""

    index: int
    name: str
    color: tuple[float, float, float]
    display_min: float | None
    display_max: float | None
    dataset_path: str
    axis_order: tuple[str, str, str]
    display_range_source: str = "ims"


@dataclass(frozen=True)
class IMSMetadata:
    """Normalized metadata for ResolutionLevel 0 / TimePoint 0."""

    source_path: Path
    size_x: int
    size_y: int
    size_z: int
    voxel_size_x_um: float
    voxel_size_y_um: float
    voxel_size_z_um: float
    origin_x_um: float
    origin_y_um: float
    origin_z_um: float
    extent_x_um: float
    extent_y_um: float
    extent_z_um: float
    unit: str
    dtype: str
    time_point_count: int
    channels: tuple[ChannelMetadata, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def channel_count(self) -> int:
        return len(self.channels)


@dataclass(frozen=True)
class ExportSettings:
    """Settings for a single CLI export operation.

    Slice numbers are 1-based and inclusive, matching the user-facing CLI.
    """

    z_start: int
    z_end: int
    channel_indices: tuple[int, ...]
    add_scale_bar: bool = True
    scale_bar_um: float | None = None
    red_to_magenta: bool = True
    output_format: str = "tif"
    scale_bar_thickness_px: int | None = None
    scale_bar_font_size_px: int | None = None
