"""Lazy Olympus OIB reader backed by BioIO and OME Bio-Formats."""

from __future__ import annotations

import math
import os
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .ims_reader import FALLBACK_COLORS, KNOWN_CHANNEL_COLORS
from .java_runtime import prepare_jpype_ascii_runtime
from .models import AcquisitionMetadata, ChannelMetadata, IMSMetadata
from .objective_detector import detect_objective


class BioFormatsUnavailableError(RuntimeError):
    """Raised when the optional Bio-Formats runtime is not installed."""


def _configure_bioformats_java() -> None:
    """Choose a full JDK because jgo needs the jar tool during first startup."""

    # bffile defaults to the smaller zulu-jre distribution. Its Java runtime can
    # execute Bio-Formats, but jgo also inspects downloaded JARs using jar.exe.
    # Respect explicit user configuration while making the default work on Windows.
    os.environ.setdefault("BFF_JAVA_VENDOR", "zulu")
    os.environ.setdefault("BFF_JAVA_VERSION", "11")
    prepare_jpype_ascii_runtime()


def _positive_float(value: object) -> float | None:
    if value is None:
        return None
    magnitude = getattr(value, "magnitude", value)
    try:
        numeric = float(magnitude)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric > 0 else None


def _metadata_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _visible_wavelength_color(wavelength_nm: float | None) -> tuple[float, float, float] | None:
    """Approximate a visible wavelength LUT; return None outside 380–750 nm."""

    if wavelength_nm is None or not 380.0 <= wavelength_nm <= 750.0:
        return None
    wavelength = float(wavelength_nm)
    if wavelength < 440:
        red, green, blue = -(wavelength - 440) / 60, 0.0, 1.0
    elif wavelength < 490:
        red, green, blue = 0.0, (wavelength - 440) / 50, 1.0
    elif wavelength < 510:
        red, green, blue = 0.0, 1.0, -(wavelength - 510) / 20
    elif wavelength < 580:
        red, green, blue = (wavelength - 510) / 70, 1.0, 0.0
    elif wavelength < 645:
        red, green, blue = 1.0, -(wavelength - 645) / 65, 0.0
    else:
        red, green, blue = 1.0, 0.0, 0.0
    return float(red), float(green), float(blue)


def _ome_color(value: object) -> tuple[float, float, float] | None:
    if value is None:
        return None
    try:
        red, green, blue = value.as_rgb_tuple()
    except (AttributeError, TypeError, ValueError):
        return None
    return red / 255.0, green / 255.0, blue / 255.0


def _fallback_color(
    name: str,
    index: int,
    emission_wavelength_nm: float | None,
    excitation_wavelength_nm: float | None,
) -> tuple[float, float, float]:
    normalized_name = " ".join(name.casefold().split())
    known_color = next(
        (color for known_name, color in KNOWN_CHANNEL_COLORS.items() if known_name in normalized_name),
        None,
    )
    if known_color is not None:
        return known_color
    wavelength_color = _visible_wavelength_color(emission_wavelength_nm or excitation_wavelength_nm)
    return wavelength_color or FALLBACK_COLORS[index % len(FALLBACK_COLORS)]


def _extract_original_dye_names(ome: object, channel_count: int) -> dict[int, str]:
    """Read Olympus DyeName entries retained as OME OriginalMetadata."""

    dye_names: dict[int, str] = {}
    pattern = re.compile(r"^\[(?:GUI )?Channel (\d+) Parameters\]\s*DyeName$", re.IGNORECASE)
    for annotation in getattr(ome, "structured_annotations", ()):
        namespace = str(getattr(annotation, "namespace", "") or "")
        if not namespace.endswith("OriginalMetadata"):
            continue
        value = getattr(annotation, "value", None)
        for element in getattr(value, "any_elements", ()):
            key = None
            original_value = None
            for child in getattr(element, "children", ()):
                local_name = str(getattr(child, "qname", "")).rsplit("}", 1)[-1]
                if local_name == "Key":
                    key = _metadata_text(getattr(child, "text", None))
                elif local_name == "Value":
                    original_value = _metadata_text(getattr(child, "text", None))
            if key is None or original_value is None or original_value.casefold() in {"none", "unknown"}:
                continue
            match = pattern.fullmatch(key)
            if match is None:
                continue
            index = int(match.group(1)) - 1
            if 0 <= index < channel_count:
                dye_names[index] = original_value
    return dye_names


class BioFormatsBackend:
    """Read OIB metadata and T/C/Z/Y/X blocks without materializing the full file."""

    backend_name = "BioFormatsBackend"

    def __init__(self, path: str | Path, tile_size: tuple[int, int] = (512, 512)) -> None:
        self.path = Path(path)
        self.tile_size = tile_size
        self.metadata: IMSMetadata | None = None
        self._image: Any | None = None

    @staticmethod
    def is_available() -> bool:
        _configure_bioformats_java()
        try:
            import bioio  # noqa: F401
            import bioio_bioformats  # noqa: F401
        except ImportError:
            return False
        return True

    def open(self) -> IMSMetadata:
        if not self.path.is_file():
            raise FileNotFoundError(f"OIB file not found: {self.path}")
        _configure_bioformats_java()
        try:
            from bioio import BioImage
            from bioio_bioformats import Reader
            from scyjava import config as scyjava_config
        except ImportError as exc:
            raise BioFormatsUnavailableError(
                'OIB support requires the optional dependencies. Install with: pip install -e ".[oib]"'
            ) from exc
        aircompressor = "io.airlift:aircompressor:2.0.3"
        if aircompressor not in scyjava_config.endpoints:
            scyjava_config.endpoints.append(aircompressor)
        try:
            self._image = BioImage(
                self.path,
                reader=Reader,
                reconstruct_mosaic=True,
                dask_tiles=True,
                tile_size=self.tile_size,
                original_meta=True,
            )
            self.metadata = self._parse_metadata()
        except Exception:
            self.close()
            raise
        return self.metadata

    def close(self) -> None:
        if self._image is not None:
            reader = getattr(self._image, "reader", None)
            bio_file = getattr(reader, "_bf", None)
            close = getattr(bio_file, "close", None)
            if callable(close):
                close()
        self._image = None
        self.metadata = None

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
        if self._image is None:
            raise RuntimeError("The Bio-Formats dataset is not open.")
        lazy_stack = self._image.get_image_dask_data("ZYX", T=time_index, C=channel_index)
        block = lazy_stack[z_start:z_end, y_start:y_end, x_start:x_end]
        compute = getattr(block, "compute", None)
        array = compute() if callable(compute) else block
        return np.ascontiguousarray(np.asarray(array))

    def _parse_metadata(self) -> IMSMetadata:
        if self._image is None:
            raise RuntimeError("The Bio-Formats dataset is not open.")
        image = self._image
        dims = image.dims
        size_x = int(dims.X)
        size_y = int(dims.Y)
        size_z = int(dims.Z)
        size_c = int(dims.C)
        size_t = int(dims.T)
        warnings: list[str] = []
        if len(image.scenes) > 1:
            warnings.append("This OIB contains multiple scenes; the first scene is used.")
        if size_t > 1:
            warnings.append("This OIB contains multiple time points; IEA viewing currently uses TimePoint 0.")

        physical = image.physical_pixel_sizes
        pixel_x = _positive_float(getattr(physical, "X", None))
        pixel_y = _positive_float(getattr(physical, "Y", None))
        pixel_z = _positive_float(getattr(physical, "Z", None))
        if pixel_x is None or pixel_y is None:
            warnings.append("Bio-Formats did not provide reliable PhysicalSizeX/PhysicalSizeY metadata.")
        if pixel_z is None:
            warnings.append("Bio-Formats did not provide reliable PhysicalSizeZ metadata.")

        ome = image.ome_metadata
        ome_image = ome.images[image.current_scene_index]
        ome_channels = tuple(ome_image.pixels.channels)
        original_dye_names = _extract_original_dye_names(ome, size_c)
        channel_names = tuple(image.channel_names)
        channels: list[ChannelMetadata] = []
        for index in range(size_c):
            ome_channel = ome_channels[index] if index < len(ome_channels) else None
            name = (
                original_dye_names.get(index)
                or _metadata_text(getattr(ome_channel, "name", None))
                or (str(channel_names[index]).strip() if index < len(channel_names) else "")
                or f"Channel {index + 1}"
            )
            excitation = _positive_float(getattr(ome_channel, "excitation_wavelength", None))
            emission = _positive_float(getattr(ome_channel, "emission_wavelength", None))
            color = _ome_color(getattr(ome_channel, "color", None))
            if color == (1.0, 1.0, 1.0) and index in original_dye_names:
                color = None
            if color is None:
                color = _fallback_color(name, index, emission, excitation)
                warnings.append(f"Color metadata missing for {name}; IEA fallback color {color} is used.")
            channels.append(
                ChannelMetadata(
                    index=index,
                    name=name,
                    color=color,
                    display_min=None,
                    display_max=None,
                    display_gamma=1.0,
                    dataset_path=f"BioFormats:Scene{image.current_scene_index}/Channel {index}",
                    axis_order=("Z", "Y", "X"),
                    display_range_source="oib_missing",
                    display_gamma_source="oib_default",
                    excitation_wavelength_nm=excitation,
                    emission_wavelength_nm=emission,
                )
            )

        acquisition = self._parse_acquisition(ome, ome_image)
        metadata = IMSMetadata(
            source_path=self.path.resolve(),
            size_x=size_x,
            size_y=size_y,
            size_z=size_z,
            voxel_size_x_um=pixel_x,
            voxel_size_y_um=pixel_y,
            voxel_size_z_um=pixel_z,
            origin_x_um=None,
            origin_y_um=None,
            origin_z_um=None,
            extent_x_um=pixel_x * size_x if pixel_x is not None else None,
            extent_y_um=pixel_y * size_y if pixel_y is not None else None,
            extent_z_um=pixel_z * size_z if pixel_z is not None else None,
            unit="µm",
            dtype=str(np.dtype(image.dtype)),
            time_point_count=size_t,
            channels=tuple(channels),
            source_format="OIB",
            acquisition=acquisition,
            warnings=tuple(warnings),
            raw_metadata={
                "reader": "Bio-Formats",
                "scene": str(image.current_scene),
                "scene_count": len(image.scenes),
                "ome_xml": getattr(image.reader, "ome_xml", None),
            },
        )
        return replace(
            metadata,
            objective_detection=detect_objective(
                metadata,
                pixel_size_x_um=pixel_x,
                pixel_size_y_um=pixel_y,
                image_width_px=size_x,
                image_height_px=size_y,
            ),
        )

    @staticmethod
    def _parse_acquisition(ome: object, ome_image: object) -> AcquisitionMetadata:
        instrument_ref = getattr(getattr(ome_image, "instrument_ref", None), "id", None)
        instrument = next(
            (item for item in getattr(ome, "instruments", ()) if getattr(item, "id", None) == instrument_ref),
            None,
        )
        microscope = getattr(instrument, "microscope", None)
        objective_ref = getattr(getattr(ome_image, "objective_settings", None), "id", None)
        objective = next(
            (
                item
                for item in getattr(instrument, "objectives", ())
                if getattr(item, "id", None) == objective_ref
            ),
            None,
        )
        acquisition_date = getattr(ome_image, "acquisition_date", None)
        if acquisition_date is not None and not isinstance(acquisition_date, datetime):
            acquisition_date = getattr(acquisition_date, "value", None)
        return AcquisitionMetadata(
            recording_date=acquisition_date if isinstance(acquisition_date, datetime) else None,
            microscope_manufacturer=_metadata_text(getattr(microscope, "manufacturer", None)),
            microscope_model=_metadata_text(getattr(microscope, "model", None)),
            objective_name=(
                _metadata_text(getattr(objective, "model", None))
                or _metadata_text(getattr(objective, "manufacturer", None))
            ),
            objective_magnification=_positive_float(
                getattr(objective, "nominal_magnification", None)
                or getattr(objective, "calibrated_magnification", None)
            ),
            numerical_aperture=_positive_float(getattr(objective, "lens_na", None)),
        )
