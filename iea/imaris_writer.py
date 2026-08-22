"""Streaming adapter around the official PyImarisWriter API."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from . import __version__
from .image_dataset import DisplaySettings, ImageDataset

ProgressCallback = Callable[[float, str], None]
CancellationCheck = Callable[[], bool]


class IMSWriterError(RuntimeError):
    """Raised when an IMS cache cannot be created safely."""


@dataclass(frozen=True)
class IMSWriteResult:
    output_path: Path
    blocks_written: int
    display_min_written: bool
    display_max_written: bool
    gamma_written: bool
    limitations: tuple[str, ...] = ()


class IMSWriterBackend:
    """Write raw blocks and standard display metadata using PyImarisWriter."""

    def __init__(self, block_xy: int = 512, thread_count: int | None = None) -> None:
        self.block_xy = max(64, int(block_xy))
        # PyImarisWriter's native worker pool can fail to terminate when a JPype
        # Bio-Formats JVM is active in the same Windows process. One writer
        # thread is reliable and still uses block-based, bounded-memory I/O.
        self.thread_count = max(1, int(thread_count)) if thread_count is not None else 1

    @staticmethod
    def is_available() -> bool:
        try:
            from PyImarisWriter import PyImarisWriter  # noqa: F401
        except (ImportError, OSError):
            return False
        return True

    def write(
        self,
        dataset: ImageDataset,
        output_path: str | Path,
        display_settings: tuple[DisplaySettings, ...] | None = None,
        progress: ProgressCallback | None = None,
        is_cancelled: CancellationCheck | None = None,
    ) -> IMSWriteResult:
        metadata = dataset.metadata
        if metadata is None:
            raise IMSWriterError("Dataset metadata is unavailable.")
        try:
            from PyImarisWriter import PyImarisWriter as PW
        except (ImportError, OSError) as exc:
            raise IMSWriterError(
                'IMS conversion requires PyImarisWriter. Install with: pip install -e ".[oib]"'
            ) from exc

        dtype = np.dtype(metadata.dtype)
        writer_type = {
            np.dtype(np.uint8): "uint8",
            np.dtype(np.uint16): "uint16",
            np.dtype(np.float32): "float32",
        }.get(dtype)
        if writer_type is None:
            raise IMSWriterError(
                f"PyImarisWriter supports uint8, uint16, and float32; OIB pixel type is {dtype}. "
                "IEA will not rescale or cast the original voxel intensities automatically."
            )
        settings = display_settings or dataset.display_settings
        if len(settings) != metadata.channel_count:
            raise IMSWriterError("One display setting is required for every channel.")
        if metadata.voxel_size_x_um is None or metadata.voxel_size_y_um is None:
            raise IMSWriterError(
                "PhysicalSizeX and PhysicalSizeY are required to create a scientifically scaled IMS cache."
            )
        if metadata.size_z > 1 and metadata.voxel_size_z_um is None:
            raise IMSWriterError("PhysicalSizeZ is required to create a multi-layer IMS cache.")

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        block_x = min(self.block_xy, metadata.size_x)
        block_y = min(self.block_xy, metadata.size_y)
        image_size = PW.ImageSize(
            x=metadata.size_x,
            y=metadata.size_y,
            z=metadata.size_z,
            c=metadata.channel_count,
            t=metadata.time_point_count,
        )
        sample_size = PW.ImageSize(x=1, y=1, z=1, c=1, t=1)
        block_size = PW.ImageSize(x=block_x, y=block_y, z=1, c=1, t=1)
        dimensions = PW.DimensionSequence("x", "y", "z", "c", "t")
        options = PW.Options()
        options.mNumberOfThreads = self.thread_count
        options.mCompressionAlgorithmType = PW.eCompressionAlgorithmGzipLevel2
        options.mEnableLogProgress = False

        progress_callback = progress or (lambda _fraction, _phase: None)

        class WriterProgress(PW.CallbackClass):
            def RecordProgress(self, fraction: float, _total_bytes_written: int) -> None:
                progress_callback(0.55 + min(max(float(fraction), 0.0), 1.0) * 0.4, "Creating IMS...")

        converter = None
        blocks_written = 0
        try:
            converter = PW.ImageConverter(
                writer_type,
                image_size,
                sample_size,
                dimensions,
                block_size,
                str(target),
                options,
                "image_easy-to-adjust",
                __version__,
                WriterProgress(),
            )
            x_blocks = math.ceil(metadata.size_x / block_x)
            y_blocks = math.ceil(metadata.size_y / block_y)
            total_blocks = (
                metadata.time_point_count
                * metadata.channel_count
                * metadata.size_z
                * y_blocks
                * x_blocks
            )
            block_index = PW.ImageSize()
            for time_index in range(metadata.time_point_count):
                block_index.t = time_index
                for channel_index in range(metadata.channel_count):
                    block_index.c = channel_index
                    for z_index in range(metadata.size_z):
                        block_index.z = z_index
                        for y_block in range(y_blocks):
                            block_index.y = y_block
                            y_start = y_block * block_y
                            y_end = min(metadata.size_y, y_start + block_y)
                            for x_block in range(x_blocks):
                                if is_cancelled is not None and is_cancelled():
                                    raise IMSWriterError("IMS conversion was cancelled.")
                                block_index.x = x_block
                                if not converter.NeedCopyBlock(block_index):
                                    continue
                                x_start = x_block * block_x
                                x_end = min(metadata.size_x, x_start + block_x)
                                raw = dataset.get_block(
                                    time_index,
                                    channel_index,
                                    z_index,
                                    z_index + 1,
                                    y_start,
                                    y_end,
                                    x_start,
                                    x_end,
                                )
                                if raw.dtype != dtype:
                                    raise IMSWriterError(
                                        f"Pixel backend changed dtype from {dtype} to {raw.dtype}; conversion stopped."
                                    )
                                padded = np.zeros((1, block_y, block_x), dtype=dtype)
                                padded[:, : y_end - y_start, : x_end - x_start] = raw
                                converter.CopyBlock(np.ascontiguousarray(padded), block_index)
                                blocks_written += 1
                                progress_callback(
                                    0.15 + 0.4 * blocks_written / max(1, total_blocks),
                                    "Creating IMS...",
                                )

            parameters = self._parameters(PW, metadata)
            color_infos = self._color_infos(PW, settings)
            extents = self._image_extents(PW, metadata)
            time_infos, time_limitation = self._time_infos(metadata)
            converter.Finish(
                extents,
                parameters,
                time_infos,
                color_infos,
                False,
            )
            progress_callback(0.98, "Finalizing IMS...")
            limitations = []
            if time_limitation:
                limitations.append(time_limitation)
            if any(
                origin is None
                for origin in (metadata.origin_x_um, metadata.origin_y_um, metadata.origin_z_um)
            ):
                limitations.append(
                    "OIB spatial origin metadata was unavailable; IMS extent origins use the 0 um storage sentinel."
                )
            if metadata.size_z == 1 and metadata.voxel_size_z_um is None:
                limitations.append(
                    "PhysicalSizeZ was unavailable for this single-layer image; IMS uses a 1 um Z extent sentinel."
                )
            return IMSWriteResult(
                target,
                blocks_written,
                display_min_written=True,
                display_max_written=True,
                gamma_written=True,
                limitations=tuple(limitations),
            )
        except IMSWriterError:
            raise
        except Exception as exc:
            raise IMSWriterError(f"PyImarisWriter failed: {exc}") from exc
        finally:
            if converter is not None:
                try:
                    converter.Destroy()
                except Exception:
                    pass

    @staticmethod
    def _parameters(PW: object, metadata) -> object:
        parameters = PW.Parameters()
        parameters.set_value("Image", "Unit", "um")
        acquisition = metadata.acquisition
        optional_image_values = {
            "RecordingDate": (
                acquisition.recording_date.isoformat(sep=" ")
                if acquisition.recording_date is not None
                else None
            ),
            "ManufactorString": acquisition.microscope_manufacturer,
            "ManufactorModel": acquisition.microscope_model,
            "ObjectiveName": acquisition.objective_name,
            "LensPower": acquisition.objective_magnification,
            "NumericalAperture": acquisition.numerical_aperture,
        }
        for name, value in optional_image_values.items():
            if value is not None:
                parameters.set_value("Image", name, value)
        for channel in metadata.channels:
            parameters.set_channel_name(channel.index, channel.name)
            if channel.excitation_wavelength_nm is not None:
                parameters.set_value(
                    f"Channel {channel.index}",
                    "ExcitationWavelength",
                    channel.excitation_wavelength_nm,
                )
            if channel.emission_wavelength_nm is not None:
                parameters.set_value(
                    f"Channel {channel.index}",
                    "EmissionWavelength",
                    channel.emission_wavelength_nm,
                )
        return parameters

    @staticmethod
    def _color_infos(PW: object, settings: tuple[DisplaySettings, ...]) -> list[object]:
        color_infos = []
        for setting in settings:
            color = setting.color or (1.0, 1.0, 1.0)
            info = PW.ColorInfo()
            info.set_base_color(PW.Color(color[0], color[1], color[2], 1.0))
            info.mOpacity = float(setting.opacity)
            info.mRangeMin = float(setting.minimum)
            info.mRangeMax = float(setting.maximum)
            info.mGammaCorrection = float(setting.gamma)
            color_infos.append(info)
        return color_infos

    @staticmethod
    def _image_extents(PW: object, metadata) -> object:
        origin_x = metadata.origin_x_um or 0.0
        origin_y = metadata.origin_y_um or 0.0
        origin_z = metadata.origin_z_um or 0.0
        extent_x = metadata.voxel_size_x_um * metadata.size_x
        extent_y = metadata.voxel_size_y_um * metadata.size_y
        # For a single plane, Z thickness is not analytically meaningful. A 1 µm
        # coordinate span is an explicit storage sentinel, not inferred metadata.
        extent_z = (
            metadata.voxel_size_z_um * metadata.size_z
            if metadata.voxel_size_z_um is not None
            else 1.0
        )
        return PW.ImageExtents(
            origin_x,
            origin_y,
            origin_z,
            origin_x + extent_x,
            origin_y + extent_y,
            origin_z + extent_z,
        )

    @staticmethod
    def _time_infos(metadata) -> tuple[list[datetime], str | None]:
        recording_date = metadata.acquisition.recording_date
        if recording_date is None:
            return (
                [datetime(1970, 1, 1) for _ in range(metadata.time_point_count)],
                "OIB acquisition timestamps were unavailable; IMS time entries use the 1970-01-01 sentinel.",
            )
        return [recording_date for _ in range(metadata.time_point_count)], None
