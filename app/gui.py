"""PySide6 desktop interface for the IMS figure exporter."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np
from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .exporter import (
    ExportResult,
    export_merge,
    export_single_channels,
    render_merge,
    render_single_channel,
    write_export_info,
)
from .ims_reader import IMSReader, IMSReaderError
from .models import ExportSettings, IMSMetadata
from .scalebar import draw_scale_bar


PREVIEW_MAX_EDGE = 1200


@dataclass
class ChannelControls:
    """Widgets associated with one channel; parsing remains outside the GUI layer."""

    include: QCheckBox
    minimum: QDoubleSpinBox
    maximum: QDoubleSpinBox
    use_data_minmax: QCheckBox | None = None


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
                preview = _downsample_for_preview(image)
                if self.settings.add_scale_bar:
                    factor = image.shape[1] / preview.shape[1]
                    preview_thickness = (
                        None
                        if self.settings.scale_bar_thickness_px is None
                        else max(1, round(self.settings.scale_bar_thickness_px / factor))
                    )
                    preview_font_size = (
                        None
                        if self.settings.scale_bar_font_size_px is None
                        else max(1, round(self.settings.scale_bar_font_size_px / factor))
                    )
                    preview, _ = draw_scale_bar(
                        preview,
                        reader.metadata.voxel_size_x_um * factor,
                        self.settings.scale_bar_um,
                        thickness_px=preview_thickness,
                        font_size_px=preview_font_size,
                    )
                self.finished.emit(preview)
        except Exception as exc:  # Convert worker exceptions into a GUI error message.
            self.failed.emit(str(exc))


class ExportWorker(QObject):
    """Perform image and JSON exports away from the GUI thread."""

    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        source_path: Path,
        settings: ExportSettings,
        display_ranges: Mapping[int, tuple[float, float]],
    ) -> None:
        super().__init__()
        self.source_path = source_path
        self.settings = settings
        self.display_ranges = dict(display_ranges)

    @Slot()
    def run(self) -> None:
        try:
            with IMSReader(self.source_path) as reader:
                results: list[ExportResult] = export_single_channels(
                    reader, self.settings, display_ranges=self.display_ranges
                )
                results.append(export_merge(reader, self.settings, display_ranges=self.display_ranges))
                info_path = write_export_info(reader, self.settings, results)
                self.finished.emit((results, info_path))
        except Exception as exc:  # See PreviewWorker.run.
            self.failed.emit(str(exc))


def _downsample_for_preview(image: np.ndarray) -> np.ndarray:
    """Use integer decimation so previews stay responsive and memory bounded."""

    height, width = image.shape[:2]
    factor = max(1, math.ceil(max(height, width) / PREVIEW_MAX_EDGE))
    return np.ascontiguousarray(image[::factor, ::factor])


class IMSFigureExporterWindow(QMainWindow):
    """Main window for opening IMS data, inspecting settings, previewing, and export."""

    def __init__(self) -> None:
        super().__init__()
        self.metadata: IMSMetadata | None = None
        self.channel_controls: dict[int, ChannelControls] = {}
        self.last_output_directory: Path | None = None
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self.preview_pixmap: QPixmap | None = None
        self.preview_zoom = 1.0
        self._preview_refresh_pending = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._run_scheduled_preview)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("IMS Publication Figure Exporter")
        self.resize(1200, 780)
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        file_row = QHBoxLayout()
        self.open_button = QPushButton("Open IMS…")
        self.open_button.clicked.connect(self.open_ims)
        self.file_label = QLabel("No IMS file selected")
        self.file_label.setWordWrap(True)
        file_row.addWidget(self.open_button)
        file_row.addWidget(self.file_label, 1)
        root.addLayout(file_row)
        self.metadata_label = QLabel("Open an IMS file to view metadata.")
        root.addWidget(self.metadata_label)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("color: #9a6700;")
        root.addWidget(self.warning_label)

        content = QHBoxLayout()
        root.addLayout(content, 1)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_panel = QWidget()
        self.left_layout = QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(4, 4, 4, 4)
        self.channels_group = QGroupBox("Channels")
        self.channels_layout = QVBoxLayout(self.channels_group)
        self.left_layout.addWidget(self.channels_group)
        self._build_settings_groups()
        self.left_layout.addStretch(1)
        left_scroll.setWidget(left_panel)
        left_scroll.setMaximumWidth(390)
        content.addWidget(left_scroll, 0)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("Preview:"))
        self.preview_combo = QComboBox()
        self.preview_combo.currentIndexChanged.connect(self._schedule_preview_refresh)
        preview_header.addWidget(self.preview_combo)
        self.update_button = QPushButton("Update Preview")
        self.update_button.clicked.connect(self.update_preview)
        preview_header.addWidget(self.update_button)
        preview_header.addWidget(QLabel("Refresh limit:"))
        self.preview_refresh_limit = QComboBox()
        self.preview_refresh_limit.addItem("2 per second", 500)
        self.preview_refresh_limit.addItem("1 per second", 1000)
        self.preview_refresh_limit.addItem("Every 2 seconds", 2000)
        self.preview_refresh_limit.addItem("Every 5 seconds", 5000)
        self.preview_refresh_limit.setCurrentIndex(1)
        self.preview_refresh_limit.setToolTip(
            "Minimum delay after a parameter change before the preview is recalculated"
        )
        self.preview_refresh_limit.currentIndexChanged.connect(self._refresh_limit_changed)
        preview_header.addWidget(self.preview_refresh_limit)
        self.zoom_out_button = QPushButton("−")
        self.zoom_out_button.setToolTip("Zoom out preview")
        self.zoom_out_button.clicked.connect(self.zoom_out)
        preview_header.addWidget(self.zoom_out_button)
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("Zoom in preview")
        self.zoom_in_button.clicked.connect(self.zoom_in)
        preview_header.addWidget(self.zoom_in_button)
        self.actual_size_button = QPushButton("100%")
        self.actual_size_button.clicked.connect(self.actual_size_preview)
        preview_header.addWidget(self.actual_size_button)
        self.fit_button = QPushButton("Fit")
        self.fit_button.clicked.connect(self.fit_preview)
        preview_header.addWidget(self.fit_button)
        self.zoom_label = QLabel("100%")
        preview_header.addWidget(self.zoom_label)
        preview_header.addStretch(1)
        preview_layout.addLayout(preview_header)
        self.preview_label = QLabel("Preview will appear here.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(1, 1)
        self.preview_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_scroll.setWidget(self.preview_label)
        preview_layout.addWidget(self.preview_scroll, 1)
        content.addWidget(preview_panel, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("Ready")
        bottom.addWidget(self.status_label, 1)
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self.open_output_folder)
        bottom.addWidget(self.open_folder_button)
        self.export_button = QPushButton("Export Images")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_tiffs)
        bottom.addWidget(self.export_button)
        root.addLayout(bottom)

    def _build_settings_groups(self) -> None:
        z_group = QGroupBox("Z Range")
        z_form = QFormLayout(z_group)
        self.z_start = QSpinBox()
        self.z_end = QSpinBox()
        self.z_start.valueChanged.connect(self._update_z_info)
        self.z_end.valueChanged.connect(self._update_z_info)
        self.z_start.valueChanged.connect(self._schedule_preview_refresh)
        self.z_end.valueChanged.connect(self._schedule_preview_refresh)
        self.z_info = QLabel("Open a file first.")
        self.z_info.setWordWrap(True)
        z_form.addRow("Start (slice):", self.z_start)
        z_form.addRow("End (slice):", self.z_end)
        z_form.addRow(self.z_info)
        self.left_layout.addWidget(z_group)

        scale_group = QGroupBox("Scale Bar")
        scale_form = QFormLayout(scale_group)
        self.include_scale_bar = QCheckBox("Include scale bar")
        self.include_scale_bar.setChecked(True)
        self.include_scale_bar.toggled.connect(self._toggle_scale_controls)
        self.include_scale_bar.toggled.connect(self._schedule_preview_refresh)
        self.auto_scale = QCheckBox("Auto scale bar")
        self.auto_scale.setChecked(True)
        self.auto_scale.toggled.connect(self._toggle_scale_length)
        self.auto_scale.toggled.connect(self._schedule_preview_refresh)
        self.scale_length = QDoubleSpinBox()
        self.scale_length.setSuffix(" um")
        self.scale_length.setRange(0.001, 1_000_000)
        self.scale_length.setValue(50)
        self.scale_length.setEnabled(False)
        self.scale_length.valueChanged.connect(self._schedule_preview_refresh)
        self.scale_thickness = QSpinBox()
        self.scale_thickness.setRange(0, 1000)
        self.scale_thickness.setSpecialValueText("Auto")
        self.scale_thickness.setSuffix(" px")
        self.scale_thickness.valueChanged.connect(self._schedule_preview_refresh)
        self.scale_font_size = QSpinBox()
        self.scale_font_size.setRange(0, 1000)
        self.scale_font_size.setSpecialValueText("Auto")
        self.scale_font_size.setSuffix(" px")
        self.scale_font_size.valueChanged.connect(self._schedule_preview_refresh)
        self.red_to_magenta = QCheckBox("Convert red to magenta")
        self.red_to_magenta.setChecked(True)
        self.red_to_magenta.toggled.connect(self._schedule_preview_refresh)
        scale_form.addRow(self.include_scale_bar)
        scale_form.addRow(self.auto_scale)
        scale_form.addRow("Manual length:", self.scale_length)
        scale_form.addRow("Bar thickness:", self.scale_thickness)
        scale_form.addRow("Text size:", self.scale_font_size)
        scale_form.addRow(self.red_to_magenta)
        self.left_layout.addWidget(scale_group)

        export_group = QGroupBox("Output")
        export_form = QFormLayout(export_group)
        self.output_format = QComboBox()
        self.output_format.addItem("TIFF (.tif)", "tif")
        self.output_format.addItem("PNG (.png)", "png")
        self.output_format.currentIndexChanged.connect(self._schedule_preview_refresh)
        export_form.addRow("Image format:", self.output_format)
        self.left_layout.addWidget(export_group)

    @Slot()
    def open_ims(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open IMS file", "", "IMS files (*.ims);;All files (*)")
        if not filename:
            return
        reader = IMSReader(filename)
        try:
            metadata = reader.open()
        except IMSReaderError as exc:
            QMessageBox.critical(self, "Unable to open IMS file", f"Reason:\n{exc}")
            return
        finally:
            reader.close()
        self.metadata = metadata
        self.file_label.setText(str(metadata.source_path))
        self.metadata_label.setText(
            f"{metadata.size_x} x {metadata.size_y} x {metadata.size_z} | "
            f"{metadata.channel_count} channels | "
            f"{metadata.voxel_size_x_um:.6g} x {metadata.voxel_size_y_um:.6g} x "
            f"{metadata.voxel_size_z_um:.6g} um"
        )
        self.warning_label.setText("\n".join(metadata.warnings))
        self._populate_channels(metadata)
        self.z_start.setRange(1, metadata.size_z)
        self.z_end.setRange(1, metadata.size_z)
        self.z_start.setValue(1)
        self.z_end.setValue(metadata.size_z)
        self._update_z_info()
        self.export_button.setEnabled(True)
        self.status_label.setText("File loaded. Choose settings and update the preview.")
        self._preview_timer.stop()
        self._preview_refresh_pending = False
        self.update_preview()

    def _populate_channels(self, metadata: IMSMetadata) -> None:
        while self.channels_layout.count():
            item = self.channels_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.channel_controls.clear()
        for channel in metadata.channels:
            row = QFrame()
            row.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QGridLayout(row)
            include = QCheckBox(channel.name)
            include.setChecked(True)
            swatch = QLabel()
            rgb = tuple(round(component * 255) for component in channel.color)
            swatch.setStyleSheet(f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); border: 1px solid #666;")
            swatch.setFixedSize(18, 18)
            minimum = self._range_spinbox(channel.display_min, 0.0)
            maximum = self._range_spinbox(channel.display_max, 1.0)
            include.toggled.connect(self._schedule_preview_refresh)
            minimum.valueChanged.connect(self._schedule_preview_refresh)
            maximum.valueChanged.connect(self._schedule_preview_refresh)
            use_data_minmax: QCheckBox | None = None
            source = "IMS ColorRange" if channel.display_range_source == "ims" else "Data min/max fallback"
            layout.addWidget(include, 0, 0, 1, 2)
            layout.addWidget(swatch, 0, 2)
            layout.addWidget(QLabel("Min"), 1, 0)
            layout.addWidget(minimum, 1, 1)
            layout.addWidget(QLabel("Max"), 2, 0)
            layout.addWidget(maximum, 2, 1)
            layout.addWidget(QLabel(source), 3, 0, 1, 3)
            if channel.display_range_source != "ims":
                use_data_minmax = QCheckBox("Use selected data min/max")
                use_data_minmax.setChecked(True)
                minimum.setEnabled(False)
                maximum.setEnabled(False)
                use_data_minmax.toggled.connect(minimum.setDisabled)
                use_data_minmax.toggled.connect(maximum.setDisabled)
                use_data_minmax.toggled.connect(self._schedule_preview_refresh)
                layout.addWidget(use_data_minmax, 4, 0, 1, 3)
            self.channels_layout.addWidget(row)
            self.channel_controls[channel.index] = ChannelControls(
                include, minimum, maximum, use_data_minmax
            )
        self._populate_preview_choices()

    @staticmethod
    def _range_spinbox(value: float | None, fallback: float) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(4)
        spinbox.setRange(-1_000_000_000_000.0, 1_000_000_000_000.0)
        spinbox.setValue(value if value is not None else fallback)
        return spinbox

    def _populate_preview_choices(self) -> None:
        current = self.preview_combo.currentData()
        self.preview_combo.blockSignals(True)
        self.preview_combo.clear()
        self.preview_combo.addItem("Merge", None)
        if self.metadata is not None:
            for channel in self.metadata.channels:
                self.preview_combo.addItem(channel.name, channel.index)
        index = self.preview_combo.findData(current)
        self.preview_combo.setCurrentIndex(index if index >= 0 else 0)
        self.preview_combo.blockSignals(False)

    @Slot()
    def _update_z_info(self) -> None:
        if self.metadata is None:
            return
        if self.z_start.value() > self.z_end.value():
            self.z_end.setValue(self.z_start.value())
        start = self.z_start.value()
        end = self.z_end.value()
        voxel = self.metadata.voxel_size_z_um
        thickness = (end - start + 1) * voxel
        self.z_info.setText(
            f"Start: slice {start} ({self.metadata.origin_z_um + (start - 1) * voxel:.4g} um)\n"
            f"End: slice {end} ({self.metadata.origin_z_um + (end - 1) * voxel:.4g} um)\n"
            f"Selected thickness: {thickness:.4g} um"
        )

    @Slot(bool)
    def _toggle_scale_length(self, automatic: bool) -> None:
        self.scale_length.setEnabled(self.include_scale_bar.isChecked() and not automatic)

    @Slot(bool)
    def _toggle_scale_controls(self, included: bool) -> None:
        self.auto_scale.setEnabled(included)
        self.scale_length.setEnabled(included and not self.auto_scale.isChecked())
        self.scale_thickness.setEnabled(included)
        self.scale_font_size.setEnabled(included)

    def _current_settings(self, show_warnings: bool = True) -> ExportSettings | None:
        if self.metadata is None:
            return None
        channels = tuple(index for index, controls in self.channel_controls.items() if controls.include.isChecked())
        if not channels:
            message = "Select at least one channel before previewing or exporting."
            if show_warnings:
                QMessageBox.warning(self, "No channels selected", message)
            else:
                self.status_label.setText(message)
            return None
        ranges = self._display_ranges()
        for index in channels:
            if index not in ranges:
                continue
            minimum, maximum = ranges[index]
            if maximum <= minimum:
                message = f"Channel {index}: Max must be greater than Min."
                if show_warnings:
                    QMessageBox.warning(self, "Invalid display range", message)
                else:
                    self.status_label.setText(message)
                return None
        return ExportSettings(
            z_start=self.z_start.value(),
            z_end=self.z_end.value(),
            channel_indices=channels,
            add_scale_bar=self.include_scale_bar.isChecked(),
            scale_bar_um=None if self.auto_scale.isChecked() else self.scale_length.value(),
            red_to_magenta=self.red_to_magenta.isChecked(),
            output_format=str(self.output_format.currentData()),
            scale_bar_thickness_px=(
                None if self.scale_thickness.value() == 0 else self.scale_thickness.value()
            ),
            scale_bar_font_size_px=(
                None if self.scale_font_size.value() == 0 else self.scale_font_size.value()
            ),
        )

    def _display_ranges(self) -> dict[int, tuple[float, float]]:
        return {
            index: (controls.minimum.value(), controls.maximum.value())
            for index, controls in self.channel_controls.items()
            if controls.use_data_minmax is None or not controls.use_data_minmax.isChecked()
        }

    @Slot()
    def update_preview(self) -> None:
        self._preview_timer.stop()
        self._preview_refresh_pending = False
        self._start_preview(show_warnings=True)

    def _start_preview(self, show_warnings: bool) -> None:
        if self._thread is not None:
            self._preview_refresh_pending = True
            self.status_label.setText("Preview refresh queued…")
            return
        settings = self._current_settings(show_warnings=show_warnings)
        if settings is None or self.metadata is None:
            return
        selected_preview = self.preview_combo.currentData()
        if selected_preview is not None and selected_preview not in settings.channel_indices:
            message = "Select this channel before previewing it."
            if show_warnings:
                QMessageBox.warning(self, "Channel not selected", message)
            else:
                self.status_label.setText(message)
            return
        worker = PreviewWorker(self.metadata.source_path, settings, self._display_ranges(), selected_preview)
        self._run_worker(worker, self._preview_finished)

    def _schedule_preview_refresh(self, *_: object) -> None:
        if self.metadata is None:
            return
        self._preview_refresh_pending = True
        self._preview_timer.start(int(self.preview_refresh_limit.currentData()))
        self.status_label.setText("Preview update scheduled…")

    @Slot()
    def _run_scheduled_preview(self) -> None:
        if not self._preview_refresh_pending:
            return
        if self._thread is not None:
            return
        self._preview_refresh_pending = False
        self._start_preview(show_warnings=False)

    def _refresh_limit_changed(self, *_: object) -> None:
        if self._preview_refresh_pending:
            self._preview_timer.start(int(self.preview_refresh_limit.currentData()))

    @Slot()
    def export_tiffs(self) -> None:
        settings = self._current_settings()
        if settings is None or self.metadata is None:
            return
        worker = ExportWorker(self.metadata.source_path, settings, self._display_ranges())
        self._run_worker(worker, self._export_finished)

    def _run_worker(self, worker: QObject, completed_slot: object) -> None:
        if self._thread is not None:
            return
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)  # type: ignore[attr-defined]
        worker.finished.connect(completed_slot)  # type: ignore[attr-defined]
        worker.finished.connect(thread.quit)  # type: ignore[attr-defined]
        worker.failed.connect(self._worker_failed)  # type: ignore[attr-defined]
        worker.failed.connect(thread.quit)  # type: ignore[attr-defined]
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._worker_finished)
        self._thread = thread
        self._worker = worker
        self.open_button.setEnabled(False)
        self.update_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.status_label.setText("Processing…")
        thread.start()

    @Slot(object)
    def _preview_finished(self, image: object) -> None:
        array = np.asarray(image)
        if array.ndim == 2:
            qimage = QImage(array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format.Format_Grayscale8)
        else:
            qimage = QImage(array.data, array.shape[1], array.shape[0], array.strides[0], QImage.Format.Format_RGB888)
        self.preview_pixmap = QPixmap.fromImage(qimage.copy())
        self.fit_preview()
        self.status_label.setText("Preview updated.")

    @Slot()
    def zoom_in(self) -> None:
        self._set_preview_zoom(self.preview_zoom * 1.25)

    @Slot()
    def zoom_out(self) -> None:
        self._set_preview_zoom(self.preview_zoom / 1.25)

    @Slot()
    def actual_size_preview(self) -> None:
        self._set_preview_zoom(1.0)

    @Slot()
    def fit_preview(self) -> None:
        if self.preview_pixmap is None or self.preview_pixmap.isNull():
            return
        viewport = self.preview_scroll.viewport().size()
        width_ratio = max(1, viewport.width() - 8) / self.preview_pixmap.width()
        height_ratio = max(1, viewport.height() - 8) / self.preview_pixmap.height()
        self._set_preview_zoom(min(width_ratio, height_ratio, 1.0))

    def _set_preview_zoom(self, zoom: float) -> None:
        if self.preview_pixmap is None or self.preview_pixmap.isNull():
            return
        self.preview_zoom = min(8.0, max(0.05, zoom))
        width = max(1, round(self.preview_pixmap.width() * self.preview_zoom))
        height = max(1, round(self.preview_pixmap.height() * self.preview_zoom))
        scaled = self.preview_pixmap.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.resize(scaled.size())
        self.zoom_label.setText(f"{self.preview_zoom * 100:.0f}%")

    @Slot(object)
    def _export_finished(self, outcome: object) -> None:
        results, info_path = outcome  # type: ignore[misc]
        result_list: list[ExportResult] = results
        self.last_output_directory = Path(info_path).parent
        self.open_folder_button.setEnabled(True)
        self.status_label.setText(f"Export completed: {len(result_list)} image files created.")
        QMessageBox.information(
            self,
            "Export completed",
            f"{len(result_list)} image files were created.\n\nOutput:\n{self.last_output_directory}\n\nRecord:\n{info_path}",
        )

    @Slot(str)
    def _worker_failed(self, reason: str) -> None:
        self.status_label.setText("Processing failed.")
        QMessageBox.critical(self, "Processing failed", reason)

    @Slot()
    def _worker_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.open_button.setEnabled(True)
        self.update_button.setEnabled(self.metadata is not None)
        self.export_button.setEnabled(self.metadata is not None)
        if self._preview_refresh_pending:
            self._preview_timer.start(int(self.preview_refresh_limit.currentData()))

    @Slot()
    def open_output_folder(self) -> None:
        if self.last_output_directory is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output_directory)))


def launch_gui() -> int:
    """Launch the application and return the Qt event-loop exit code."""

    application = QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow()
    window.show()
    return application.exec()
