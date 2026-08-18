"""Small modal dialogs used by the IEA desktop window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
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
