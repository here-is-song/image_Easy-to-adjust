"""Data models shared by IMS parsing and figure export modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ChannelMetadata:
    """Metadata needed to display and export one IMS channel."""

    index: int
    name: str
    color: tuple[float, float, float]
    display_min: float | None
    display_max: float | None
    display_gamma: float
    dataset_path: str
    axis_order: tuple[str, str, str]
    display_range_source: str = "ims"
    display_gamma_source: str = "ims"


@dataclass(frozen=True)
class DisplayAdjustmentSettings:
    """Min, max, and gamma values used to display one channel."""

    display_min: float | None
    display_max: float | None
    gamma: float | None = None

    @property
    def display_range(self) -> tuple[float, float] | None:
        if self.display_min is None or self.display_max is None:
            return None
        return self.display_min, self.display_max


@dataclass(frozen=True)
class AcquisitionMetadata:
    """Optional acquisition details preserved by the source microscopy file."""

    recording_date: datetime | None = None
    microscope_manufacturer: str | None = None
    microscope_model: str | None = None
    scan_speed_us_per_pixel: float | None = None
    objective_name: str | None = None
    objective_magnification: float | None = None
    numerical_aperture: float | None = None
    z_section_interval_um: float | None = None
    scan_zoom: float | None = None


@dataclass(frozen=True)
class ObjectiveDetectionResult:
    """Traceable result from metadata, calibrated Z spacing, or manual selection."""

    objective_key: str | None
    model: str | None
    magnification: float | None
    na: float | None
    immersion: str | None
    measured_z_spacing_um: float | None
    expected_z_spacing_um: float | None
    relative_error: float | None
    confidence: str
    detection_source: str
    warning: str | None = None


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
    acquisition: AcquisitionMetadata = field(default_factory=AcquisitionMetadata)
    objective_detection: ObjectiveDetectionResult | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def channel_count(self) -> int:
        return len(self.channels)


@dataclass(frozen=True)
class ChannelSelection:
    """One user-selected channel and its optional display-range override."""

    index: int
    name: str
    display_min: float | None = None
    display_max: float | None = None
    gamma: float | None = None

    @property
    def display_range(self) -> tuple[float, float] | None:
        if self.display_min is None or self.display_max is None:
            return None
        return self.display_min, self.display_max

    @property
    def display_adjustment(self) -> DisplayAdjustmentSettings:
        return DisplayAdjustmentSettings(self.display_min, self.display_max, self.gamma)


@dataclass(frozen=True)
class ScaleBarSettings:
    """Scale-bar appearance and physical length."""

    enabled: bool = True
    length_um: float | None = None
    thickness_px: int | None = None
    font_size_px: int | None = None


@dataclass(frozen=True)
class ImageOutputSettings:
    """Raster file dimensions, encoding, and print metadata."""

    format: str = "tif"
    width_px: int | None = None
    height_px: int | None = None
    dpi: int = 300
    resize_mode: str = "fit"


@dataclass(frozen=True)
class ExportSettings:
    """Scientific processing settings for one export operation.

    Slice numbers are 1-based and inclusive, matching the user-facing CLI.
    """

    z_start: int
    z_end: int
    channel_indices: tuple[int, ...]
    red_to_magenta: bool = True
    scale_bar: ScaleBarSettings = field(default_factory=ScaleBarSettings)
    output: ImageOutputSettings = field(default_factory=ImageOutputSettings)
    objective_override: str | None = None


@dataclass(frozen=True)
class GuiPreferences:
    """Persistent GUI-only behavior that does not alter image pixels."""

    output_directory: Path | None = None
    copy_to_clipboard: bool = False
    preview_refresh_interval_ms: int = 1000
    section_expanded: dict[str, bool] = field(default_factory=dict)
