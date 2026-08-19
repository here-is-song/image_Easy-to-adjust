"""Image export pipeline for IMS projections."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, ImageOps

from .color_mapping import additive_merge, apply_pseudocolor, convert_red_to_magenta
from .display_adjustment import apply_display_adjustment, resolve_display_range
from .ims_reader import IMSReader, IMSReaderError
from .models import (
    ChannelMetadata,
    DisplayAdjustmentSettings,
    ExportSettings,
    IMSMetadata,
    ObjectiveDetectionResult,
)
from .objective_detector import apply_manual_objective, detect_objective
from .scalebar import draw_scale_bar


@dataclass(frozen=True)
class ExportResult:
    """One exported file and its reproducibility-relevant computed values."""

    path: Path
    shape: tuple[int, ...]
    dtype: str
    scale_bar_um: float | None
    channel_records: tuple[ChannelExportRecord, ...] = ()


@dataclass(frozen=True)
class ChannelExportRecord:
    """Actual display values used for one exported channel."""

    index: int
    name: str
    display_min: float
    display_max: float
    gamma: float
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


def _write_output_image(path: Path, image: np.ndarray, output_format: str, output_dpi: int) -> None:
    """Write one lossless 8-bit grayscale or RGB figure image."""

    if output_dpi <= 0:
        raise IMSReaderError("Output DPI must be greater than zero.")
    if output_format == "tif":
        photometric = "minisblack" if image.ndim == 2 else "rgb"
        tifffile.imwrite(
            path,
            image,
            photometric=photometric,
            metadata=None,
            resolution=(output_dpi, output_dpi),
            resolutionunit="INCH",
        )
    else:
        Image.fromarray(image).save(path, format="PNG", dpi=(output_dpi, output_dpi))


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
    display_adjustment: DisplayAdjustmentSettings | None = None,
) -> tuple[np.ndarray, float, float, float]:
    # Scientific order: raw intensity -> chunked Z projection -> display adjustment.
    projection, data_min, data_max = reader.project_z_range(channel.index, z_start, z_end)
    display_range = display_adjustment.display_range if display_adjustment is not None else None
    display_min, display_max = display_range or resolve_display_range(
        channel.display_min,
        channel.display_max,
        np.asarray([data_min, data_max]),
    )
    gamma = (
        display_adjustment.gamma
        if display_adjustment is not None and display_adjustment.gamma is not None
        else channel.display_gamma
    )
    return apply_display_adjustment(projection, display_min, display_max, gamma), display_min, display_max, gamma


def render_single_channel(
    reader: IMSReader,
    settings: ExportSettings,
    channel_index: int,
    display_adjustment: DisplayAdjustmentSettings | None = None,
) -> tuple[np.ndarray, ChannelExportRecord]:
    """Create an 8-bit grayscale MIP without writing a file."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before rendering.")
    if not 0 <= channel_index < metadata.channel_count:
        raise IMSReaderError(f"Channel index {channel_index} is out of range.")
    channel = metadata.channels[channel_index]
    image, display_min, display_max, gamma = _project_and_adjust(
        reader, channel, settings.z_start, settings.z_end, display_adjustment
    )
    record = ChannelExportRecord(
        index=channel.index,
        name=channel.name,
        display_min=display_min,
        display_max=display_max,
        gamma=gamma,
        original_color=channel.color,
        output_color=channel.color,
    )
    return image, record


def render_merge(
    reader: IMSReader,
    settings: ExportSettings,
    display_adjustments: Mapping[int, DisplayAdjustmentSettings] | None = None,
) -> tuple[np.ndarray, tuple[ChannelExportRecord, ...]]:
    """Create an additive RGB MIP without writing a file."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before rendering.")
    if not settings.channel_indices:
        raise IMSReaderError("At least one channel must be selected.")
    rendered = render_selected_channels(reader, settings, display_adjustments)
    return merge_rendered_channels(rendered, settings)


def render_selected_channels(
    reader: IMSReader,
    settings: ExportSettings,
    display_adjustments: Mapping[int, DisplayAdjustmentSettings] | None = None,
) -> dict[int, tuple[np.ndarray, ChannelExportRecord]]:
    """Render every selected grayscale channel once for reuse by all outputs."""

    adjustment_overrides = display_adjustments or {}
    return {
        channel_index: render_single_channel(reader, settings, channel_index, adjustment_overrides.get(channel_index))
        for channel_index in settings.channel_indices
    }


def merge_rendered_channels(
    rendered: Mapping[int, tuple[np.ndarray, ChannelExportRecord]],
    settings: ExportSettings,
) -> tuple[np.ndarray, tuple[ChannelExportRecord, ...]]:
    """Create an RGB merge from already-rendered grayscale channels."""

    pseudocolor_images: list[np.ndarray] = []
    records: list[ChannelExportRecord] = []
    for channel_index in settings.channel_indices:
        grayscale, record = rendered[channel_index]
        output_color = convert_red_to_magenta(record.original_color, settings.red_to_magenta)
        pseudocolor_images.append(apply_pseudocolor(grayscale, output_color))
        records.append(
            ChannelExportRecord(
                index=record.index,
                name=record.name,
                display_min=record.display_min,
                display_max=record.display_max,
                gamma=record.gamma,
                original_color=record.original_color,
                output_color=output_color,
            )
        )
    return additive_merge(pseudocolor_images), tuple(records)


def _export_rendered_single_channels(
    reader: IMSReader,
    settings: ExportSettings,
    rendered: Mapping[int, tuple[np.ndarray, ChannelExportRecord]],
    output_directory: str | Path | None,
) -> list[ExportResult]:
    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before exporting.")
    output_dir = Path(output_directory) if output_directory else default_output_directory(metadata.source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_name = sanitize_filename_component(metadata.source_path.stem)
    output_format = _normalized_output_format(settings.output.format)
    results: list[ExportResult] = []
    for channel_index in settings.channel_indices:
        adjusted, record = rendered[channel_index]
        if output_format == "png":
            output_color = convert_red_to_magenta(record.original_color, settings.red_to_magenta)
            adjusted = additive_merge([apply_pseudocolor(adjusted, output_color)])
            record = ChannelExportRecord(
                index=record.index,
                name=record.name,
                display_min=record.display_min,
                display_max=record.display_max,
                gamma=record.gamma,
                original_color=record.original_color,
                output_color=output_color,
            )
        output_image, chosen_scale = prepare_output_image(adjusted, reader, settings)
        filename = f"{source_name}_{sanitize_filename_component(record.name)}.{output_format}"
        output_path = _available_path(output_dir / filename)
        _write_output_image(output_path, output_image, output_format, settings.output.dpi)
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


def _export_rendered_merge(
    reader: IMSReader,
    settings: ExportSettings,
    rendered: Mapping[int, tuple[np.ndarray, ChannelExportRecord]],
    output_directory: str | Path | None,
) -> ExportResult:
    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before exporting.")
    merged, channel_records = merge_rendered_channels(rendered, settings)
    output_image, chosen_scale = prepare_output_image(merged, reader, settings)
    output_dir = Path(output_directory) if output_directory else default_output_directory(metadata.source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_name = sanitize_filename_component(metadata.source_path.stem)
    output_format = _normalized_output_format(settings.output.format)
    output_path = _available_path(output_dir / f"{source_name}_Merge.{output_format}")
    _write_output_image(output_path, output_image, output_format, settings.output.dpi)
    return ExportResult(
        output_path,
        output_image.shape,
        str(output_image.dtype),
        chosen_scale,
        channel_records,
    )


def _resize_for_output(
    image: np.ndarray, settings: ExportSettings
) -> tuple[np.ndarray, float, tuple[int, int, int, int]]:
    width = settings.output.width_px
    height = settings.output.height_px
    if width is None and height is None:
        return image, 1.0, (0, 0, image.shape[1], image.shape[0])
    if width is None or height is None or width <= 0 or height <= 0:
        raise IMSReaderError("Output width and height must both be greater than zero.")
    if image.shape[1] == width and image.shape[0] == height:
        return image, 1.0, (0, 0, width, height)
    mode = settings.output.resize_mode
    if mode not in {"fit", "stretch", "crop"}:
        raise IMSReaderError(f"Unsupported resize mode: {mode}.")
    source_height, source_width = image.shape[:2]
    pil_image = Image.fromarray(image)
    if mode == "stretch":
        resized = pil_image.resize((width, height), Image.Resampling.LANCZOS)
        return (
            np.asarray(resized).copy(),
            width / source_width,
            (0, 0, width, height),
        )
    if mode == "crop":
        resized = ImageOps.fit(pil_image, (width, height), method=Image.Resampling.LANCZOS)
        return (
            np.asarray(resized).copy(),
            max(width / source_width, height / source_height),
            (0, 0, width, height),
        )

    scale = min(width / source_width, height / source_height)
    content_width = max(1, round(source_width * scale))
    content_height = max(1, round(source_height * scale))
    resized = pil_image.resize((content_width, content_height), Image.Resampling.LANCZOS)
    canvas_mode = "L" if image.ndim == 2 else "RGB"
    canvas = Image.new(canvas_mode, (width, height), color=0)
    left = (width - content_width) // 2
    top = (height - content_height) // 2
    canvas.paste(resized, (left, top))
    return (
        np.asarray(canvas).copy(),
        scale,
        (left, top, left + content_width, top + content_height),
    )


def prepare_output_image(
    image: np.ndarray,
    reader: IMSReader,
    settings: ExportSettings,
) -> tuple[np.ndarray, float | None]:
    """Resize a rendered image and draw its scale bar at final-output resolution."""

    output_image, scale_x, content_box = _resize_for_output(image, settings)
    if not settings.scale_bar.enabled:
        return output_image, None
    if reader.metadata is None:
        raise IMSReaderError("IMS metadata is unavailable.")
    return draw_scale_bar(
        output_image,
        voxel_size_x_um=(reader.metadata.extent_x_um / image.shape[1]) / scale_x,
        scale_bar_um=settings.scale_bar.length_um,
        thickness_px=settings.scale_bar.thickness_px,
        font_size_px=settings.scale_bar.font_size_px,
        content_box=content_box,
    )


def export_single_channels(
    reader: IMSReader,
    settings: ExportSettings,
    output_directory: str | Path | None = None,
    display_adjustments: Mapping[int, DisplayAdjustmentSettings] | None = None,
) -> list[ExportResult]:
    """Export channels as grayscale TIFF or RGB pseudocolor PNG images."""

    if not settings.channel_indices:
        raise IMSReaderError("At least one channel must be selected.")
    rendered = render_selected_channels(reader, settings, display_adjustments)
    return _export_rendered_single_channels(reader, settings, rendered, output_directory)


def export_merge(
    reader: IMSReader,
    settings: ExportSettings,
    output_directory: str | Path | None = None,
    display_adjustments: Mapping[int, DisplayAdjustmentSettings] | None = None,
) -> ExportResult:
    """Export selected channels as an additive, 8-bit RGB pseudocolor image."""

    rendered = render_selected_channels(reader, settings, display_adjustments)
    return _export_rendered_merge(reader, settings, rendered, output_directory)


def export_channels_and_merge(
    reader: IMSReader,
    settings: ExportSettings,
    output_directory: str | Path | None = None,
    display_adjustments: Mapping[int, DisplayAdjustmentSettings] | None = None,
) -> list[ExportResult]:
    """Export individual channels and a merge while projecting each channel once."""

    if not settings.channel_indices:
        raise IMSReaderError("At least one channel must be selected.")
    rendered = render_selected_channels(reader, settings, display_adjustments)
    results = _export_rendered_single_channels(reader, settings, rendered, output_directory)
    results.append(_export_rendered_merge(reader, settings, rendered, output_directory))
    return results


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
            "gamma": record.gamma,
            "original_color": list(record.original_color),
            "output_color": list(record.output_color),
        }
        for record in channel_records
    ]
    detected_objective = metadata.objective_detection or detect_objective(metadata)
    selected_objective = apply_manual_objective(detected_objective, settings.objective_override)
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
        "scale_bar_thickness_px": settings.scale_bar.thickness_px,
        "scale_bar_font_size_px": settings.scale_bar.font_size_px,
        "red_to_magenta": settings.red_to_magenta,
        "output_format": _normalized_output_format(settings.output.format),
        "output_width_px": settings.output.width_px,
        "output_height_px": settings.output.height_px,
        "output_dpi": settings.output.dpi,
        "resize_mode": settings.output.resize_mode,
        "acquisition": {
            "recording_date": (
                metadata.acquisition.recording_date.isoformat()
                if metadata.acquisition.recording_date is not None
                else None
            ),
            "microscope_manufacturer": metadata.acquisition.microscope_manufacturer,
            "microscope_model": metadata.acquisition.microscope_model,
            "scan_speed_us_per_pixel": metadata.acquisition.scan_speed_us_per_pixel,
            "objective_name": metadata.acquisition.objective_name,
            "objective_magnification": metadata.acquisition.objective_magnification,
            "numerical_aperture": metadata.acquisition.numerical_aperture,
            "z_section_interval_um": metadata.acquisition.z_section_interval_um,
            "scan_zoom": metadata.acquisition.scan_zoom,
        },
        "objective_detection": _objective_result_payload(detected_objective),
        "selected_objective": _objective_result_payload(selected_objective),
        "channels": channel_info,
        "output_files": [str(result.path) for result in results],
    }
    output_path = _available_path(output_dir / "export_info.json")
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def _summary_number(value: float) -> str:
    return f"{value:.6g}"


def _objective_result_payload(objective: ObjectiveDetectionResult) -> dict[str, object]:
    return {
        "objective_key": objective.objective_key,
        "model": objective.model,
        "magnification": objective.magnification,
        "na": objective.na,
        "immersion": objective.immersion,
        "measured_z_spacing_um": objective.measured_z_spacing_um,
        "expected_z_spacing_um": objective.expected_z_spacing_um,
        "relative_error": objective.relative_error,
        "confidence": objective.confidence,
        "detection_source": objective.detection_source,
        "warning": objective.warning,
    }


def _summary_microscope(metadata: IMSMetadata) -> str:
    manufacturer = metadata.acquisition.microscope_manufacturer
    model = metadata.acquisition.microscope_model
    if manufacturer and model:
        if manufacturer.casefold() in model.casefold():
            return model
        return f"{manufacturer} {model}"
    return manufacturer or model or "Not available"


def _summary_objective(metadata: IMSMetadata, settings: ExportSettings) -> str:
    detected = metadata.objective_detection or detect_objective(metadata)
    selected = apply_manual_objective(detected, settings.objective_override)
    if selected.objective_key is None:
        return "Not available"
    objective = selected.model or selected.objective_key
    if selected.na is not None:
        objective += f" (N.A.{selected.na:.2f})"
    return objective


def format_ppt_summary(metadata: IMSMetadata, settings: ExportSettings) -> str:
    """Format source acquisition details as four copy-ready lines for a PPT."""

    acquisition = metadata.acquisition
    detected = metadata.objective_detection or detect_objective(metadata)
    selected = apply_manual_objective(detected, settings.objective_override)
    date = acquisition.recording_date.strftime("%y%m%d") if acquisition.recording_date is not None else "Not available"
    scan_speed = (
        f"{_summary_number(acquisition.scan_speed_us_per_pixel)} μsecond/pixel"
        if acquisition.scan_speed_us_per_pixel is not None
        else "Not available"
    )
    selected_thickness = (settings.z_end - settings.z_start + 1) * metadata.voxel_size_z_um
    z_interval = selected.measured_z_spacing_um or metadata.voxel_size_z_um
    return (
        f"Date: {date}\n"
        f"Microscope: {_summary_microscope(metadata)}\n"
        f"Scan speed: {scan_speed}, Size: {metadata.size_x}×{metadata.size_y}\n"
        f"Objective lens: {_summary_objective(metadata, settings)}, "
        f"Z-sectioning interval: {_summary_number(z_interval)} μm, "
        f"Z-stack thickness: {_summary_number(selected_thickness)} μm;"
    )


def write_ppt_summary(
    reader: IMSReader,
    settings: ExportSettings,
    output_directory: str | Path | None = None,
) -> Path:
    """Write one copy-ready microscopy acquisition summary beside exported images."""

    metadata = reader.metadata
    if metadata is None:
        raise IMSReaderError("Open the IMS file before writing a PPT summary.")
    output_dir = Path(output_directory) if output_directory else default_output_directory(metadata.source_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_name = sanitize_filename_component(metadata.source_path.stem)
    output_path = _available_path(output_dir / f"{source_name}_PPT_summary.txt")
    output_path.write_text(format_ppt_summary(metadata, settings), encoding="utf-8")
    return output_path
