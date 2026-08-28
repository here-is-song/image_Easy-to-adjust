"""TIFF/OME-TIFF pixel backend with normalized T/C/Z/Y/X axes."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np
import tifffile

from .image_dataset import ImageDatasetError
from .models import AcquisitionMetadata, ChannelMetadata, IMSMetadata
from .objective_detector import detect_objective

TIFF_FALLBACK_COLORS: tuple[tuple[float, float, float], ...] = (
    (0.0, 1.0, 0.0),
    (1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0),
    (1.0, 1.0, 0.0),
    (0.0, 1.0, 1.0),
    (1.0, 0.0, 1.0),
)
RGB_SAMPLE_NAMES: tuple[str, ...] = ("Red", "Green", "Blue", "Alpha")
RGB_SAMPLE_COLORS: tuple[tuple[float, float, float], ...] = (
    (1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 0.0, 1.0),
    (1.0, 1.0, 1.0),
)


class TIFFReaderError(ImageDatasetError):
    """Raised when a TIFF cannot be normalized safely."""


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _resolution_float(value: object) -> float | None:
    """Convert TIFF rational or numeric resolution values to a positive float."""

    if isinstance(value, tuple) and len(value) == 2:
        numerator = _positive_float(value[0])
        denominator = _positive_float(value[1])
        return numerator / denominator if numerator is not None and denominator is not None else None
    return _positive_float(value)


def _length_um(value: object, unit: object) -> float | None:
    number = _positive_float(value)
    if number is None:
        return None
    normalized = str(unit or "µm").strip().casefold().replace("μ", "µ")
    factors = {
        "m": 1_000_000.0,
        "cm": 10_000.0,
        "mm": 1_000.0,
        "µm": 1.0,
        "um": 1.0,
        "micron": 1.0,
        "microns": 1.0,
        "micrometer": 1.0,
        "micrometers": 1.0,
        "micrometre": 1.0,
        "micrometres": 1.0,
        "nm": 0.001,
    }
    factor = factors.get(normalized)
    return number * factor if factor is not None else None


def _ome_channel_color(value: object) -> tuple[float, float, float] | None:
    """Decode the signed 32-bit RGBA color used by OME Channel metadata."""

    try:
        rgba = int(str(value)) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None
    return (
        ((rgba >> 24) & 0xFF) / 255.0,
        ((rgba >> 16) & 0xFF) / 255.0,
        ((rgba >> 8) & 0xFF) / 255.0,
    )


def _page_pixel_sizes_um(
    page: tifffile.TiffPage,
    imagej: dict[str, object],
) -> tuple[float | None, float | None, str | None]:
    """Read physical pixel size from standard TIFF resolution tags when possible."""

    x_tag = page.tags.get("XResolution")
    y_tag = page.tags.get("YResolution")
    x_resolution = _resolution_float(x_tag.value) if x_tag is not None else None
    y_resolution = _resolution_float(y_tag.value) if y_tag is not None else None
    if x_resolution is None or y_resolution is None:
        return None, None, None

    unit_tag = page.tags.get("ResolutionUnit")
    unit_value = unit_tag.value if unit_tag is not None else None
    unit_name = str(getattr(unit_value, "name", unit_value or "")).strip().upper()
    if unit_name in {"2", "INCH"}:
        return 25_400.0 / x_resolution, 25_400.0 / y_resolution, "TIFF resolution tags (inch)"
    if unit_name in {"3", "CENTIMETER", "CENTIMETRE"}:
        return 10_000.0 / x_resolution, 10_000.0 / y_resolution, "TIFF resolution tags (cm)"

    imagej_unit = str(imagej.get("unit") or "").strip()
    one_unit_um = _length_um(1.0, imagej_unit) if imagej_unit else None
    if one_unit_um is not None:
        return one_unit_um / x_resolution, one_unit_um / y_resolution, "ImageJ resolution metadata"
    return None, None, None


def _parse_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate.rstrip("Z"))
        except ValueError:
            continue
    for pattern in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None


def _infer_axes(shape: tuple[int, ...]) -> tuple[str, tuple[str, ...]]:
    warnings = (f"TIFF axes were not declared; inferred from shape {shape}.",)
    if len(shape) == 2:
        return "YX", warnings
    if len(shape) == 3:
        return ("YXS" if shape[-1] in {3, 4} else "ZYX"), warnings
    if len(shape) == 4:
        return ("ZYXS" if shape[-1] in {3, 4} else "CZYX"), warnings
    raise TIFFReaderError(f"TIFF shape {shape} has no declared axes and cannot be inferred safely.")


def _normalize_to_tczyx(array: np.ndarray, axes: str) -> tuple[np.ndarray, tuple[str, ...]]:
    """Normalize common TIFF axes without changing voxel values."""

    data = np.asarray(array)
    normalized_axes = axes.upper().replace(" ", "")
    warnings: list[str] = []
    if len(normalized_axes) != data.ndim or "X" not in normalized_axes or "Y" not in normalized_axes:
        normalized_axes, inferred = _infer_axes(tuple(data.shape))
        warnings.extend(inferred)

    axis_names = list(normalized_axes)
    for required in ("X", "Y"):
        if axis_names.count(required) != 1:
            raise TIFFReaderError(f"TIFF axis order {normalized_axes!r} must contain one {required} axis.")

    unknown_non_single = [
        index
        for index, name in enumerate(axis_names)
        if name not in {"T", "C", "Z", "Y", "X", "S"} and data.shape[index] > 1
    ]
    if unknown_non_single:
        if "Z" not in axis_names and len(unknown_non_single) == 1:
            index = unknown_non_single[0]
            warnings.append(f"TIFF axis {axis_names[index]} was treated as Z.")
            axis_names[index] = "Z"
        else:
            names = ", ".join(axis_names[index] for index in unknown_non_single)
            raise TIFFReaderError(f"Unsupported non-singleton TIFF axes: {names}.")

    squeeze_axes = [
        index
        for index, name in enumerate(axis_names)
        if name not in {"T", "C", "Z", "Y", "X", "S"} and data.shape[index] == 1
    ]
    for index in reversed(squeeze_axes):
        data = np.squeeze(data, axis=index)
        axis_names.pop(index)

    for unique in ("T", "Z", "Y", "X"):
        if axis_names.count(unique) > 1:
            raise TIFFReaderError(f"TIFF axis {unique} occurs more than once.")
    channel_axes = [index for index, name in enumerate(axis_names) if name in {"C", "S"}]
    order = []
    for name in ("T",):
        order.extend(index for index, axis in enumerate(axis_names) if axis == name)
    order.extend(channel_axes)
    for name in ("Z", "Y", "X"):
        order.extend(index for index, axis in enumerate(axis_names) if axis == name)
    if len(order) != data.ndim:
        raise TIFFReaderError(f"Unsupported TIFF axis order: {''.join(axis_names)}.")
    data = np.transpose(data, order)

    has_t = "T" in axis_names
    has_z = "Z" in axis_names
    channel_shape = tuple(
        data.shape[(1 if has_t else 0) + offset] for offset in range(len(channel_axes))
    )
    channel_count = math.prod(channel_shape) if channel_shape else 1
    cursor = 0
    time_count = data.shape[cursor] if has_t else 1
    cursor += int(has_t)
    cursor += len(channel_axes)
    z_count = data.shape[cursor] if has_z else 1
    y_count, x_count = data.shape[-2:]
    normalized = data.reshape(time_count, channel_count, z_count, y_count, x_count)
    return np.ascontiguousarray(normalized), tuple(warnings)


def _ome_metadata(xml: str | None) -> dict[str, object]:
    if not xml:
        return {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return {}
    image = next((element for element in root.iter() if _local_name(element) == "Image"), None)
    pixels = (
        next((element for element in image if _local_name(element) == "Pixels"), None)
        if image is not None
        else None
    )
    if pixels is None:
        return {}
    channel_elements = [element for element in pixels if _local_name(element) == "Channel"]
    channel_names = [
        channel.attrib.get("Name") or f"Channel {index}"
        for index, channel in enumerate(channel_elements)
    ]
    channel_colors = [_ome_channel_color(channel.attrib.get("Color")) for channel in channel_elements]
    acquisition_date = next(
        (element.text for element in image if _local_name(element) == "AcquisitionDate"),
        None,
    )
    microscope = next((element for element in root.iter() if _local_name(element) == "Microscope"), None)
    objective = next((element for element in root.iter() if _local_name(element) == "Objective"), None)
    return {
        "pixel_size_x_um": _length_um(
            pixels.attrib.get("PhysicalSizeX"), pixels.attrib.get("PhysicalSizeXUnit")
        ),
        "pixel_size_y_um": _length_um(
            pixels.attrib.get("PhysicalSizeY"), pixels.attrib.get("PhysicalSizeYUnit")
        ),
        "z_spacing_um": _length_um(
            pixels.attrib.get("PhysicalSizeZ"), pixels.attrib.get("PhysicalSizeZUnit")
        ),
        "channel_names": channel_names,
        "channel_colors": channel_colors,
        "recording_date": _parse_datetime(acquisition_date),
        "microscope_manufacturer": microscope.attrib.get("Manufacturer") if microscope is not None else None,
        "microscope_model": microscope.attrib.get("Model") if microscope is not None else None,
        "objective_name": objective.attrib.get("Model") if objective is not None else None,
        "objective_magnification": (
            _positive_float(objective.attrib.get("NominalMagnification")) if objective is not None else None
        ),
        "numerical_aperture": _positive_float(objective.attrib.get("LensNA")) if objective is not None else None,
    }


class TIFFPixelBackend:
    """Read the first TIFF series and expose normalized T/C/Z/Y/X blocks."""

    backend_name = "TIFFPixelBackend"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.metadata: IMSMetadata | None = None
        self._tiff: tifffile.TiffFile | None = None
        self._data: np.ndarray | None = None

    def open(self) -> IMSMetadata:
        if not self.path.is_file():
            raise FileNotFoundError(f"TIFF file not found: {self.path}")
        try:
            self._tiff = tifffile.TiffFile(self.path)
            if not self._tiff.series:
                raise TIFFReaderError("TIFF contains no readable image series.")
            series = self._tiff.series[0]
            raw = series.asarray()
            declared_axes = str(series.axes or "")
            data, axis_warnings = _normalize_to_tczyx(raw, declared_axes)
            self._data = data
            ome = _ome_metadata(self._tiff.ome_metadata)
            imagej = self._tiff.imagej_metadata or {}
            tag_pixel_x, tag_pixel_y, calibration_source = _page_pixel_sizes_um(
                self._tiff.pages[0], imagej
            )
            pixel_x = _positive_float(ome.get("pixel_size_x_um")) or tag_pixel_x
            pixel_y = _positive_float(ome.get("pixel_size_y_um")) or tag_pixel_y
            z_spacing = _positive_float(ome.get("z_spacing_um")) or _length_um(
                imagej.get("spacing"), imagej.get("unit")
            )
            time_count, channel_count, size_z, size_y, size_x = data.shape
            names = list(ome.get("channel_names") or [])
            colors = list(ome.get("channel_colors") or [])
            axes_upper = declared_axes.upper()
            sample_axis = axes_upper.find("S")
            is_rgb_samples = (
                sample_axis >= 0
                and "C" not in axes_upper
                and raw.shape[sample_axis] in {3, 4}
                and channel_count == raw.shape[sample_axis]
            )
            channels = tuple(
                ChannelMetadata(
                    index=index,
                    name=(
                        RGB_SAMPLE_NAMES[index]
                        if is_rgb_samples
                        else str(names[index])
                        if index < len(names)
                        else f"Channel {index}"
                    ),
                    color=(
                        RGB_SAMPLE_COLORS[index]
                        if is_rgb_samples
                        else colors[index]
                        if index < len(colors) and colors[index] is not None
                        else TIFF_FALLBACK_COLORS[index % len(TIFF_FALLBACK_COLORS)]
                    ),
                    display_min=float(np.min(data[:, index])),
                    display_max=float(np.max(data[:, index])),
                    display_gamma=1.0,
                    dataset_path=f"TIFF series 0 / channel {index}",
                    axis_order=("Z", "Y", "X"),
                    display_range_source="tiff_data",
                    display_gamma_source="default",
                )
                for index in range(channel_count)
            )
            use_mvx10_defaults = not any(
                ome.get(key)
                for key in (
                    "microscope_manufacturer",
                    "microscope_model",
                    "objective_name",
                    "objective_magnification",
                )
            )
            acquisition = AcquisitionMetadata(
                recording_date=(
                    ome.get("recording_date")
                    if isinstance(ome.get("recording_date"), datetime)
                    else self._page_datetime()
                ),
                microscope_manufacturer=(
                    str(ome.get("microscope_manufacturer") or "Olympus")
                    if use_mvx10_defaults or ome.get("microscope_manufacturer")
                    else None
                ),
                microscope_model=(
                    str(ome.get("microscope_model") or "MVX10")
                    if use_mvx10_defaults or ome.get("microscope_model")
                    else None
                ),
                objective_name=(
                    str(ome.get("objective_name") or "MV PLAPO 2XC")
                    if use_mvx10_defaults or ome.get("objective_name")
                    else None
                ),
                objective_magnification=(
                    _positive_float(ome.get("objective_magnification"))
                    or (2.0 if use_mvx10_defaults else None)
                ),
                numerical_aperture=_positive_float(ome.get("numerical_aperture")),
                z_section_interval_um=z_spacing,
                scan_zoom=1.25 if use_mvx10_defaults else None,
            )
            warnings = list(axis_warnings)
            if use_mvx10_defaults:
                warnings.append(
                    "TIFF microscope defaults use Olympus MVX10, MV PLAPO 2XC, Zoom 1.25X; verify them before export."
                )
            if calibration_source is not None and not ome.get("pixel_size_x_um"):
                warnings.append(
                    f"Physical X/Y calibration came from {calibration_source}; verify that it represents "
                    "microscope pixel size rather than display/print DPI."
                )
            if pixel_x is None or pixel_y is None:
                warnings.append(
                    "TIFF physical X/Y calibration is missing; use File > Edit Image Metadata "
                    "before enabling a scale bar."
                )
            if time_count > 1:
                warnings.append(
                    f"TIFF contains {time_count} time points; IEA currently previews and exports TimePoint 0."
                )
            metadata = IMSMetadata(
                source_path=self.path.resolve(),
                size_x=size_x,
                size_y=size_y,
                size_z=size_z,
                voxel_size_x_um=pixel_x,
                voxel_size_y_um=pixel_y,
                voxel_size_z_um=z_spacing,
                origin_x_um=0.0 if pixel_x is not None else None,
                origin_y_um=0.0 if pixel_y is not None else None,
                origin_z_um=0.0 if z_spacing is not None else None,
                extent_x_um=pixel_x * size_x if pixel_x is not None else None,
                extent_y_um=pixel_y * size_y if pixel_y is not None else None,
                extent_z_um=z_spacing * size_z if z_spacing is not None else None,
                unit="µm",
                dtype=str(data.dtype),
                time_point_count=time_count,
                channels=channels,
                source_format="TIFF",
                acquisition=acquisition,
                warnings=tuple(warnings),
                raw_metadata={
                    "tiff_axes": declared_axes,
                    "tiff_shape": tuple(series.shape),
                    "imagej_metadata": dict(imagej),
                    "physical_calibration_source": (
                        "OME PhysicalSize" if ome.get("pixel_size_x_um") else calibration_source
                    ),
                },
            )
            metadata = replace(metadata, objective_detection=detect_objective(metadata))
            self.metadata = metadata
            return metadata
        except Exception:
            self.close()
            raise

    def _page_datetime(self) -> datetime | None:
        if self._tiff is None or not self._tiff.pages:
            return None
        tag = self._tiff.pages[0].tags.get("DateTime")
        return _parse_datetime(tag.value if tag is not None else None)

    def close(self) -> None:
        self._data = None
        if self._tiff is not None:
            self._tiff.close()
        self._tiff = None

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
        if self._data is None:
            raise TIFFReaderError("Open the TIFF before reading pixels.")
        return np.asarray(
            self._data[
                time_index,
                channel_index,
                z_start:z_end,
                y_start:y_end,
                x_start:x_end,
            ]
        )
