"""Format-independent microscopy dataset and session abstractions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np

from .models import IMSMetadata


class ImageDatasetError(RuntimeError):
    """Raised when a microscopy dataset cannot be opened or read safely."""


@dataclass(frozen=True)
class ResolutionLevelInfo:
    """One image-pyramid level, expressed in logical X/Y/Z dimensions."""

    index: int
    size_x: int
    size_y: int
    size_z: int

    @property
    def pixel_count_xy(self) -> int:
        return self.size_x * self.size_y


@dataclass(frozen=True)
class DisplaySettings:
    """Non-destructive display mapping for one raw microscopy channel."""

    minimum: float
    maximum: float
    gamma: float = 1.0
    color: tuple[float, float, float] | None = None
    opacity: float = 1.0
    source: str = "UNKNOWN"


@dataclass(frozen=True)
class DatasetFileRelationship:
    """Trace the requested source and its optional persistent IMS cache."""

    original_path: Path
    cache_path: Path | None
    source_format: str
    cache_format: str | None
    cache_status: str


@runtime_checkable
class PixelBackend(Protocol):
    """Lazy/block-based pixel access implemented by each file-format reader."""

    path: Path
    backend_name: str
    metadata: IMSMetadata | None

    def open(self) -> IMSMetadata: ...

    def close(self) -> None: ...

    def get_block(
        self,
        time_index: int,
        channel_index: int,
        z_start: int,
        z_end: int,
        y_start: int,
        y_end: int,
        x_start: int,
        x_end: int,
    ) -> np.ndarray: ...


class ImageDataset:
    """The single application-facing interface for microscopy pixels and metadata."""

    def __init__(self, backend: PixelBackend, source_format: str) -> None:
        self.backend = backend
        self.source_format = source_format.upper()
        self._metadata: IMSMetadata | None = None
        self._display_settings: tuple[DisplaySettings, ...] = ()

    @property
    def source_path(self) -> Path:
        return self.backend.path

    @property
    def active_backend(self) -> str:
        return self.backend.backend_name

    @property
    def metadata(self) -> IMSMetadata | None:
        return self._metadata

    @property
    def display_settings(self) -> tuple[DisplaySettings, ...]:
        return self._display_settings

    @property
    def size_x(self) -> int:
        return self._require_metadata().size_x

    @property
    def size_y(self) -> int:
        return self._require_metadata().size_y

    @property
    def size_z(self) -> int:
        return self._require_metadata().size_z

    @property
    def size_c(self) -> int:
        return self._require_metadata().channel_count

    @property
    def size_t(self) -> int:
        return self._require_metadata().time_point_count

    @property
    def dtype(self) -> str:
        return self._require_metadata().dtype

    @property
    def pixel_size_x_um(self) -> float | None:
        return self._require_metadata().voxel_size_x_um

    @property
    def pixel_size_y_um(self) -> float | None:
        return self._require_metadata().voxel_size_y_um

    @property
    def z_spacing_um(self) -> float | None:
        return self._require_metadata().voxel_size_z_um

    @property
    def channels(self):
        return self._require_metadata().channels

    @property
    def objective(self):
        return self._require_metadata().objective_detection

    def open(self) -> ImageDataset:
        self._metadata = self.backend.open()
        self._display_settings = tuple(
            DisplaySettings(
                minimum=channel.display_min if channel.display_min is not None else 0.0,
                maximum=channel.display_max if channel.display_max is not None else 1.0,
                gamma=channel.display_gamma,
                color=channel.color,
                source=(
                    "IMS_METADATA"
                    if channel.display_range_source == "ims"
                    else channel.display_range_source.upper()
                ),
            )
            for channel in self._metadata.channels
        )
        return self

    def close(self) -> None:
        self.backend.close()

    def __enter__(self) -> ImageDataset:
        if self._metadata is None:
            self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def apply_display_settings(self, settings: tuple[DisplaySettings, ...]) -> None:
        """Attach display settings without changing any raw voxel values."""

        metadata = self._require_metadata()
        if len(settings) != metadata.channel_count:
            raise ImageDatasetError(
                f"Expected {metadata.channel_count} channel display settings, received {len(settings)}."
            )
        channels = tuple(
            replace(
                channel,
                display_min=setting.minimum,
                display_max=setting.maximum,
                display_gamma=setting.gamma,
                color=setting.color or channel.color,
                display_range_source=setting.source.casefold(),
                display_gamma_source=setting.source.casefold(),
            )
            for channel, setting in zip(metadata.channels, settings, strict=True)
        )
        self._metadata = replace(metadata, channels=channels)
        self._display_settings = settings

    def apply_metadata(self, metadata: IMSMetadata) -> None:
        """Attach corrected metadata while preserving the underlying pixel layout."""

        current = self._require_metadata()
        current_shape = (current.size_x, current.size_y, current.size_z, current.channel_count)
        replacement_shape = (metadata.size_x, metadata.size_y, metadata.size_z, metadata.channel_count)
        if replacement_shape != current_shape:
            raise ImageDatasetError("Corrected metadata cannot change the stored pixel dimensions or channels.")
        self._metadata = metadata

    def get_block(
        self,
        time_index: int,
        channel_index: int,
        z_start: int,
        z_end: int,
        y_start: int,
        y_end: int,
        x_start: int,
        x_end: int,
    ) -> np.ndarray:
        """Read one zero-based, half-open T/C/Z/Y/X block lazily."""

        metadata = self._require_metadata()
        if not 0 <= time_index < metadata.time_point_count:
            raise ImageDatasetError(f"Time index {time_index} is out of range.")
        if not 0 <= channel_index < metadata.channel_count:
            raise ImageDatasetError(f"Channel index {channel_index} is out of range.")
        if not (0 <= z_start < z_end <= metadata.size_z):
            raise ImageDatasetError(f"Invalid Z block {z_start}:{z_end}.")
        if not (0 <= y_start < y_end <= metadata.size_y):
            raise ImageDatasetError(f"Invalid Y block {y_start}:{y_end}.")
        if not (0 <= x_start < x_end <= metadata.size_x):
            raise ImageDatasetError(f"Invalid X block {x_start}:{x_end}.")
        block = np.asarray(
            self.backend.get_block(
                time_index,
                channel_index,
                z_start,
                z_end,
                y_start,
                y_end,
                x_start,
                x_end,
            )
        )
        expected_shape = (z_end - z_start, y_end - y_start, x_end - x_start)
        if block.shape != expected_shape:
            raise ImageDatasetError(
                f"Backend returned block shape {block.shape}; expected {expected_shape}."
            )
        return block

    def get_plane(self, time_index: int, channel_index: int, z_index: int) -> np.ndarray:
        """Read one Y/X plane without loading the complete stack."""

        metadata = self._require_metadata()
        return self.get_block(
            time_index,
            channel_index,
            z_index,
            z_index + 1,
            0,
            metadata.size_y,
            0,
            metadata.size_x,
        )[0]

    def get_z_slice(self, channel_index: int, z_index: int, time_index: int = 0) -> np.ndarray:
        return self.get_plane(time_index, channel_index, z_index)

    def get_channel(self, channel_index: int, time_index: int = 0) -> np.ndarray:
        """Explicitly materialize one channel; callers should prefer block access for large data."""

        metadata = self._require_metadata()
        return self.get_block(
            time_index,
            channel_index,
            0,
            metadata.size_z,
            0,
            metadata.size_y,
            0,
            metadata.size_x,
        )

    def read_z_range(self, channel_index: int, z_start: int, z_end: int) -> np.ndarray:
        """Compatibility API using the application's 1-based inclusive Z range."""

        metadata = self._require_metadata()
        if not 1 <= z_start <= z_end <= metadata.size_z:
            raise ImageDatasetError(
                f"Z range must satisfy 1 <= start <= end <= {metadata.size_z}; received {z_start}..{z_end}."
            )
        return self.get_block(
            0,
            channel_index,
            z_start - 1,
            z_end,
            0,
            metadata.size_y,
            0,
            metadata.size_x,
        )

    def project_z_range(
        self,
        channel_index: int,
        z_start: int,
        z_end: int,
        chunk_depth: int = 8,
    ) -> tuple[np.ndarray, float, float]:
        """Chunked MIP and exact selected-range min/max without full-stack RAM use."""

        metadata = self._require_metadata()
        if chunk_depth <= 0:
            raise ImageDatasetError("Projection chunk depth must be greater than zero.")
        if not 1 <= z_start <= z_end <= metadata.size_z:
            raise ImageDatasetError(
                f"Z range must satisfy 1 <= start <= end <= {metadata.size_z}; received {z_start}..{z_end}."
            )
        projection: np.ndarray | None = None
        data_min = np.inf
        data_max = -np.inf
        for zero_based_start in range(z_start - 1, z_end, chunk_depth):
            zero_based_end = min(z_end, zero_based_start + chunk_depth)
            block = self.get_block(
                0,
                channel_index,
                zero_based_start,
                zero_based_end,
                0,
                metadata.size_y,
                0,
                metadata.size_x,
            )
            chunk_projection = np.max(block, axis=0)
            projection = chunk_projection if projection is None else np.maximum(projection, chunk_projection)
            data_min = min(data_min, float(np.min(block)))
            data_max = max(data_max, float(np.max(block)))
        if projection is None:
            raise ImageDatasetError("The selected Z range did not contain image data.")
        return projection, data_min, data_max

    def resolution_levels(self) -> tuple[ResolutionLevelInfo, ...]:
        """Return native pyramid levels, or a single full-resolution fallback."""

        metadata = self._require_metadata()
        provider = getattr(self.backend, "resolution_levels", None)
        if callable(provider):
            levels = tuple(provider())
            if levels:
                return levels
        return (ResolutionLevelInfo(0, metadata.size_x, metadata.size_y, metadata.size_z),)

    def choose_resolution_level(self, target_width: int, target_height: int) -> ResolutionLevelInfo:
        """Choose the least expensive level that still satisfies the screen request."""

        target_width = max(1, int(target_width))
        target_height = max(1, int(target_height))
        levels = self.resolution_levels()
        adequate = [
            level
            for level in levels
            if level.size_x >= target_width and level.size_y >= target_height
        ]
        if adequate:
            return min(adequate, key=lambda level: (level.pixel_count_xy, level.index))
        return max(levels, key=lambda level: (level.pixel_count_xy, -level.index))

    def project_z_range_at_resolution(
        self,
        channel_index: int,
        z_start: int,
        z_end: int,
        level: ResolutionLevelInfo,
        chunk_depth: int = 8,
    ) -> tuple[np.ndarray, float, float]:
        """Project at a native pyramid level when the backend supports it."""

        provider = getattr(self.backend, "project_z_range_at_resolution", None)
        if callable(provider):
            return provider(channel_index, z_start, z_end, level.index, chunk_depth)
        projection, data_min, data_max = self.project_z_range(
            channel_index,
            z_start,
            z_end,
            chunk_depth,
        )
        if projection.shape == (level.size_y, level.size_x):
            return projection, data_min, data_max
        # This path is mainly for non-pyramidal backends. Native IMS levels avoid
        # the full-resolution read and therefore remain the preferred fast path.
        from PIL import Image

        resized = Image.fromarray(projection).resize(
            (level.size_x, level.size_y),
            Image.Resampling.BILINEAR,
        )
        return np.asarray(resized), data_min, data_max

    def _require_metadata(self) -> IMSMetadata:
        if self._metadata is None:
            raise ImageDatasetError("The dataset is not open.")
        return self._metadata


@dataclass
class ImageSession:
    """Runtime dataset plus source/cache provenance and future analysis layers."""

    dataset: ImageDataset
    relationship: DatasetFileRelationship
    original_source_path: Path
    cache_path: Path | None
    active_backend: str
    messages: tuple[str, ...] = ()
    segmentation_layers: list[object] = field(default_factory=list)
    roi_layers: list[object] = field(default_factory=list)
    measurement_tables: list[object] = field(default_factory=list)

    def close(self) -> None:
        self.dataset.close()

    def __enter__(self) -> ImageSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
