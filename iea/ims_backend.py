"""ImageDataset backend adapter for existing Imaris IMS files."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .ims_reader import IMSReader
from .models import IMSMetadata


class IMSPixelBackend:
    """Expose the existing lazy HDF5 reader through the common block API."""

    backend_name = "IMSBackend"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.reader = IMSReader(self.path)
        self.metadata: IMSMetadata | None = None

    def open(self) -> IMSMetadata:
        self.metadata = self.reader.open()
        return self.metadata

    def close(self) -> None:
        self.reader.close()
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
        if time_index != 0:
            raise ValueError("IEA currently exposes TimePoint 0 from IMS files.")
        stack = self.reader.read_z_range(channel_index, z_start + 1, z_end)
        return np.ascontiguousarray(stack[:, y_start:y_end, x_start:x_end])
