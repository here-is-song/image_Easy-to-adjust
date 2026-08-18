"""Image export pipeline for IMS projections."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
import tifffile
from PIL import Image

from .color_mapping import additive_merge, apply_pseudocolor, convert_red_to_magenta
from .display_adjustment import apply_display_adjustment, resolve_display_range
from .ims_reader import IMSReader, IMSReaderError
from .models import ChannelMetadata, ExportSettings
from .projection import maximum_intensity_projection
from .scalebar import draw_scale_bar


@dataclass(frozen=True)
class ExportResult:
    """One exported file and its reproducibility-relevant computed values."""

    path: Path
    shape: tuple[int, ...]
    dtype: str
    scale_bar_um: float | None
    channel_records: tuple["ChannelExportRecord", ...] = ()


@dataclass(frozen=True)
class ChannelExportRecord:
    """Actual display values used for one exported channel."""

    index: int
    name: str
    display_min: float
    display_max: float
    original_color: tuple[float, float, float]
    output_color: tuple[float, float, float]


def sanitize_filename_component(value: str) -> str:
    """Replace Windows-forbidden filename characters and empty names."""

    cleaned = re.sub(r'[\\/:*?"<>|]', "_", value).strip().rstrip(".")
    return cleaned or "Channel"


def default_output_directory(source_path: Path) -> Path:
    return source_path.parent / f"{source_path.stem}_Export"


def _normalized_output_format(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized in {"tif", "tiff"}:
        return "tif"
    if normalized == "png":
        return "png"
    raise IMSReaderError(f"Unsupported output format: {value}. Choose tif or png.")


def _write_output_image(path: Path, image: np.ndarray, output_format: str) -> None:
    """Write one lossless 8-bit grayscale or RGB figure image."""

    if output_format == "tif":
        photometric = "minisblack" if image.ndim == 2 else "rgb"
        tifffile.imwrite(path, image, photometric=photometric, metadata=None)
    else:
        Image.fromarray(image).save(path, format="PNG")


def _available_path(path: Path) -> Path:
    """Avoid silently overwriting an earlier scientific figure export."""

    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise IMSReaderError(f"Unable to choose a unique output filename for {path}.")


def _project_and_adjust(
    reader: IMSReader,
    channel: ChannelMetadata,
    z_start: int,
    z_end: int,
    display_range: tuple[float, float] | None = None,
) -> tuple[np.ndarray, float, float]:
    raw_stack = reader.read_z_range(channel.index, z_start, z_end)
    # Scientific order: raw intensity -> Z projection -> display adjustment.
    projection = maximum_intensity_projection(raw_stack)
    display_min, display_max = display_range or resolve_display_range(
        channel.display_min, channel.display_max, raw_stack
    )
    return apply_display_adjustment(projection, display_min, display_max), display_min, display_max


def render_single_channel(
    reader: IMSReader,
    settings: ExportSettings,
    channel_index: int,
    display_range: tuple[float, float] | None = None,
) -> tuple[np.ndarray, ChannelExportRecord]:
    """Create an 8-bit grayscale MIP without writing a file."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before rendering.")
    if not 0 <= channel_index < metadata.channel_count:
        raise IMSReaderError(f"Channel index {channel_index} is out of range.")
    channel = metadata.channels[channel_index]
    image, display_min, display_max = _project_and_adjust(
        reader, channel, settings.z_start, settings.z_end, display_range
    )
    record = ChannelExportRecord(
        index=channel.index,
        name=channel.name,
        display_min=display_min,
        display_max=display_max,
        original_color=channel.color,
        output_color=channel.color,
    )
    return image, record


def render_merge(
    reader: IMSReader,
    settings: ExportSettings,
    display_ranges: Mapping[int, tuple[float, float]] | None = None,
) -> tuple[np.ndarray, tuple[ChannelExportRecord, ...]]:
    """Create an additive RGB MIP without writing a file."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before rendering.")
    if not settings.channel_indices:
        raise IMSReaderError("At least one channel must be selected.")
    range_overrides = display_ranges or {}
    pseudocolor_images: list[np.ndarray] = []
    records: list[ChannelExportRecord] = []
    for channel_index in settings.channel_indices:
        grayscale, record = render_single_channel(
            reader, settings, channel_index, range_overrides.get(channel_index)
        )
        output_color = convert_red_to_magenta(record.original_color, settings.red_to_magenta)
        pseudocolor_images.append(apply_pseudocolor(grayscale, output_color))
        records.append(
            ChannelExportRecord(
                index=record.index,
                name=record.name,
                display_min=record.display_min,
                display_max=record.display_max,
                original_color=record.original_color,
                output_color=output_color,
            )
        )
    return additive_merge(pseudocolor_images), tuple(records)


def _with_optional_scale_bar(
    image: np.ndarray,
    reader: IMSReader,
    settings: ExportSettings,
) -> tuple[np.ndarray, float | None]:
    if not settings.add_scale_bar:
        return image, None
    if reader.metadata is None:
        raise IMSReaderError("IMS metadata is unavailable.")
    return draw_scale_bar(
        image,
        voxel_size_x_um=reader.metadata.voxel_size_x_um,
        scale_bar_um=settings.scale_bar_um,
        thickness_px=settings.scale_bar_thickness_px,
        font_size_px=settings.scale_bar_font_size_px,
    )


def export_single_channels(
    reader: IMSReader,
    settings: ExportSettings,
    output_directory: str | Path | None = None,
    display_ranges: Mapping[int, tuple[float, float]] | None = None,
) -> list[ExportResult]:
    """Export selected channels as independent 8-bit grayscale images."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before exporting.")
    if not settings.channel_indices:
        raise IMSReaderError("At least one channel must be selected.")
    output_dir = Path(output_directory) if output_directory else default_output_directory(metadata.source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_name = sanitize_filename_component(metadata.source_path.stem)
    output_format = _normalized_output_format(settings.output_format)
    results: list[ExportResult] = []
    range_overrides = display_ranges or {}
    for channel_index in settings.channel_indices:
        adjusted, record = render_single_channel(
            reader, settings, channel_index, range_overrides.get(channel_index)
        )
        output_image, chosen_scale = _with_optional_scale_bar(adjusted, reader, settings)
        filename = f"{source_name}_{sanitize_filename_component(record.name)}.{output_format}"
        output_path = _available_path(output_dir / filename)
        _write_output_image(output_path, output_image, output_format)
        results.append(
            ExportResult(
                output_path,
                output_image.shape,
                str(output_image.dtype),
                chosen_scale,
                (record,),
            )
        )
    return results


def export_merge(
    reader: IMSReader,
    settings: ExportSettings,
    output_directory: str | Path | None = None,
    display_ranges: Mapping[int, tuple[float, float]] | None = None,
) -> ExportResult:
    """Export selected channels as an additive, 8-bit RGB pseudocolor image."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before exporting.")
    merged, channel_records = render_merge(reader, settings, display_ranges)
    output_image, chosen_scale = _with_optional_scale_bar(merged, reader, settings)
    output_dir = Path(output_directory) if output_directory else default_output_directory(metadata.source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_name = sanitize_filename_component(metadata.source_path.stem)
    output_format = _normalized_output_format(settings.output_format)
    output_path = _available_path(output_dir / f"{source_name}_Merge.{output_format}")
    _write_output_image(output_path, output_image, output_format)
    return ExportResult(
        output_path,
        output_image.shape,
        str(output_image.dtype),
        chosen_scale,
        channel_records,
    )


def write_export_info(
    reader: IMSReader,
    settings: ExportSettings,
    results: list[ExportResult],
    output_directory: str | Path | None = None,
) -> Path:
    """Write a JSON record describing the exact settings used for an export."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before recording export metadata.")
    if not results:
        raise IMSReaderError("No image results are available for export metadata.")
    output_dir = Path(output_directory) if output_directory else default_output_directory(metadata.source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    channel_records = next(
        (result.channel_records for result in results if len(result.channel_records) > 1),
        tuple(record for result in results for record in result.channel_records),
    )
    scale_bar_um = next((result.scale_bar_um for result in results if result.scale_bar_um is not None), None)
    channel_info = [
        {
            "index": record.index,
            "name": record.name,
            "display_min": record.display_min,
            "display_max": record.display_max,
            "original_color": list(record.original_color),
            "output_color": list(record.output_color),
        }
        for record in channel_records
    ]
    payload = {
        "source_file": metadata.source_path.name,
        "source_path": str(metadata.source_path),
        "z_start_slice": settings.z_start,
        "z_end_slice": settings.z_end,
        "z_start_um": metadata.origin_z_um + (settings.z_start - 1) * metadata.voxel_size_z_um,
        "z_end_um": metadata.origin_z_um + (settings.z_end - 1) * metadata.voxel_size_z_um,
        "selected_thickness_um": (settings.z_end - settings.z_start + 1) * metadata.voxel_size_z_um,
        "projection": "maximum",
        "scale_bar_um": scale_bar_um,
        "scale_bar_thickness_px": settings.scale_bar_thickness_px,
        "scale_bar_font_size_px": settings.scale_bar_font_size_px,
        "red_to_magenta": settings.red_to_magenta,
        "output_format": _normalized_output_format(settings.output_format),
        "channels": channel_info,
        "output_files": [str(result.path) for result in results],
    }
    output_path = _available_path(output_dir / "export_info.json")
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path
