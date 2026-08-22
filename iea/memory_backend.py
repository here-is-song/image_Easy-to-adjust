"""Small in-memory backend for tests and future generated analysis layers."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .models import IMSMetadata


class MemoryPixelBackend:
    """Expose an existing T/C/Z/Y/X array through the common block API."""

    backend_name = "MemoryBackend"

    def __init__(self, data_tczyx: np.ndarray, metadata: IMSMetadata, path: str | Path = "memory.ims") -> None:
        self.path = Path(path)
        self.data = np.asarray(data_tczyx)
        self._source_metadata = metadata
        self.metadata: IMSMetadata | None = None

    def open(self) -> IMSMetadata:
        expected = (
            self._source_metadata.time_point_count,
            self._source_metadata.channel_count,
            self._source_metadata.size_z,
            self._source_metadata.size_y,
            self._source_metadata.size_x,
        )
        if self.data.shape != expected:
            raise ValueError(f"Memory data shape {self.data.shape} does not match metadata {expected}.")
        if self.data.dtype != np.dtype(self._source_metadata.dtype):
            raise ValueError(
                f"Memory data dtype {self.data.dtype} does not match metadata {self._source_metadata.dtype}."
            )
        self.metadata = self._source_metadata
        return self.metadata

    def close(self) -> None:
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
        return np.ascontiguousarray(
            self.data[
                time_index,
                channel_index,
                z_start:z_end,
                y_start:y_end,
                x_start:x_end,
            ]
        )
