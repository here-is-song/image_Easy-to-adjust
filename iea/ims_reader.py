"""Read-only, lazy reader for Bitplane Imaris IMS (HDF5) files."""

from __future__ import annotations

import itertools
import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from .metadata import (
    get_attribute,
    normalize_attribute,
    parse_int,
    parse_number_list,
    unit_scale_to_um,
)
from .models import AcquisitionMetadata, ChannelMetadata, IMSMetadata
from .objective_detector import detect_objective


class IMSReaderError(RuntimeError):
    """Raised when an IMS file cannot be read safely or unambiguously."""


FALLBACK_COLORS: tuple[tuple[float, float, float], ...] = (
    (0.0, 1.0, 0.0),
    (1.0, 0.0, 1.0),
    (0.0, 0.0, 1.0),
    (0.0, 1.0, 1.0),
    (1.0, 1.0, 0.0),
    (1.0, 1.0, 1.0),
)


def _natural_key(name: str) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name))


def _child_casefold(group: h5py.Group, name: str) -> h5py.Group | h5py.Dataset | None:
    for key in group.keys():
        if key.casefold() == name.casefold():
            return group[key]
    return None


def _indexed_groups(group: h5py.Group, prefix: str) -> list[h5py.Group]:
    pattern = re.compile(rf"^{re.escape(prefix.strip())}\s+(\d+)$", re.IGNORECASE)
    matches = [
        child
        for key in sorted(group.keys(), key=_natural_key)
        if pattern.fullmatch(key) and isinstance((child := group[key]), h5py.Group)
    ]
    return matches


class IMSReader:
    """Own an HDF5 handle and expose normalized, Z/Y/X-oriented reads."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file: h5py.File | None = None
        self.metadata: IMSMetadata | None = None

    def open(self) -> IMSMetadata:
        """Open the source read-only and parse metadata without loading image stacks."""

        self.close()
        if not self.path.is_file():
            raise IMSReaderError(f"File not found: {self.path}")
        try:
            self._file = h5py.File(self.path, "r")
        except OSError as exc:
            raise IMSReaderError(f"Not an HDF5/IMS file: {exc}") from exc
        try:
            self.metadata = self._parse_metadata()
        except Exception:
            self.close()
            raise
        return self.metadata

    def close(self) -> None:
        """Close the current HDF5 handle."""

        if self._file is not None:
            self._file.close()
        self._file = None
        self.metadata = None

    def __enter__(self) -> IMSReader:
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _require_file(self) -> h5py.File:
        if self._file is None:
            raise IMSReaderError("IMS file is not open.")
        return self._file

    def _parse_metadata(self) -> IMSMetadata:
        h5_file = self._require_file()
        warnings: list[str] = []
        dataset_root = _child_casefold(h5_file, "DataSet")
        if not isinstance(dataset_root, h5py.Group):
            raise IMSReaderError("Invalid IMS structure: /DataSet was not found.")
        resolution = _child_casefold(dataset_root, "ResolutionLevel 0")
        if not isinstance(resolution, h5py.Group):
            raise IMSReaderError("Invalid IMS structure: ResolutionLevel 0 was not found.")
        time_points = _indexed_groups(resolution, "TimePoint ")
        if not time_points:
            raise IMSReaderError("Invalid IMS structure: no TimePoint groups were found.")
        time_point = next(
            (group for group in time_points if group.name.rsplit("/", 1)[-1].casefold() == "timepoint 0"),
            None,
        )
        if time_point is None:
            raise IMSReaderError("Invalid IMS structure: TimePoint 0 was not found.")
        if len(time_points) > 1:
            warnings.append("This file contains multiple time points; TimePoint 0 only is used.")
        channel_groups = _indexed_groups(time_point, "Channel ")
        if not channel_groups:
            raise IMSReaderError("Invalid IMS structure: no channel image data were found.")
        for expected_index, channel_group in enumerate(channel_groups):
            stored_index = int(channel_group.name.rsplit(" ", 1)[-1])
            if stored_index != expected_index:
                raise IMSReaderError(
                    "Invalid IMS structure: channel groups must be numbered "
                    f"continuously from 0; found Channel {stored_index} at position {expected_index}."
                )

        first_data = self._find_data_dataset(channel_groups[0])
        if first_data.ndim != 3:
            raise IMSReaderError(f"Unsupported image rank {first_data.ndim}; expected a 3D stack.")
        self._validate_dtype(first_data.dtype)

        image_info, dataset_info = self._metadata_groups(h5_file)
        reported_sizes = self._read_sizes(image_info)
        if reported_sizes is None:
            size_z, size_y, size_x = (int(value) for value in first_data.shape)
            sizes = {"X": size_x, "Y": size_y, "Z": size_z}
            warnings.append("Image dimensions were missing; dataset storage was interpreted as Z, Y, X.")
            axis_order = ("Z", "Y", "X")
        else:
            sizes, axis_order, size_warning = self._resolve_sizes_from_data(first_data.shape, reported_sizes)
            if size_warning:
                warnings.append(size_warning)
        axis_warning = self._axis_ambiguity_warning(first_data.shape, sizes, axis_order)
        if axis_warning:
            warnings.append(axis_warning)

        unit_value = get_attribute(image_info.attrs, "Unit") if image_info is not None else None
        unit_text = str(unit_value).strip() if unit_value not in (None, "") else "um"
        factor = unit_scale_to_um(unit_text)
        if unit_value in (None, ""):
            warnings.append("Physical unit was missing; extent values are assumed to be um.")
            factor = 1.0
        elif factor is None:
            warnings.append(f"Unknown physical unit {unit_text!r}; extent values are assumed to be um.")
            factor = 1.0

        extents, origins = self._read_extents(image_info, sizes, factor, warnings)
        channels: list[ChannelMetadata] = []
        for index, channel_group in enumerate(channel_groups):
            data = self._find_data_dataset(channel_group)
            if data.ndim != 3:
                raise IMSReaderError(f"Channel {index} is not a 3D stack.")
            self._validate_dtype(data.dtype)
            channel_axis_order, channel_warning = self._infer_axis_order(data.shape, sizes)
            if channel_warning and channel_warning not in warnings:
                warnings.append(channel_warning)
            channel_info = self._channel_info_group(dataset_info, index)
            channels.append(self._parse_channel(index, channel_info, data, channel_axis_order, warnings))

        size_x, size_y, size_z = sizes["X"], sizes["Y"], sizes["Z"]
        acquisition = self._parse_acquisition_metadata(image_info, dataset_info)
        metadata = IMSMetadata(
            source_path=self.path.resolve(),
            size_x=size_x,
            size_y=size_y,
            size_z=size_z,
            voxel_size_x_um=extents["X"] / size_x,
            voxel_size_y_um=extents["Y"] / size_y,
            voxel_size_z_um=extents["Z"] / size_z,
            origin_x_um=origins["X"],
            origin_y_um=origins["Y"],
            origin_z_um=origins["Z"],
            extent_x_um=extents["X"],
            extent_y_um=extents["Y"],
            extent_z_um=extents["Z"],
            unit="µm",
            dtype=str(first_data.dtype),
            time_point_count=len(time_points),
            channels=tuple(channels),
            acquisition=acquisition,
            warnings=tuple(warnings),
        )
        return replace(
            metadata,
            objective_detection=detect_objective(
                metadata,
                pixel_size_x_um=metadata.voxel_size_x_um,
                pixel_size_y_um=metadata.voxel_size_y_um,
                image_width_px=metadata.size_x,
                image_height_px=metadata.size_y,
            ),
        )

    @staticmethod
    def _metadata_groups(h5_file: h5py.File) -> tuple[h5py.Group | None, h5py.Group | None]:
        dataset_info = _child_casefold(h5_file, "DataSetInfo")
        if not isinstance(dataset_info, h5py.Group):
            return None, None
        image_info = _child_casefold(dataset_info, "Image")
        return (image_info if isinstance(image_info, h5py.Group) else None), dataset_info

    @staticmethod
    def _parse_acquisition_metadata(
        image_info: h5py.Group | None,
        dataset_info: h5py.Group | None,
    ) -> AcquisitionMetadata:
        image_attrs = image_info.attrs if image_info is not None else {}
        recording_date = IMSReader._parse_recording_date(
            get_attribute(image_attrs, "RecordingDate", "AcquisitionDate", "ImageCaptureDate")
        )
        manufacturer = IMSReader._known_metadata_text(
            get_attribute(image_attrs, "ManufactorString", "Manufacturer", "MicroscopeManufacturer")
        )
        model = IMSReader._known_metadata_text(
            get_attribute(image_attrs, "ManufactorModel", "ManufacturerModel", "MicroscopeModel")
        )
        objective_name = IMSReader._known_metadata_text(
            IMSReader._find_metadata_attribute(
                dataset_info,
                "ObjectiveName",
                "ObjectiveLens",
                "ObjectiveModel",
                "LensName",
                "Lens",
                "Objective",
            )
        )
        lens_power = IMSReader._positive_metadata_number(
            get_attribute(image_attrs, "LensPower", "ObjectiveMagnification", "Magnification")
        )
        numerical_aperture = IMSReader._positive_metadata_number(
            get_attribute(image_attrs, "NumericalAperture", "ObjectiveNA", "LensNA")
        )
        sampling_clock = IMSReader._positive_metadata_number(
            IMSReader._find_metadata_attribute(dataset_info, "SamplingClock")
        )
        scan_speed = 1_000_000.0 / sampling_clock if sampling_clock is not None else None
        z_section_interval = IMSReader._parse_z_section_interval(dataset_info)
        scan_zoom = IMSReader._positive_metadata_number(
            IMSReader._find_metadata_attribute(dataset_info, "ScanZoom", "ZoomValue", "Zoom")
        )
        return AcquisitionMetadata(
            recording_date=recording_date,
            microscope_manufacturer=manufacturer,
            microscope_model=model,
            scan_speed_us_per_pixel=scan_speed,
            objective_name=objective_name,
            objective_magnification=lens_power,
            numerical_aperture=numerical_aperture,
            z_section_interval_um=z_section_interval,
            scan_zoom=scan_zoom,
        )

    @staticmethod
    def _parse_z_section_interval(dataset_info: h5py.Group | None) -> float | None:
        if dataset_info is None:
            return None
        for child in dataset_info.values():
            if not isinstance(child, h5py.Group):
                continue
            axis_code = IMSReader._known_metadata_text(get_attribute(child.attrs, "AxisCode", "AxisName"))
            if axis_code is None or axis_code.casefold() != "z":
                continue
            interval = IMSReader._positive_metadata_number(get_attribute(child.attrs, "Interval", "StepSize", "ZStep"))
            if interval is None:
                continue
            unit = IMSReader._known_metadata_text(get_attribute(child.attrs, "PixUnit", "UnitName", "Unit"))
            factor = unit_scale_to_um(unit) if unit is not None else None
            if factor is not None:
                return interval * factor
        return None

    @staticmethod
    def _find_metadata_attribute(dataset_info: h5py.Group | None, *names: str) -> Any | None:
        if dataset_info is None:
            return None
        direct = get_attribute(dataset_info.attrs, *names)
        if direct is not None:
            return direct
        for child in dataset_info.values():
            if isinstance(child, h5py.Group):
                value = get_attribute(child.attrs, *names)
                if value is not None:
                    return value
        return None

    @staticmethod
    def _known_metadata_text(value: Any | None) -> str | None:
        if value is None:
            return None
        text = str(normalize_attribute(value)).strip().strip("'\"")
        if text.casefold() in {"", "not known", "unknown", "none", "n/a", "na"}:
            return None
        return text

    @staticmethod
    def _positive_metadata_number(value: Any | None) -> float | None:
        numbers = parse_number_list(value)
        if not numbers or not np.isfinite(numbers[0]) or numbers[0] <= 0:
            return None
        return float(numbers[0])

    @staticmethod
    def _parse_recording_date(value: Any | None) -> datetime | None:
        text = IMSReader._known_metadata_text(value)
        if text is None:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            pass
        for date_format in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, date_format)
            except ValueError:
                continue
        return None

    @staticmethod
    def _read_sizes(image_info: h5py.Group | None) -> dict[str, int] | None:
        if image_info is None:
            return None
        sizes: dict[str, int] = {}
        for axis, aliases in {
            "X": ("X", "SizeX"),
            "Y": ("Y", "SizeY"),
            "Z": ("Z", "SizeZ"),
        }.items():
            parsed = parse_int(get_attribute(image_info.attrs, *aliases))
            if parsed is None:
                return None
            sizes[axis] = parsed
        return sizes

    @staticmethod
    def _read_extents(
        image_info: h5py.Group | None,
        sizes: dict[str, int],
        factor: float,
        warnings: list[str],
    ) -> tuple[dict[str, float], dict[str, float]]:
        if image_info is None:
            raise IMSReaderError("Metadata missing: /DataSetInfo/Image is required for physical scale.")
        extents: dict[str, float] = {}
        origins: dict[str, float] = {}
        for index, axis in enumerate(("X", "Y", "Z")):
            minimum_values = parse_number_list(get_attribute(image_info.attrs, f"ExtMin{index}"))
            maximum_values = parse_number_list(get_attribute(image_info.attrs, f"ExtMax{index}"))
            if not minimum_values or not maximum_values:
                raise IMSReaderError(f"Metadata missing: ExtMin{index}/ExtMax{index} is required for {axis} scale.")
            extent = (maximum_values[0] - minimum_values[0]) * factor
            if not np.isfinite(extent) or extent <= 0:
                raise IMSReaderError(f"Invalid physical extent for axis {axis}: {extent}.")
            extents[axis] = float(extent)
            origins[axis] = float(minimum_values[0] * factor)
        return extents, origins

    @staticmethod
    def _resolve_sizes_from_data(
        shape: tuple[int, ...], reported_sizes: dict[str, int]
    ) -> tuple[dict[str, int], tuple[str, str, str], str | None]:
        """Use ResolutionLevel 0 dimensions when one Image size attribute is stale."""

        scored_orders = [
            (
                sum(shape[position] == reported_sizes[axis] for position, axis in enumerate(order)),
                order,
            )
            for order in itertools.permutations(("Z", "Y", "X"))
        ]
        best_score = max(score for score, _ in scored_orders)
        if best_score < 2:
            raise IMSReaderError(
                f"Dataset shape {tuple(shape)} does not reliably match metadata sizes "
                f"X={reported_sizes['X']}, Y={reported_sizes['Y']}, Z={reported_sizes['Z']}."
            )
        candidates = [order for score, order in scored_orders if score == best_score]
        preferred = ("Z", "Y", "X")
        selected = preferred if preferred in candidates else candidates[0]
        resolved = {axis: int(shape[position]) for position, axis in enumerate(selected)}
        mismatches = [
            f"{axis}: metadata={reported_sizes[axis]}, data={resolved[axis]}"
            for axis in ("X", "Y", "Z")
            if reported_sizes[axis] != resolved[axis]
        ]
        warning = None
        if mismatches:
            warning = (
                "Image size metadata differs from ResolutionLevel 0 data "
                f"({'; '.join(mismatches)}); data dimensions are used."
            )
        return resolved, selected, warning

    @staticmethod
    def _axis_ambiguity_warning(
        shape: tuple[int, ...],
        sizes: dict[str, int],
        selected: tuple[str, str, str],
    ) -> str | None:
        candidates = [
            order
            for order in itertools.permutations(("Z", "Y", "X"))
            if tuple(sizes[axis] for axis in order) == tuple(shape)
        ]
        if len(candidates) > 1:
            return f"Axis order is ambiguous for shape {tuple(shape)}; selected storage order {', '.join(selected)}."
        return None

    @staticmethod
    def _infer_axis_order(shape: tuple[int, ...], sizes: dict[str, int]) -> tuple[tuple[str, str, str], str | None]:
        candidates = [
            order
            for order in itertools.permutations(("Z", "Y", "X"))
            if tuple(sizes[axis] for axis in order) == tuple(shape)
        ]
        if not candidates:
            raise IMSReaderError(
                f"Dataset shape {tuple(shape)} does not match metadata sizes "
                f"X={sizes['X']}, Y={sizes['Y']}, Z={sizes['Z']}."
            )
        preferred = ("Z", "Y", "X")
        selected = preferred if preferred in candidates else candidates[0]
        warning = None
        if len(candidates) > 1:
            warning = f"Axis order is ambiguous for shape {tuple(shape)}; selected storage order {', '.join(selected)}."
        return selected, warning

    @staticmethod
    def _find_data_dataset(channel_group: h5py.Group) -> h5py.Dataset:
        data = _child_casefold(channel_group, "Data")
        if not isinstance(data, h5py.Dataset):
            raise IMSReaderError(f"No Data dataset in {channel_group.name}.")
        return data

    @staticmethod
    def _validate_dtype(dtype: np.dtype[Any]) -> None:
        if not (np.issubdtype(dtype, np.integer) or np.issubdtype(dtype, np.floating)):
            raise IMSReaderError(f"Unsupported datatype: {dtype}.")

    @staticmethod
    def _channel_info_group(dataset_info: h5py.Group | None, index: int) -> h5py.Group | None:
        if dataset_info is None:
            return None
        channel_info = _child_casefold(dataset_info, f"Channel {index}")
        return channel_info if isinstance(channel_info, h5py.Group) else None

    @staticmethod
    def _parse_channel(
        index: int,
        channel_info: h5py.Group | None,
        data: h5py.Dataset,
        axis_order: tuple[str, str, str],
        warnings: list[str],
    ) -> ChannelMetadata:
        attrs = channel_info.attrs if channel_info is not None else {}
        raw_name = get_attribute(attrs, "Name")
        name = str(raw_name).strip() if raw_name not in (None, "") else f"Channel {index + 1}"

        color_values = parse_number_list(get_attribute(attrs, "Color"))
        if len(color_values) >= 3 and all(np.isfinite(value) for value in color_values[:3]):
            color_array = np.asarray(color_values[:3], dtype=np.float64)
            if np.max(color_array) > 1.0:
                color_array /= 255.0
            color = tuple(float(value) for value in np.clip(color_array, 0.0, 1.0))
        else:
            color = FALLBACK_COLORS[index % len(FALLBACK_COLORS)]
            warnings.append(f"Color missing for {name}; fallback color {color} is used.")

        range_values = parse_number_list(get_attribute(attrs, "ColorRange"))
        if len(range_values) >= 2 and np.isfinite(range_values[:2]).all() and range_values[1] > range_values[0]:
            display_min, display_max = float(range_values[0]), float(range_values[1])
            source = "ims"
        else:
            display_min = display_max = None
            source = "data_min_max"
            warnings.append(f"Display range not found for {name}; selected data min/max will be used during export.")

        gamma_values = parse_number_list(get_attribute(attrs, "GammaCorrection", "Gamma"))
        if gamma_values and np.isfinite(gamma_values[0]) and 0.1 <= gamma_values[0] <= 5.0:
            display_gamma = float(gamma_values[0])
            gamma_source = "ims"
        else:
            display_gamma = 1.0
            gamma_source = "default"
            warnings.append(f"Gamma correction not found for {name}; default gamma 1.0 will be used.")

        return ChannelMetadata(
            index=index,
            name=name,
            color=color,
            display_min=display_min,
            display_max=display_max,
            display_gamma=display_gamma,
            dataset_path=data.name,
            axis_order=axis_order,
            display_range_source=source,
            display_gamma_source=gamma_source,
        )

    def read_z_range(self, channel_index: int, z_start: int, z_end: int) -> np.ndarray:
        """Read an inclusive, 1-based Z range and return a Z/Y/X array."""

        metadata = self.metadata
        h5_file = self._require_file()
        if metadata is None:
            raise IMSReaderError("IMS metadata has not been parsed.")
        if not 0 <= channel_index < metadata.channel_count:
            raise IMSReaderError(f"Channel index {channel_index} is out of range.")
        if not 1 <= z_start <= z_end <= metadata.size_z:
            raise IMSReaderError(
                f"Z range must satisfy 1 <= start <= end <= {metadata.size_z}; received {z_start}..{z_end}."
            )

        channel = metadata.channels[channel_index]
        data = h5_file[channel.dataset_path]
        z_axis = channel.axis_order.index("Z")
        selection: list[slice] = [slice(None), slice(None), slice(None)]
        selection[z_axis] = slice(z_start - 1, z_end)
        selected = np.asarray(data[tuple(selection)])
        transpose_axes = tuple(channel.axis_order.index(axis) for axis in ("Z", "Y", "X"))
        return np.transpose(selected, axes=transpose_axes)

    def project_z_range(
        self,
        channel_index: int,
        z_start: int,
        z_end: int,
        chunk_depth: int = 8,
    ) -> tuple[np.ndarray, float, float]:
        """Calculate a Z maximum projection without loading the full stack."""

        metadata = self.metadata
        h5_file = self._require_file()
        if metadata is None:
            raise IMSReaderError("IMS metadata has not been parsed.")
        if not 0 <= channel_index < metadata.channel_count:
            raise IMSReaderError(f"Channel index {channel_index} is out of range.")
        if not 1 <= z_start <= z_end <= metadata.size_z:
            raise IMSReaderError(
                f"Z range must satisfy 1 <= start <= end <= {metadata.size_z}; received {z_start}..{z_end}."
            )
        if chunk_depth <= 0:
            raise IMSReaderError("Projection chunk depth must be greater than zero.")

        channel = metadata.channels[channel_index]
        data = h5_file[channel.dataset_path]
        z_axis = channel.axis_order.index("Z")
        transpose_axes = tuple(channel.axis_order.index(axis) for axis in ("Z", "Y", "X"))
        projection: np.ndarray | None = None
        data_min: float | None = None
        data_max: float | None = None
        for chunk_start in range(z_start - 1, z_end, chunk_depth):
            chunk_end = min(chunk_start + chunk_depth, z_end)
            selection: list[slice] = [slice(None), slice(None), slice(None)]
            selection[z_axis] = slice(chunk_start, chunk_end)
            selected = np.asarray(data[tuple(selection)])
            chunk_zyx = np.transpose(selected, axes=transpose_axes)
            chunk_projection = np.max(chunk_zyx, axis=0)
            if projection is None:
                projection = chunk_projection.copy()
            else:
                np.maximum(projection, chunk_projection, out=projection)
            chunk_minimum = float(np.min(chunk_zyx))
            chunk_maximum = float(np.max(chunk_zyx))
            data_min = chunk_minimum if data_min is None else min(data_min, chunk_minimum)
            data_max = chunk_maximum if data_max is None else max(data_max, chunk_maximum)

        if projection is None or data_min is None or data_max is None:
            raise IMSReaderError("The selected Z range did not contain image data.")
        return projection, data_min, data_max

    def inspect_hdf5_structure(self) -> str:
        """Return groups, datasets, and normalized attributes for diagnostics."""

        h5_file = self._require_file()
        lines = ["/"]

        def visitor(name: str, obj: h5py.Group | h5py.Dataset) -> None:
            kind = "Dataset" if isinstance(obj, h5py.Dataset) else "Group"
            suffix = f" shape={obj.shape} dtype={obj.dtype}" if isinstance(obj, h5py.Dataset) else ""
            lines.append(f"/{name} [{kind}]{suffix}")
            for key in obj.attrs.keys():
                lines.append(f"  @{key} = {normalize_attribute(obj.attrs[key])!r}")

        h5_file.visititems(visitor)
        return "\n".join(lines)
