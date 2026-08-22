"""Background preview and batch-export workers for the Qt interface."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from .batch import adapt_settings_for_metadata
from .dataset_loader import DatasetLoader, open_microscopy_dataset
from .exporter import (
    ExportResult,
    export_channels_and_merge,
    prepare_output_image,
    render_merge,
    render_single_channel,
    write_export_info,
    write_ppt_summary,
)
from .fiji_bridge import (
    FijiBridgeCancelled,
    FijiBridgeResult,
    export_dataset_to_ome_tiff,
    launch_fiji,
    make_bridge_output_path,
)
from .image_dataset import ImageDataset, ResolutionLevelInfo
from .ims_reader import IMSReaderError
from .models import ChannelSelection, DisplayAdjustmentSettings, ExportSettings, IMSMetadata
from .plugins.cell_counting import (
    CellCountingRequest,
    CellCountingResult,
    CellSegmenterPlugin,
    run_cell_counting,
)


@dataclass(frozen=True)
class BatchExportOutcome:
    results: tuple[ExportResult, ...]
    info_paths: tuple[Path, ...]
    summary_paths: tuple[Path, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    cancelled: bool = False


@dataclass(frozen=True)
class DatasetOpenRecord:
    requested_path: Path
    metadata: IMSMetadata
    active_backend: str
    cache_path: Path | None
    cache_status: str
    messages: tuple[str, ...]


@dataclass(frozen=True)
class DatasetOpenOutcome:
    records: tuple[DatasetOpenRecord, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class PreviewRenderResult:
    """Rendered preview plus the pyramid level used to produce it."""

    image: np.ndarray
    full_size: tuple[int, int]
    level: ResolutionLevelInfo
    available_levels: tuple[ResolutionLevelInfo, ...]


@dataclass(frozen=True)
class FijiBridgeOutcome:
    result: FijiBridgeResult | None
    cancelled: bool = False


class DatasetOpenWorker(QObject):
    """Open/convert OIB sources away from the Qt main thread."""

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, source_paths: tuple[Path, ...], loader: DatasetLoader | None = None) -> None:
        super().__init__()
        self.source_paths = source_paths
        self.loader = loader or DatasetLoader()
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        records: list[DatasetOpenRecord] = []
        errors: list[str] = []
        for position, source_path in enumerate(self.source_paths):
            if self._cancel_event.is_set():
                break

            def report(fraction: float, phase: str) -> None:
                overall = (position + min(max(fraction, 0.0), 1.0)) / max(1, len(self.source_paths))
                self.progress.emit(round(overall * 100), phase)

            try:
                with self.loader.open(
                    source_path,
                    progress=report,
                    is_cancelled=self._cancel_event.is_set,
                ) as session:
                    metadata = session.dataset.metadata
                    if metadata is None:
                        raise IMSReaderError("Normalized microscopy metadata could not be read.")
                    records.append(
                        DatasetOpenRecord(
                            requested_path=source_path.resolve(),
                            metadata=metadata,
                            active_backend=session.active_backend,
                            cache_path=session.cache_path,
                            cache_status=session.relationship.cache_status,
                            messages=session.messages,
                        )
                    )
            except Exception as exc:
                errors.append(f"{source_path.name}: {exc}")
        if not records:
            reason = "Opening microscopy files was cancelled." if self._cancel_event.is_set() else "\n".join(errors)
            self.failed.emit(reason)
            return
        self.progress.emit(100, "Microscopy files opened")
        self.finished.emit(DatasetOpenOutcome(tuple(records), tuple(errors)))


class _PreviewResolutionDataset:
    """Present one chosen pyramid level to the existing color renderer."""

    def __init__(self, dataset: ImageDataset, level: ResolutionLevelInfo) -> None:
        self.dataset = dataset
        self.level = level
        self.metadata = dataset.metadata

    def project_z_range(
        self,
        channel_index: int,
        z_start: int,
        z_end: int,
        chunk_depth: int = 8,
    ) -> tuple[np.ndarray, float, float]:
        return self.dataset.project_z_range_at_resolution(
            channel_index,
            z_start,
            z_end,
            self.level,
            chunk_depth,
        )


class PreviewWorker(QObject):
    """Read selected data and render a downsampled preview away from the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source_path: Path,
        settings: ExportSettings,
        display_adjustments: Mapping[int, DisplayAdjustmentSettings],
        preview_selection: int | tuple[int, ...],
        target_width: int = 1200,
        target_height: int = 1200,
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.settings = settings
        self.display_adjustments = dict(display_adjustments)
        self.preview_selection = preview_selection
        self.target_width = max(1, int(target_width))
        self.target_height = max(1, int(target_height))

    @Slot()
    def run(self) -> None:
        try:
            with open_microscopy_dataset(self.source_path) as session:
                reader = session.dataset
                if reader.metadata is None:
                    raise IMSReaderError("Microscopy metadata could not be read.")
                base_width = self.settings.output.width_px or reader.metadata.size_x
                base_height = self.settings.output.height_px or reader.metadata.size_y
                requested_factor = max(
                    self.target_width / base_width,
                    self.target_height / base_height,
                )
                source_limit_factor = max(
                    reader.metadata.size_x / base_width,
                    reader.metadata.size_y / base_height,
                )
                render_factor = min(requested_factor, source_limit_factor)
                render_width = max(1, round(base_width * render_factor))
                render_height = max(1, round(base_height * render_factor))
                level = reader.choose_resolution_level(render_width, render_height)
                preview_reader = _PreviewResolutionDataset(reader, level)
                scaled_thickness = (
                    max(1, round(self.settings.scale_bar.thickness_px * render_factor))
                    if self.settings.scale_bar.thickness_px is not None
                    else None
                )
                scaled_font_size = (
                    max(1, round(self.settings.scale_bar.font_size_px * render_factor))
                    if self.settings.scale_bar.font_size_px is not None
                    else None
                )
                preview_settings = replace(
                    self.settings,
                    output=replace(
                        self.settings.output,
                        width_px=render_width,
                        height_px=render_height,
                    ),
                    scale_bar=replace(
                        self.settings.scale_bar,
                        thickness_px=scaled_thickness,
                        font_size_px=scaled_font_size,
                    ),
                )
                if isinstance(self.preview_selection, tuple):
                    preview_settings = replace(preview_settings, merge_channel_indices=self.preview_selection)
                    image, _ = render_merge(preview_reader, preview_settings, self.display_adjustments)
                else:
                    image, _ = render_single_channel(
                        preview_reader,
                        self.settings,
                        self.preview_selection,
                        self.display_adjustments.get(self.preview_selection),
                    )
                output_image, _ = prepare_output_image(image, preview_reader, preview_settings)
                self.finished.emit(
                    PreviewRenderResult(
                        np.ascontiguousarray(output_image),
                        (base_width, base_height),
                        level,
                        reader.resolution_levels(),
                    )
                )
        except Exception as exc:  # Convert worker exceptions into a GUI error message.
            self.failed.emit(str(exc))


class CellCountWorker(QObject):
    """Project selected channels and run one cell-counting plugin off the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source_path: Path,
        request: CellCountingRequest,
        plugin: CellSegmenterPlugin,
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.request = request
        self.plugin = plugin

    @Slot()
    def run(self) -> None:
        try:
            with open_microscopy_dataset(self.source_path) as session:
                dataset = session.dataset
                metadata = dataset.metadata
                if metadata is None:
                    raise IMSReaderError("Microscopy metadata could not be read.")
                channel_indices = tuple(
                    sorted(
                        set(self.request.detection_channel_indices)
                        | set(self.request.measurement_channel_indices)
                    )
                )
                raw_channels = {
                    index: dataset.project_z_range(
                        index,
                        self.request.z_start,
                        min(self.request.z_end, metadata.size_z),
                    )[0]
                    for index in channel_indices
                }
                channel_names = {channel.index: channel.name for channel in metadata.channels}
                channel_colors = {channel.index: channel.color for channel in metadata.channels}
                result: CellCountingResult = run_cell_counting(
                    metadata.source_path,
                    raw_channels,
                    channel_names,
                    channel_colors,
                    self.request,
                    self.plugin,
                )
                self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class FijiBridgeWorker(QObject):
    """Stream selected raw data to OME-TIFF and launch external Fiji."""

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(
        self,
        source_path: Path,
        fiji_directory: Path,
        channel_indices: tuple[int, ...],
        z_start: int,
        z_end: int,
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.fiji_directory = fiji_directory
        self.channel_indices = channel_indices
        self.z_start = z_start
        self.z_end = z_end
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            output_path = make_bridge_output_path(self.source_path)
            with open_microscopy_dataset(self.source_path) as session:
                export_dataset_to_ome_tiff(
                    session.dataset,
                    output_path,
                    self.channel_indices,
                    self.z_start,
                    self.z_end,
                    progress=lambda fraction, phase: self.progress.emit(round(fraction * 100), phase),
                    is_cancelled=self._cancel_event.is_set,
                )
            result = launch_fiji(self.fiji_directory, output_path)
            self.finished.emit(FijiBridgeOutcome(result))
        except FijiBridgeCancelled:
            self.finished.emit(FijiBridgeOutcome(None, cancelled=True))
        except Exception as exc:
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
        summary_paths: list[Path] = []
        errors: list[str] = []
        warnings: list[str] = []
        total = len(self.source_paths)
        for position, source_path in enumerate(self.source_paths, start=1):
            if self._cancel_event.is_set():
                break
            self.progress.emit(position - 1, total, source_path.name)
            try:
                with open_microscopy_dataset(source_path) as session:
                    reader = session.dataset
                    if reader.metadata is None:
                        raise IMSReaderError("Microscopy metadata could not be read.")
                    matched = adapt_settings_for_metadata(self.settings, self.channel_selections, reader.metadata)
                    if not matched.settings.required_output_channel_indices:
                        raise IMSReaderError("None of the requested output channels exist in this file.")
                    warnings.extend(f"{source_path.name}: {message}" for message in matched.warnings)
                    results = export_channels_and_merge(
                        reader,
                        matched.settings,
                        self.output_directory,
                        display_adjustments=matched.display_adjustments,
                    )
                    info_path = write_export_info(reader, matched.settings, results, self.output_directory)
                    summary_path = write_ppt_summary(reader, matched.settings, self.output_directory)
                    all_results.extend(results)
                    info_paths.append(info_path)
                    summary_paths.append(summary_path)
            except Exception as exc:  # Continue with other files in the batch.
                errors.append(f"{source_path.name}: {exc}")
        cancelled = self._cancel_event.is_set()
        self.progress.emit(total if not cancelled else len(info_paths), total, "")
        if not all_results and not cancelled:
            self.failed.emit("No batch files could be exported.\n" + "\n".join(errors))
            return
        self.finished.emit(
            BatchExportOutcome(
                results=tuple(all_results),
                info_paths=tuple(info_paths),
                summary_paths=tuple(summary_paths),
                errors=tuple(errors),
                warnings=tuple(warnings),
                cancelled=cancelled,
            )
        )
