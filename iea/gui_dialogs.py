"""Small modal dialogs used by the IEA desktop window."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .models import IMSMetadata, MetadataCorrection
from .plugins.cell_counting import (
    CellCountingRequest,
    CellCountingResult,
    CellSegmenterPlugin,
    NormalizedROI,
    write_cell_count_csv,
)


class MetadataCorrectionDialog(QDialog):
    """Edit physical calibration while keeping stored pixel dimensions read-only."""

    def __init__(
        self,
        parent: QWidget,
        metadata: IMSMetadata,
        correction: MetadataCorrection | None = None,
    ) -> None:
        super().__init__(parent)
        self.metadata = metadata
        self.setWindowTitle("Edit Image Metadata")
        self.setModal(True)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)

        explanation = QLabel(
            "Corrections are saved by IEA for this file and used for preview, scale bars, export, "
            "objective checking, and Fiji. The source IMS/OIB is never modified."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        stored_group = QGroupBox("Stored pixel data (read-only)")
        stored_form = QFormLayout(stored_group)
        stored_form.addRow("Pixel dimensions:", QLabel(f"{metadata.size_x} × {metadata.size_y} px"))
        stored_form.addRow("Z / Channels:", QLabel(f"{metadata.size_z} slices / {metadata.channel_count} channels"))
        stored_form.addRow("Data type:", QLabel(metadata.dtype))
        root.addWidget(stored_group)

        calibration_group = QGroupBox("Manual physical calibration")
        calibration_form = QFormLayout(calibration_group)
        self.width_check, self.width_spin = self._calibration_control(
            "Override",
            correction.physical_width_um if correction else None,
            self._source_width_um(),
        )
        self.height_check, self.height_spin = self._calibration_control(
            "Override",
            correction.physical_height_um if correction else None,
            self._source_height_um(),
        )
        self.z_check, self.z_spin = self._calibration_control(
            "Override",
            correction.z_spacing_um if correction else None,
            metadata.voxel_size_z_um,
        )
        calibration_form.addRow("Physical width:", self._control_row(self.width_check, self.width_spin))
        calibration_form.addRow("Physical height:", self._control_row(self.height_check, self.height_spin))
        calibration_form.addRow("Z spacing:", self._control_row(self.z_check, self.z_spin))
        self.pixel_size_label = QLabel()
        calibration_form.addRow("Effective pixel size:", self.pixel_size_label)
        root.addWidget(calibration_group)

        note = QLabel(
            "Choose values from a trusted acquisition record or a calibration image. "
            "Objective name can still be selected separately in the Objective panel."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.restore_button = buttons.addButton(
            "Use Source Metadata",
            QDialogButtonBox.ButtonRole.ResetRole,
        )
        self.restore_button.clicked.connect(self._restore_source)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        for spin in (self.width_spin, self.height_spin):
            spin.valueChanged.connect(self._update_pixel_size_label)
        for check in (self.width_check, self.height_check):
            check.toggled.connect(self._update_pixel_size_label)
        self._update_pixel_size_label()

    @staticmethod
    def _control_row(check: QCheckBox, spin: QDoubleSpinBox) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(check)
        layout.addWidget(spin, 1)
        return widget

    @staticmethod
    def _calibration_control(
        label: str,
        override: float | None,
        source: float | None,
    ) -> tuple[QCheckBox, QDoubleSpinBox]:
        check = QCheckBox(label)
        check.setChecked(override is not None)
        spin = QDoubleSpinBox()
        spin.setDecimals(6)
        spin.setRange(0.000001, 1_000_000_000.0)
        spin.setSuffix(" µm")
        spin.setValue(override if override is not None else source if source is not None else 1.0)
        spin.setEnabled(check.isChecked())
        check.toggled.connect(spin.setEnabled)
        return check, spin

    def _source_width_um(self) -> float | None:
        if self.metadata.extent_x_um is not None:
            return self.metadata.extent_x_um
        if self.metadata.voxel_size_x_um is not None:
            return self.metadata.voxel_size_x_um * self.metadata.size_x
        return None

    def _source_height_um(self) -> float | None:
        if self.metadata.extent_y_um is not None:
            return self.metadata.extent_y_um
        if self.metadata.voxel_size_y_um is not None:
            return self.metadata.voxel_size_y_um * self.metadata.size_y
        return None

    def _effective_width_um(self) -> float | None:
        return self.width_spin.value() if self.width_check.isChecked() else self._source_width_um()

    def _effective_height_um(self) -> float | None:
        return self.height_spin.value() if self.height_check.isChecked() else self._source_height_um()

    @Slot()
    def _update_pixel_size_label(self) -> None:
        width = self._effective_width_um()
        height = self._effective_height_um()
        x_text = f"{width / self.metadata.size_x:.6g} µm/px" if width is not None else "Unknown"
        y_text = f"{height / self.metadata.size_y:.6g} µm/px" if height is not None else "Unknown"
        self.pixel_size_label.setText(f"X: {x_text}    Y: {y_text}")

    @Slot()
    def _restore_source(self) -> None:
        self.width_check.setChecked(False)
        self.height_check.setChecked(False)
        self.z_check.setChecked(False)
        self._update_pixel_size_label()

    def correction(self) -> MetadataCorrection:
        return MetadataCorrection(
            physical_width_um=self.width_spin.value() if self.width_check.isChecked() else None,
            physical_height_um=self.height_spin.value() if self.height_check.isChecked() else None,
            z_spacing_um=self.z_spin.value() if self.z_check.isChecked() else None,
        )


class ExportImageSettingsDialog(QDialog):
    """Edit image-output settings without crowding the main parameter panel."""

    def __init__(
        self,
        parent: QWidget,
        width_px: int,
        height_px: int,
        dpi: int,
        copy_to_clipboard: bool,
        output_format: str,
        resize_mode: str,
        output_directory: Path | None,
        default_directory: Path | None,
    ) -> None:
        super().__init__(parent)
        self.default_directory = default_directory
        self.setWindowTitle("Export Image Settings")
        self.setModal(True)
        self.setMinimumWidth(480)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, 100_000)
        self.width_spin.setSuffix(" px")
        self.width_spin.setValue(width_px)
        form.addRow("Width:", self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, 100_000)
        self.height_spin.setSuffix(" px")
        self.height_spin.setValue(height_px)
        form.addRow("Height:", self.height_spin)

        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(1, 2400)
        self.dpi_spin.setValue(dpi)
        form.addRow("DPI:", self.dpi_spin)

        self.copy_checkbox = QCheckBox("Copy merged image to Clipboard after export")
        self.copy_checkbox.setChecked(copy_to_clipboard)
        form.addRow(self.copy_checkbox)

        self.format_combo = QComboBox()
        self.format_combo.addItem("TIFF (.tif)", "tif")
        self.format_combo.addItem("PNG (.png)", "png")
        format_index = self.format_combo.findData(output_format)
        self.format_combo.setCurrentIndex(max(0, format_index))
        form.addRow("File format:", self.format_combo)

        self.resize_mode_combo = QComboBox()
        self.resize_mode_combo.addItem("Fit (preserve ratio, add margins)", "fit")
        self.resize_mode_combo.addItem("Stretch (exact size)", "stretch")
        self.resize_mode_combo.addItem("Crop (preserve ratio, crop edges)", "crop")
        resize_index = self.resize_mode_combo.findData(resize_mode)
        self.resize_mode_combo.setCurrentIndex(max(0, resize_index))
        form.addRow("Resize mode:", self.resize_mode_combo)

        output_row = QWidget()
        output_layout = QHBoxLayout(output_row)
        output_layout.setContentsMargins(0, 0, 0, 0)
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setText(str(output_directory) if output_directory else "")
        default_text = str(default_directory) if default_directory else "source IMS default folder"
        self.output_path_edit.setPlaceholderText(f"Default: {default_text}")
        output_layout.addWidget(self.output_path_edit, 1)
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_output_directory)
        output_layout.addWidget(browse_button)
        default_button = QPushButton("Use Default")
        default_button.clicked.connect(self.output_path_edit.clear)
        output_layout.addWidget(default_button)
        form.addRow("Save location:", output_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @Slot()
    def _browse_output_directory(self) -> None:
        typed_path = self.output_path_edit.text().strip()
        if typed_path:
            starting_directory = Path(typed_path)
        elif self.default_directory is not None:
            starting_directory = self.default_directory.parent
        else:
            starting_directory = Path.cwd()
        selected = QFileDialog.getExistingDirectory(self, "Select output folder", str(starting_directory))
        if selected:
            self.output_path_edit.setText(selected)

    def selected_output_directory(self) -> Path | None:
        value = self.output_path_edit.text().strip()
        return Path(value) if value else None


class RectangularROIEditor(QWidget):
    """Small preview surface for drawing one rectangular ROI."""

    roi_changed = Signal(float, float, float, float)

    def __init__(self, pixmap: QPixmap | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = pixmap
        self._content_rect = QRectF()
        self._start: QPointF | None = None
        self._selection = QRectF(0.0, 0.0, 1.0, 1.0)
        self.setMinimumSize(480, 300)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())
        if self._pixmap is None or self._pixmap.isNull():
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Generate a preview before drawing an ROI.")
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        left = (self.width() - scaled.width()) / 2
        top = (self.height() - scaled.height()) / 2
        self._content_rect = QRectF(left, top, scaled.width(), scaled.height())
        painter.drawPixmap(round(left), round(top), scaled)
        selection = QRectF(
            left + self._selection.x() * scaled.width(),
            top + self._selection.y() * scaled.height(),
            self._selection.width() * scaled.width(),
            self._selection.height() * scaled.height(),
        )
        painter.setPen(QPen(Qt.GlobalColor.yellow, 2, Qt.PenStyle.DashLine))
        painter.drawRect(selection)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._content_rect.contains(event.position()):
            self._start = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._set_from_widget_points(self._start, event.position(), emit=False)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._start is not None:
            self._set_from_widget_points(self._start, event.position(), emit=True)
            self._start = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _set_from_widget_points(self, first: QPointF, second: QPointF, emit: bool) -> None:
        if self._content_rect.isEmpty():
            return
        first = QPointF(
            min(max(first.x(), self._content_rect.left()), self._content_rect.right()),
            min(max(first.y(), self._content_rect.top()), self._content_rect.bottom()),
        )
        second = QPointF(
            min(max(second.x(), self._content_rect.left()), self._content_rect.right()),
            min(max(second.y(), self._content_rect.top()), self._content_rect.bottom()),
        )
        rectangle = QRectF(first, second).normalized()
        if rectangle.width() < 2 or rectangle.height() < 2:
            return
        self._selection = QRectF(
            (rectangle.x() - self._content_rect.x()) / self._content_rect.width(),
            (rectangle.y() - self._content_rect.y()) / self._content_rect.height(),
            rectangle.width() / self._content_rect.width(),
            rectangle.height() / self._content_rect.height(),
        )
        self.update()
        if emit:
            self.roi_changed.emit(
                self._selection.x(),
                self._selection.y(),
                self._selection.width(),
                self._selection.height(),
            )


class CellCountingDemoDialog(QDialog):
    """Configure the active cell-counting plugin and a reproducible ROI."""

    def __init__(
        self,
        parent: QWidget,
        metadata: IMSMetadata,
        plugins: dict[str, CellSegmenterPlugin],
        z_start: int,
        z_end: int,
        preview_pixmap: QPixmap | None,
        preview_size: tuple[int, int],
        resize_mode: str,
    ) -> None:
        super().__init__(parent)
        self.metadata = metadata
        self.plugins = plugins
        self.preview_size = preview_size
        self.resize_mode = resize_mode
        self.setWindowTitle("Cell Counting Plugin Demo")
        self.setModal(True)
        self.resize(760, 760)
        root = QVBoxLayout(self)
        notice = QLabel(
            "Demo workflow: segment one shared cell-label image, then measure every selected marker channel. "
            "Validate the overlay before using counts for scientific conclusions."
        )
        notice.setWordWrap(True)
        root.addWidget(notice)

        form = QFormLayout()
        self.plugin_combo = QComboBox()
        for plugin_id, plugin in plugins.items():
            self.plugin_combo.addItem(plugin.display_name, plugin_id)
            self.plugin_combo.setItemData(
                self.plugin_combo.count() - 1,
                plugin.description,
                Qt.ItemDataRole.ToolTipRole,
            )
        form.addRow("Segmentation plugin:", self.plugin_combo)
        self.z_start_spin = QSpinBox()
        self.z_start_spin.setRange(1, metadata.size_z)
        self.z_start_spin.setValue(z_start)
        self.z_end_spin = QSpinBox()
        self.z_end_spin.setRange(1, metadata.size_z)
        self.z_end_spin.setValue(z_end)
        z_widget = QWidget()
        z_layout = QHBoxLayout(z_widget)
        z_layout.setContentsMargins(0, 0, 0, 0)
        z_layout.addWidget(self.z_start_spin)
        z_layout.addWidget(QLabel("to"))
        z_layout.addWidget(self.z_end_spin)
        form.addRow("Z range (MIP):", z_widget)
        root.addLayout(form)

        channels_row = QHBoxLayout()
        detection_group = QGroupBox("Detection input channels")
        detection_layout = QVBoxLayout(detection_group)
        measurement_group = QGroupBox("Measure / classify channels")
        measurement_layout = QVBoxLayout(measurement_group)
        self.detection_checks: dict[int, QCheckBox] = {}
        self.measurement_checks: dict[int, QCheckBox] = {}
        automatic_detection = self._suggest_detection_channel(metadata)
        for channel in metadata.channels:
            detection = QCheckBox(channel.name)
            detection.setChecked(channel.index == automatic_detection)
            measurement = QCheckBox(channel.name)
            measurement.setChecked(True)
            detection_layout.addWidget(detection)
            measurement_layout.addWidget(measurement)
            self.detection_checks[channel.index] = detection
            self.measurement_checks[channel.index] = measurement
        channels_row.addWidget(detection_group)
        channels_row.addWidget(measurement_group)
        root.addLayout(channels_row)

        analysis_form = QFormLayout()
        self.roi_mode_combo = QComboBox()
        self.roi_mode_combo.addItem("Full image", "full")
        self.roi_mode_combo.addItem("Automatic foreground rectangle", "auto")
        self.roi_mode_combo.addItem("Manual rectangle", "manual")
        analysis_form.addRow("ROI:", self.roi_mode_combo)
        self.threshold_mode_combo = QComboBox()
        self.threshold_mode_combo.addItem("Automatic Otsu", "otsu")
        self.threshold_mode_combo.addItem("Manual normalized value", "manual")
        analysis_form.addRow("Detection threshold:", self.threshold_mode_combo)
        self.manual_threshold_spin = QDoubleSpinBox()
        self.manual_threshold_spin.setRange(0.0, 1.0)
        self.manual_threshold_spin.setDecimals(3)
        self.manual_threshold_spin.setSingleStep(0.01)
        self.manual_threshold_spin.setValue(0.35)
        self.manual_threshold_spin.setEnabled(False)
        analysis_form.addRow("Manual threshold:", self.manual_threshold_spin)
        self.threshold_correction_spin = QDoubleSpinBox()
        self.threshold_correction_spin.setRange(0.1, 3.0)
        self.threshold_correction_spin.setDecimals(2)
        self.threshold_correction_spin.setValue(1.0)
        analysis_form.addRow("Threshold correction:", self.threshold_correction_spin)
        self.positive_threshold_spin = QDoubleSpinBox()
        self.positive_threshold_spin.setRange(0.0, 1.0)
        self.positive_threshold_spin.setDecimals(3)
        self.positive_threshold_spin.setValue(0.25)
        analysis_form.addRow("Marker-positive mean:", self.positive_threshold_spin)
        self.minimum_area_spin = QSpinBox()
        self.minimum_area_spin.setRange(1, 10_000_000)
        self.minimum_area_spin.setValue(20)
        analysis_form.addRow("Minimum object area:", self.minimum_area_spin)
        self.maximum_area_spin = QSpinBox()
        self.maximum_area_spin.setRange(1, 100_000_000)
        self.maximum_area_spin.setValue(100_000)
        analysis_form.addRow("Maximum object area:", self.maximum_area_spin)
        self.exclude_border_check = QCheckBox("Exclude objects touching the ROI border")
        self.exclude_border_check.setChecked(True)
        analysis_form.addRow(self.exclude_border_check)
        root.addLayout(analysis_form)

        manual_group = QGroupBox("Manual ROI — drag on preview or enter source-image percentages")
        manual_root = QVBoxLayout(manual_group)
        manual_form = QFormLayout()
        self.roi_spins: dict[str, QDoubleSpinBox] = {}
        for label, key, default in (
            ("X:", "x", 0.0),
            ("Y:", "y", 0.0),
            ("Width:", "width", 100.0),
            ("Height:", "height", 100.0),
        ):
            spin = QDoubleSpinBox()
            spin.setRange(0.0 if key in {"x", "y"} else 0.1, 100.0)
            spin.setSuffix(" %")
            spin.setDecimals(1)
            spin.setValue(default)
            manual_form.addRow(label, spin)
            self.roi_spins[key] = spin
        manual_root.addLayout(manual_form)
        self.roi_editor = RectangularROIEditor(preview_pixmap)
        self.roi_editor.roi_changed.connect(self._preview_roi_changed)
        manual_root.addWidget(self.roi_editor)
        root.addWidget(manual_group, 1)
        self.manual_roi_group = manual_group
        self.manual_roi_group.setEnabled(False)
        self.roi_mode_combo.currentIndexChanged.connect(self._roi_mode_changed)
        self.threshold_mode_combo.currentIndexChanged.connect(
            lambda: self.manual_threshold_spin.setEnabled(
                self.threshold_mode_combo.currentData() == "manual"
            )
        )

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run Demo")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _suggest_detection_channel(metadata: IMSMetadata) -> int:
        terms = ("dapi", "draq", "hoechst", "nucleus", "nuclei", "dna")
        for channel in metadata.channels:
            if any(term in channel.name.casefold() for term in terms):
                return channel.index
        return metadata.channels[-1].index

    @Slot()
    def _roi_mode_changed(self) -> None:
        self.manual_roi_group.setEnabled(self.roi_mode_combo.currentData() == "manual")

    @Slot(float, float, float, float)
    def _preview_roi_changed(self, x: float, y: float, width: float, height: float) -> None:
        source_roi = self._canvas_roi_to_source(NormalizedROI(x, y, width, height))
        for key, value in (
            ("x", source_roi.x),
            ("y", source_roi.y),
            ("width", source_roi.width),
            ("height", source_roi.height),
        ):
            self.roi_spins[key].setValue(value * 100.0)

    def _canvas_roi_to_source(self, roi: NormalizedROI) -> NormalizedROI:
        source_width = self.metadata.size_x
        source_height = self.metadata.size_y
        canvas_width, canvas_height = self.preview_size
        x0 = roi.x * canvas_width
        y0 = roi.y * canvas_height
        x1 = (roi.x + roi.width) * canvas_width
        y1 = (roi.y + roi.height) * canvas_height
        if self.resize_mode == "stretch":
            return roi
        scale = (
            max(canvas_width / source_width, canvas_height / source_height)
            if self.resize_mode == "crop"
            else min(canvas_width / source_width, canvas_height / source_height)
        )
        scaled_width = source_width * scale
        scaled_height = source_height * scale
        offset_x = (canvas_width - scaled_width) / 2
        offset_y = (canvas_height - scaled_height) / 2
        source_x0 = np.clip((x0 - offset_x) / scale, 0, source_width)
        source_y0 = np.clip((y0 - offset_y) / scale, 0, source_height)
        source_x1 = np.clip((x1 - offset_x) / scale, 0, source_width)
        source_y1 = np.clip((y1 - offset_y) / scale, 0, source_height)
        return NormalizedROI(
            float(source_x0 / source_width),
            float(source_y0 / source_height),
            float(max(1.0, source_x1 - source_x0) / source_width),
            float(max(1.0, source_y1 - source_y0) / source_height),
        )

    @Slot()
    def _validate_and_accept(self) -> None:
        if not any(check.isChecked() for check in self.detection_checks.values()):
            QMessageBox.warning(self, "Detection channel required", "Select at least one detection input channel.")
            return
        if not any(check.isChecked() for check in self.measurement_checks.values()):
            QMessageBox.warning(self, "Measurement channel required", "Select at least one channel to measure.")
            return
        if self.z_start_spin.value() > self.z_end_spin.value():
            QMessageBox.warning(self, "Invalid Z range", "The Z start value cannot be greater than Z end.")
            return
        if self.minimum_area_spin.value() > self.maximum_area_spin.value():
            QMessageBox.warning(
                self,
                "Invalid object area",
                "Minimum object area cannot be greater than maximum object area.",
            )
            return
        self.accept()

    def selected_plugin(self) -> CellSegmenterPlugin:
        return self.plugins[str(self.plugin_combo.currentData())]

    def request(self) -> CellCountingRequest:
        return CellCountingRequest(
            detection_channel_indices=tuple(
                index for index, check in self.detection_checks.items() if check.isChecked()
            ),
            measurement_channel_indices=tuple(
                index for index, check in self.measurement_checks.items() if check.isChecked()
            ),
            z_start=self.z_start_spin.value(),
            z_end=self.z_end_spin.value(),
            roi_mode=str(self.roi_mode_combo.currentData()),
            manual_roi=NormalizedROI(
                self.roi_spins["x"].value() / 100.0,
                self.roi_spins["y"].value() / 100.0,
                self.roi_spins["width"].value() / 100.0,
                self.roi_spins["height"].value() / 100.0,
            ),
            threshold_mode=str(self.threshold_mode_combo.currentData()),
            manual_threshold=self.manual_threshold_spin.value(),
            threshold_correction=self.threshold_correction_spin.value(),
            positive_threshold=self.positive_threshold_spin.value(),
            minimum_area_px=self.minimum_area_spin.value(),
            maximum_area_px=self.maximum_area_spin.value(),
            exclude_border_objects=self.exclude_border_check.isChecked(),
        )


class CellCountingResultsDialog(QDialog):
    """Inspect overlay, multi-channel summary, and per-cell measurements."""

    def __init__(self, parent: QWidget, result: CellCountingResult) -> None:
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("Cell Counting Demo Results")
        self.resize(900, 720)
        root = QVBoxLayout(self)
        threshold = "N/A" if result.threshold is None else f"{result.threshold:.4f}"
        summary = QLabel(
            f"Objects: {result.total_count} · Plugin: {result.plugin_name} · "
            f"Threshold: {threshold} · ROI: {result.roi_bounds_px}"
        )
        summary.setWordWrap(True)
        root.addWidget(summary)
        tabs = QTabWidget()
        root.addWidget(tabs, 1)

        overlay_label = QLabel()
        overlay = np.ascontiguousarray(result.overlay_rgb)
        qimage = QImage(
            overlay.data,
            overlay.shape[1],
            overlay.shape[0],
            overlay.strides[0],
            QImage.Format.Format_RGB888,
        )
        overlay_label.setPixmap(QPixmap.fromImage(qimage.copy()))
        overlay_scroll = QScrollArea()
        overlay_scroll.setWidget(overlay_label)
        overlay_scroll.setWidgetResizable(False)
        overlay_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tabs.addTab(overlay_scroll, "Overlay")

        summary_table = QTableWidget(len(result.channel_summaries), 4)
        summary_table.setHorizontalHeaderLabels(
            ["Channel", "Positive cells", "Positive %", "Mean object intensity"]
        )
        for row, item in enumerate(result.channel_summaries):
            for column, value in enumerate(
                (
                    item.channel_name,
                    str(item.positive_count),
                    f"{item.positive_percent:.2f}",
                    f"{item.mean_object_intensity:.4f}",
                )
            ):
                summary_table.setItem(row, column, QTableWidgetItem(value))
        summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabs.addTab(summary_table, "Channel summary")

        headers = ["ID", "X px", "Y px", "Area px"]
        for name in result.measurement_channel_names:
            headers.extend((f"{name} mean", f"{name} max", f"{name} +"))
        cell_table = QTableWidget(len(result.measurements), len(headers))
        cell_table.setHorizontalHeaderLabels(headers)
        for row, measurement in enumerate(result.measurements):
            values: list[str] = [
                str(measurement.object_id),
                f"{measurement.centroid_x_px:.2f}",
                f"{measurement.centroid_y_px:.2f}",
                str(measurement.area_px),
            ]
            for mean, maximum, positive in zip(
                measurement.channel_means,
                measurement.channel_maxima,
                measurement.channel_positive,
                strict=True,
            ):
                values.extend((f"{mean:.4f}", f"{maximum:.4f}", "Yes" if positive else "No"))
            for column, value in enumerate(values):
                cell_table.setItem(row, column, QTableWidgetItem(value))
        cell_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabs.addTab(cell_table, "Per-cell measurements")

        if result.notes:
            notes = QLabel("    ".join(result.notes))
            notes.setWordWrap(True)
            root.addWidget(notes)
        button_row = QHBoxLayout()
        export_button = QPushButton("Export per-cell CSV…")
        export_button.clicked.connect(self._export_csv)
        button_row.addWidget(export_button)
        button_row.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        root.addLayout(button_row)

    @Slot()
    def _export_csv(self) -> None:
        default = self.result.source_path.with_name(f"{self.result.source_path.stem}_cell_count.csv")
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Export per-cell measurements",
            str(default),
            "CSV files (*.csv)",
        )
        if selected:
            write_cell_count_csv(self.result, selected)
