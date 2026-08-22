"""Export selected microscopy data to OME-TIFF and open it in Fiji."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import tifffile

from .image_dataset import ImageDataset


class FijiBridgeError(RuntimeError):
    """Raised when Fiji cannot be located, prepared, or launched."""


class FijiBridgeCancelled(FijiBridgeError):
    """Raised when an OME-TIFF bridge export is cancelled."""


@dataclass(frozen=True)
class FijiBridgeResult:
    """Files and executable used for one successful bridge launch."""

    ome_tiff_path: Path
    fiji_executable: Path


def resolve_fiji_executable(location: str | Path) -> Path:
    """Resolve a Fiji application directory or launcher to an executable."""

    path = Path(location).expanduser().resolve()
    if path.is_file():
        if path.suffix.casefold() not in {".exe", ".bat"}:
            raise FijiBridgeError(f"The selected file is not a Fiji launcher: {path}")
        return path
    if not path.is_dir():
        raise FijiBridgeError(f"Fiji folder was not found: {path}")
    for name in (
        "fiji-windows-x64.exe",
        "fiji-windows-arm64.exe",
        "ImageJ-win64.exe",
        "fiji.bat",
    ):
        candidate = path / name
        if candidate.is_file():
            return candidate
    raise FijiBridgeError(
        "No Fiji Windows launcher was found in the selected folder. "
        "Select the Fiji.app folder containing fiji-windows-x64.exe."
    )


def discover_fiji_installation() -> Path | None:
    """Find common portable Fiji locations without scanning whole drives."""

    configured = os.environ.get("IEA_FIJI_DIR", "").strip()
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    home = Path.home()
    candidates.extend(
        (
            home / "Fiji.app",
            home / "Fiji" / "Fiji.app",
            home / "Downloads" / "Fiji.app",
        )
    )
    if os.name == "nt":
        candidates.extend(Path(f"{letter}:\\Fiji\\Fiji.app") for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ")
    for candidate in candidates:
        try:
            resolve_fiji_executable(candidate)
        except FijiBridgeError:
            continue
        return candidate.resolve()
    return None


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", path.stem).strip("._")
    return stem or "microscopy_image"


def make_bridge_output_path(source_path: Path) -> Path:
    """Create a unique, ASCII-safe location that remains available to Fiji."""

    bridge_directory = Path(tempfile.gettempdir()) / "image_easy-to-adjust" / "fiji-bridge"
    bridge_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return bridge_directory / f"{_safe_stem(source_path)}_{timestamp}.ome.tif"


def export_dataset_to_ome_tiff(
    dataset: ImageDataset,
    output_path: str | Path,
    channel_indices: Sequence[int],
    z_start: int,
    z_end: int,
    *,
    progress: Callable[[float, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Path:
    """Stream raw selected C/Z planes to an ImageJ-friendly OME-TIFF."""

    metadata = dataset.metadata
    if metadata is None:
        raise FijiBridgeError("Microscopy metadata is unavailable.")
    channels = tuple(dict.fromkeys(int(index) for index in channel_indices))
    if not channels:
        raise FijiBridgeError("Select at least one channel to send to Fiji.")
    if any(index < 0 or index >= metadata.channel_count for index in channels):
        raise FijiBridgeError("A selected channel does not exist in the active image.")
    if not 1 <= z_start <= z_end <= metadata.size_z:
        raise FijiBridgeError(f"Z range must be between 1 and {metadata.size_z}.")

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.part")
    plane_count = len(channels) * (z_end - z_start + 1)
    first_plane = dataset.get_plane(0, channels[0], z_start - 1)
    dtype = first_plane.dtype
    expected_bytes = plane_count * metadata.size_y * metadata.size_x * dtype.itemsize
    report = progress or (lambda _fraction, _phase: None)
    cancelled = is_cancelled or (lambda: False)

    def planes() -> Iterator[np.ndarray]:
        completed = 0
        for channel_index in channels:
            for z_index in range(z_start - 1, z_end):
                if cancelled():
                    raise FijiBridgeCancelled("Sending the image to Fiji was cancelled.")
                plane = dataset.get_plane(0, channel_index, z_index)
                if plane.shape != (metadata.size_y, metadata.size_x):
                    raise FijiBridgeError(f"Unexpected plane shape {plane.shape}.")
                if plane.dtype != dtype:
                    plane = plane.astype(dtype, copy=False)
                completed += 1
                report(completed / plane_count, f"Preparing Fiji data: {completed} / {plane_count} planes")
                yield np.ascontiguousarray(plane)

    ome_metadata: dict[str, object] = {
        "axes": "CZYX",
        "Channel": {"Name": [metadata.channels[index].name for index in channels]},
    }
    if metadata.voxel_size_x_um is not None:
        ome_metadata.update(PhysicalSizeX=metadata.voxel_size_x_um, PhysicalSizeXUnit="µm")
    if metadata.voxel_size_y_um is not None:
        ome_metadata.update(PhysicalSizeY=metadata.voxel_size_y_um, PhysicalSizeYUnit="µm")
    if metadata.voxel_size_z_um is not None:
        ome_metadata.update(PhysicalSizeZ=metadata.voxel_size_z_um, PhysicalSizeZUnit="µm")

    try:
        with tifffile.TiffWriter(partial, bigtiff=expected_bytes >= 4_000_000_000, ome=True) as writer:
            writer.write(
                planes(),
                shape=(len(channels), z_end - z_start + 1, metadata.size_y, metadata.size_x),
                dtype=dtype,
                photometric="minisblack",
                metadata=ome_metadata,
                compression="zlib",
            )
        partial.replace(destination)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise
    report(1.0, "Opening the selected data in Fiji...")
    return destination


def launch_fiji(location: str | Path, image_path: str | Path) -> FijiBridgeResult:
    """Open an exported image in an independent Fiji process."""

    executable = resolve_fiji_executable(location)
    image = Path(image_path).resolve()
    if not image.is_file():
        raise FijiBridgeError(f"Bridge image was not created: {image}")
    try:
        subprocess.Popen(
            [str(executable), str(image)],
            cwd=str(executable.parent),
            close_fds=True,
        )
    except OSError as exc:
        raise FijiBridgeError(f"Unable to start Fiji: {exc}") from exc
    return FijiBridgeResult(image, executable)
