from __future__ import annotations

import os
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QTreeWidgetItem

from iea.gui import ExportImageSettingsDialog, ExportWorker, IMSFigureExporterWindow
from iea.ims_reader import IMSReader
from iea.models import ChannelSelection, ExportSettings, ScaleBarSettings


@pytest.fixture
def gui_settings(tmp_path):
    return QSettings(str(tmp_path / "gui-test.ini"), QSettings.Format.IniFormat)


def _add_batch_item(window, path, metadata):
    window.batch_metadata[path] = metadata
    item = QTreeWidgetItem([path.name, "", ""])
    item.setData(0, Qt.ItemDataRole.UserRole, str(path))
    item.setCheckState(1, Qt.CheckState.Checked)
    item.setCheckState(2, Qt.CheckState.Checked)
    window.batch_tree.addTopLevelItem(item)
    return item


def test_gui_window_constructs_without_a_display(gui_settings):
    application = QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow(gui_settings)
    assert window.windowTitle() == "image_easy-to-adjust (IEA)"
    assert not window.windowIcon().isNull()
    menu_names = [action.text().replace("&", "") for action in window.menuBar().actions()]
    assert menu_names == ["File", "Preview", "Batch", "Export"]
    assert window.content_splitter.count() == 2
    assert window.content_splitter.handleWidth() == 7
    assert not window.content_splitter.isCollapsible(0)
    assert not window.content_splitter.isCollapsible(1)
    assert window.output_width_px == 1000
    assert window.output_height_px == 1000
    assert window.output_dpi == 300
    assert window.output_resize_mode == "fit"
    assert window.export_action.shortcut().toString() == "Ctrl+C"
    assert not window.export_button.isEnabled()
    window.close()
    assert application is not None


def test_preview_zoom_changes_display_but_not_source_pixmap(gui_settings):
    QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow(gui_settings)
    window.preview_pixmap = QPixmap(100, 80)
    original_size = window.preview_pixmap.size()
    window._set_preview_zoom(2.0)
    assert window.preview_label.pixmap().size().width() == 200
    assert window.preview_label.pixmap().size().height() == 160
    assert window.preview_pixmap.size() == original_size
    window.close()


def test_parameter_change_schedules_preview_using_selected_limit(sample_ims, gui_settings):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None

    window = IMSFigureExporterWindow(gui_settings)
    window.metadata = metadata
    window._populate_channels(metadata)
    window.refresh_limit_actions[2000].trigger()
    window.scale_thickness.setValue(4)

    assert window._preview_refresh_pending
    assert window._preview_timer.isActive()
    assert window._preview_timer.interval() == 2000

    window._preview_timer.stop()
    window.close()
    assert application is not None


def test_selected_output_folder_is_passed_to_gui_export(sample_ims, tmp_path, monkeypatch, gui_settings):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None

    window = IMSFigureExporterWindow(gui_settings)
    window.metadata = metadata
    _add_batch_item(window, sample_ims, metadata)
    window._populate_channels(metadata)
    window.z_start.setRange(1, metadata.size_z)
    window.z_end.setRange(1, metadata.size_z)
    window.z_start.setValue(1)
    window.z_end.setValue(metadata.size_z)
    window.output_directory = tmp_path
    window.output_width_px = 1200
    window.output_height_px = 900
    window.output_dpi = 600
    window.output_format = "png"
    window.copy_to_clipboard = True

    captured = []
    monkeypatch.setattr(window, "_run_worker", lambda worker, _slot: captured.append(worker))
    window.export_tiffs()

    assert window.output_directory == tmp_path
    assert captured[0].source_paths == (sample_ims,)
    assert captured[0].output_directory == tmp_path
    assert captured[0].settings.output.width_px == 1200
    assert captured[0].settings.output.height_px == 900
    assert captured[0].settings.output.dpi == 600
    assert captured[0].settings.output.format == "png"
    window._preview_timer.stop()
    window.close()
    assert application is not None


def test_export_settings_dialog_contains_current_values(tmp_path, gui_settings):
    application = QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow(gui_settings)
    dialog = ExportImageSettingsDialog(
        window,
        1000,
        1000,
        300,
        True,
        "png",
        "fit",
        tmp_path,
        tmp_path / "default",
    )

    assert dialog.width_spin.value() == 1000
    assert dialog.height_spin.value() == 1000
    assert dialog.dpi_spin.value() == 300
    assert dialog.copy_checkbox.isChecked()
    assert dialog.format_combo.currentData() == "png"
    assert dialog.resize_mode_combo.currentData() == "fit"
    assert dialog.selected_output_directory() == tmp_path

    dialog.close()
    window.close()
    assert application is not None


def test_copy_image_to_clipboard(tmp_path):
    application = QApplication.instance() or QApplication([])
    path = tmp_path / "clipboard.png"
    Image.fromarray(np.zeros((12, 16, 3), dtype=np.uint8)).save(path)

    IMSFigureExporterWindow._copy_image_to_clipboard(path)

    clipboard_image = QApplication.clipboard().image()
    assert clipboard_image.width() == 16
    assert clipboard_image.height() == 12
    assert application is not None


def test_menu_settings_persist_between_windows(tmp_path):
    application = QApplication.instance() or QApplication([])
    settings_path = tmp_path / "persistent.ini"
    first_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    first = IMSFigureExporterWindow(first_settings)
    first.output_width_px = 1400
    first.output_height_px = 900
    first.output_dpi = 600
    first.output_format = "png"
    first.output_resize_mode = "crop"
    first.copy_to_clipboard = True
    first.output_directory = tmp_path / "saved-output"
    first._save_export_settings()
    first.refresh_limit_actions[5000].trigger()
    first.close()

    second_settings = QSettings(str(settings_path), QSettings.Format.IniFormat)
    second = IMSFigureExporterWindow(second_settings)
    assert second.output_width_px == 1400
    assert second.output_height_px == 900
    assert second.output_dpi == 600
    assert second.output_format == "png"
    assert second.output_resize_mode == "crop"
    assert second.copy_to_clipboard
    assert second.output_directory == tmp_path / "saved-output"
    assert second.preview_refresh_interval_ms == 5000
    assert second.refresh_limit_actions[5000].isChecked()
    second.close()
    assert application is not None


def test_open_multiple_files_defaults_to_process_and_export_all(sample_ims, tmp_path, monkeypatch, gui_settings):
    application = QApplication.instance() or QApplication([])
    second_path = tmp_path / "second.ims"
    shutil.copyfile(sample_ims, second_path)
    window = IMSFigureExporterWindow(gui_settings)
    monkeypatch.setattr(window, "update_preview", lambda: None)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(sample_ims), str(second_path)], "IMS files"),
    )

    window.open_ims()

    assert window.batch_tree.topLevelItemCount() == 2
    assert len(window._selected_export_paths()) == 2
    first_item = window.batch_tree.topLevelItem(0)
    first_item.setCheckState(1, Qt.CheckState.Unchecked)
    assert first_item.checkState(2) == Qt.CheckState.Unchecked
    first_item.setCheckState(2, Qt.CheckState.Checked)
    assert first_item.checkState(1) == Qt.CheckState.Checked
    assert len(window._selected_export_paths()) == 2
    window.close()
    assert application is not None


def test_batch_worker_exports_every_selected_source(sample_ims, tmp_path):
    application = QApplication.instance() or QApplication([])
    second_path = tmp_path / "second.ims"
    shutil.copyfile(sample_ims, second_path)
    output_dir = tmp_path / "batch-output"
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0, 1),
        scale_bar=ScaleBarSettings(enabled=False),
    )
    worker = ExportWorker(
        (sample_ims, second_path),
        settings,
        (
            ChannelSelection(0, "Green"),
            ChannelSelection(1, "Red/Marker"),
        ),
        output_dir,
    )
    outcomes = []
    failures = []
    worker.finished.connect(outcomes.append)
    worker.failed.connect(failures.append)

    worker.run()

    assert not failures
    assert len(outcomes) == 1
    assert len(outcomes[0].results) == 6
    assert len(outcomes[0].info_paths) == 2
    assert not outcomes[0].errors
    assert not outcomes[0].warnings
    assert not outcomes[0].cancelled
    assert application is not None


def test_batch_worker_can_cancel_before_first_file(sample_ims, tmp_path):
    application = QApplication.instance() or QApplication([])
    settings = ExportSettings(
        z_start=1,
        z_end=3,
        channel_indices=(0,),
        scale_bar=ScaleBarSettings(enabled=False),
    )
    worker = ExportWorker(
        (sample_ims,),
        settings,
        (ChannelSelection(0, "Green"),),
        tmp_path / "cancelled",
    )
    outcomes = []
    worker.finished.connect(outcomes.append)
    worker.cancel()

    worker.run()

    assert len(outcomes) == 1
    assert outcomes[0].cancelled
    assert not outcomes[0].results
    assert application is not None
