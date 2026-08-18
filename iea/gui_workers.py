"""Background preview and batch-export workers for the Qt interface."""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from .batch import adapt_settings_for_metadata
from .exporter import (
    ExportResult,
    export_channels_and_merge,
    prepare_output_image,
    render_merge,
    render_single_channel,
    write_export_info,
)
from .ims_reader import IMSReader, IMSReaderError
from .models import ChannelSelection, ExportSettings

PREVIEW_MAX_EDGE = 1200


@dataclass(frozen=True)
class BatchExportOutcome:
    results: tuple[ExportResult, ...]
    info_paths: tuple[Path, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    cancelled: bool = False


def _downsample_for_preview(image: np.ndarray) -> np.ndarray:
    """Use integer decimation so previews stay responsive and memory bounded."""

    height, width = image.shape[:2]
    factor = max(1, math.ceil(max(height, width) / PREVIEW_MAX_EDGE))
    return np.ascontiguousarray(image[::factor, ::factor])


class PreviewWorker(QObject):
    """Read selected data and render a downsampled preview away from the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source_path: Path,
        settings: ExportSettings,
        display_ranges: Mapping[int, tuple[float, float]],
        preview_channel: int | None,
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.settings = settings
        self.display_ranges = dict(display_ranges)
        self.preview_channel = preview_channel

    @Slot()
    def run(self) -> None:
        try:
            with IMSReader(self.source_path) as reader:
                if reader.metadata is None:
                    raise IMSReaderError("IMS metadata could not be read.")
                if self.preview_channel is None:
                    image, _ = render_merge(reader, self.settings, self.display_ranges)
                else:
                    image, _ = render_single_channel(
                        reader,
                        self.settings,
                        self.preview_channel,
                        self.display_ranges.get(self.preview_channel),
                    )
                output_image, _ = prepare_output_image(image, reader, self.settings)
                self.finished.emit(_downsample_for_preview(output_image))
        except Exception as exc:  # Convert worker exceptions into a GUI error message.
            self.failed.emit(str(exc))


class ExportWorker(QObject):
    """Perform image and JSON exports away from the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int, str)

    def __init__(
        self,
        source_paths: tuple[Path, ...],
        settings: ExportSettings,
        channel_selections: tuple[ChannelSelection, ...],
        output_directory: Path | None,
    ) -> None:
        super().__init__()
        self.source_paths = source_paths
        self.settings = settings
        self.channel_selections = channel_selections
        self.output_directory = output_directory
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        all_results: list[ExportResult] = []
        info_paths: list[Path] = []
        errors: list[str] = []
        warnings: list[str] = []
        total = len(self.source_paths)
        for position, source_path in enumerate(self.source_paths, start=1):
            if self._cancel_event.is_set():
                break
            self.progress.emit(position - 1, total, source_path.name)
            try:
                with IMSReader(source_path) as reader:
                    if reader.metadata is None:
                        raise IMSReaderError("IMS metadata could not be read.")
                    matched = adapt_settings_for_metadata(self.settings, self.channel_selections, reader.metadata)
                    if not matched.settings.channel_indices:
                        raise IMSReaderError("None of the selected channel names exist in this file.")
                    warnings.extend(f"{source_path.name}: {message}" for message in matched.warnings)
                    results = export_channels_and_merge(
                        reader,
                        matched.settings,
                        self.output_directory,
                        display_ranges=matched.display_ranges,
                    )
                    info_path = write_export_info(reader, matched.settings, results, self.output_directory)
                    all_results.extend(results)
                    info_paths.append(info_path)
            except Exception as exc:  # Continue with other files in the batch.
                errors.append(f"{source_path.name}: {exc}")
        cancelled = self._cancel_event.is_set()
        self.progress.emit(total if not cancelled else len(info_paths), total, "")
        if not all_results and not cancelled:
            self.failed.emit("No batch files could be exported.\n" + "\n".join(errors))
            return
        self.finished.emit(
            BatchExportOutcome(
                tuple(all_results),
                tuple(info_paths),
                tuple(errors),
                tuple(warnings),
                cancelled,
            )
        )
