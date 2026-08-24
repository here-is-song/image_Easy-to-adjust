from __future__ import annotations

import os
import shutil
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QSettings, Qt
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QTreeWidgetItem, QWidget

from iea.gui import (
    CellCountingDemoDialog,
    DatasetOpenWorker,
    ExportImageSettingsDialog,
    ExportWorker,
    IMSFigureExporterWindow,
    MetadataCorrectionDialog,
)
from iea.gui_controls import PersistentSelectionMenu
from iea.gui_window import AUTO_MERGE_PREVIEW, GITHUB_REPOSITORY_URL
from iea.ims_reader import IMSReader
from iea.models import ChannelSelection, ExportSettings, MetadataCorrection, ScaleBarSettings
from iea.plugins.cell_counting import load_cell_counting_plugins


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
    application_stylesheet = application.styleSheet()
    assert "#2A2A2A" in application_stylesheet
    assert "#3D3D3F" in application_stylesheet
    assert "#232324" in application_stylesheet
    assert application.palette().window().color().name() == "#2a2a2a"
    assert "#F0B44D" in window.warning_label.styleSheet()
    assert not window.warning_label.wordWrap()
    assert window.centralWidget().layout().indexOf(window.warning_label) > window.centralWidget().layout().indexOf(
        window.content_splitter
    )
    assert window.channels_group.isAncestorOf(window.red_to_magenta)
    menu_names = [action.text().replace("&", "") for action in window.menuBar().actions()]
    assert menu_names == ["File", "Preview", "Batch", "Output Images", "Analysis", "Export", "Help"]
    assert window.content_splitter.count() == 2
    assert window.content_splitter.handleWidth() == 7
    assert not window.content_splitter.isCollapsible(0)
    assert not window.content_splitter.isCollapsible(1)
    assert window.output_width_px == 1000
    assert window.output_height_px == 1000
    assert window.output_dpi == 300
    assert window.output_resize_mode == "fit"
    assert window.scale_thickness.value() == 10
    assert window.scale_font_size.value() == 50
    assert isinstance(window.output_images_menu, PersistentSelectionMenu)
    assert window.export_action.shortcut().toString() == "Ctrl+C"
    assert window.reset_preview_view_action.shortcut().toString() == "Ctrl+B"
    assert not window.cell_count_demo_action.isEnabled()
    assert not window.edit_metadata_action.isEnabled()
    assert not window.send_to_fiji_action.isEnabled()
    assert window.configure_fiji_action.isEnabled()
    assert not window.export_button.isEnabled()
    assert set(window.collapsible_sections) == {"batch_files", "channels", "z_range", "objective", "scale_bar"}
    assert all(section.is_expanded for section in window.collapsible_sections.values())
    window.close()
    assert application is not None


def test_help_menu_opens_repository_and_shows_about_information(gui_settings, monkeypatch):
    QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow(gui_settings)
    opened_urls = []
    about_calls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened_urls.append(url.toString()) or True)
    monkeypatch.setattr(QMessageBox, "about", lambda parent, title, text: about_calls.append((parent, title, text)))

    window.github_action.trigger()
    window.about_action.trigger()

    assert opened_urls == [GITHUB_REPOSITORY_URL]
    assert about_calls[0][0] is window
    assert about_calls[0][1] == "About IEA"
    assert "Song Xuanyu" in about_calls[0][2]
    assert "Codex" in about_calls[0][2]
    assert "simple batch processing of IMS files" in about_calls[0][2]
    assert "author's own workflow needs" in about_calls[0][2]
    assert "songxuanyuhappy@gmail.com" in about_calls[0][2]
    assert "Version 0.3.0" in about_calls[0][2]
    window.close()


def test_metadata_warnings_are_shown_as_one_bottom_line(gui_settings):
    QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow(gui_settings)
    window._update_warning_display(("First warning.\nExtra detail.", "Second warning."))

    assert window.warning_label.text() == "First warning. Extra detail.    Second warning."
    assert "\n" not in window.warning_label.text()
    assert not window.warning_label.isHidden()
    assert window.warning_label.toolTip() == window.warning_label.text()
    window.close()


def test_output_selection_menu_stays_open_for_checks_and_closes_after_pointer_leaves():
    application = QApplication.instance() or QApplication([])
    root_menu = PersistentSelectionMenu("Output Images")
    submenu = root_menu.add_persistent_menu("Two-color Merge")
    choice = QAction("Green + Red", submenu, checkable=True)
    submenu.addAction(choice)

    root_menu.popup(QPoint(10, 10))
    submenu.popup(QPoint(150, 10))
    application.processEvents()
    QTest.mouseClick(
        submenu,
        Qt.MouseButton.LeftButton,
        pos=submenu.actionGeometry(choice).center(),
    )

    assert choice.isChecked()
    assert root_menu.isVisible()
    assert submenu.isVisible()

    QCursor.setPos(QPoint(10_000, 10_000))
    submenu.leaveEvent(QEvent(QEvent.Type.Leave))
    QTest.qWait(180)
    assert not root_menu.isVisible()
    submenu.close()
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


def test_preview_pan_rotate_and_zoom_are_view_only(gui_settings):
    application = QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow(gui_settings)
    window.resize(700, 500)
    window.show()
    window.preview_pixmap = QPixmap(1000, 800)
    window.preview_full_size = (1000, 800)
    window._set_preview_zoom(1.5)
    application.processEvents()
    horizontal = window.preview_scroll.horizontalScrollBar()
    vertical = window.preview_scroll.verticalScrollBar()
    horizontal.setValue(min(100, horizontal.maximum()))
    vertical.setValue(min(80, vertical.maximum()))
    old_scroll = (horizontal.value(), vertical.value())

    window._pan_preview(20, 15)
    assert horizontal.value() <= old_scroll[0]
    assert vertical.value() <= old_scroll[1]
    window._rotate_preview(30.0)
    window._zoom_preview_by_factor(1.25)

    assert window.preview_rotation_degrees == 30.0
    assert window.preview_zoom == pytest.approx(1.875)
    assert window.preview_pixmap.size().width() == 1000
    assert window.preview_pixmap.size().height() == 800
    window.reset_rotation_button.click()
    assert window.preview_rotation_degrees == 0.0
    window._set_preview_zoom(2.0)
    window._rotate_preview(45.0)
    window.reset_preview_view_action.trigger()
    assert window.preview_zoom == 1.0
    assert window.preview_rotation_degrees == 0.0
    assert window.status_label.text() == "Preview view reset to 100% and 0°."
    window.close()
    assert application is not None


def test_cell_counting_dialog_suggests_nuclear_channel_and_builds_manual_roi(
    sample_three_channel_ims,
):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_three_channel_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    channels = tuple(
        replace(channel, name="DRAQ5") if channel.index == 2 else channel
        for channel in metadata.channels
    )
    metadata = replace(metadata, channels=channels)
    parent = QWidget()
    dialog = CellCountingDemoDialog(
        parent,
        metadata,
        load_cell_counting_plugins(),
        1,
        metadata.size_z,
        QPixmap(500, 400),
        (1000, 1000),
        "stretch",
    )

    assert dialog.detection_checks[2].isChecked()
    assert not dialog.detection_checks[0].isChecked()
    assert all(check.isChecked() for check in dialog.measurement_checks.values())
    dialog.roi_mode_combo.setCurrentIndex(dialog.roi_mode_combo.findData("manual"))
    dialog._preview_roi_changed(0.1, 0.2, 0.3, 0.4)
    request = dialog.request()

    assert request.roi_mode == "manual"
    assert request.detection_channel_indices == (2,)
    assert request.measurement_channel_indices == (0, 1, 2)
    assert request.manual_roi.x == pytest.approx(0.1)
    assert request.manual_roi.y == pytest.approx(0.2)
    assert request.manual_roi.width == pytest.approx(0.3)
    assert request.manual_roi.height == pytest.approx(0.4)
    dialog.close()
    assert application is not None


def test_parameter_change_schedules_preview_using_selected_limit(sample_ims, gui_settings):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None

    window = IMSFigureExporterWindow(gui_settings)
    window.metadata = metadata
    window._populate_channels(metadata)
    assert window.channel_rows_layout.count() == metadata.channel_count
    assert window.channels_group.isAncestorOf(window.red_to_magenta)
    green_controls = window.channel_controls[0]
    assert green_controls.minimum.value() == 0.0
    assert green_controls.maximum.value() == 20.0
    assert green_controls.gamma.value() == 0.5
    assert green_controls.minimum_slider.orientation() == Qt.Orientation.Horizontal
    assert green_controls.maximum_slider.orientation() == Qt.Orientation.Horizontal
    assert green_controls.gamma_slider.orientation() == Qt.Orientation.Horizontal
    assert window.output_image_actions[(0,)].isChecked()
    assert window.output_image_actions[(1,)].isChecked()
    assert window.output_image_actions[(0, 1)].isChecked()
    window.refresh_limit_actions[2000].trigger()
    green_controls.gamma_slider.setValue(green_controls.gamma_slider.maximum())

    assert window._preview_refresh_pending
    assert window._preview_timer.isActive()
    assert window._preview_timer.interval() == 2000
    assert green_controls.gamma.value() == 5.0
    assert window._display_adjustments()[0].gamma == 5.0

    window.output_image_actions[(0,)].setChecked(False)
    window.red_to_magenta.setChecked(False)
    settings = window._current_settings()
    selections = window._channel_selections()
    assert settings is not None
    assert not settings.red_to_magenta
    assert settings.resolved_single_channel_indices == (1,)
    assert settings.resolved_merge_channel_groups == ((0, 1),)
    assert not selections[0].export_single
    assert selections[0].include_in_merge
    assert selections[1].export_single
    assert selections[1].include_in_merge

    window._preview_timer.stop()
    window.close()
    assert application is not None


def test_output_images_menu_selects_multiple_single_and_merge_outputs(
    sample_three_channel_ims,
    gui_settings,
):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_three_channel_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None

    window = IMSFigureExporterWindow(gui_settings)
    window.metadata = metadata
    window._populate_channels(metadata)

    submenu_names = [action.text() for action in window.output_images_menu.actions() if action.menu() is not None]
    assert submenu_names == ["Three-color Merge", "Two-color Merge", "Single-color"]
    assert len(window.output_image_actions) == 7
    assert len(window._selected_output_groups()) == 4

    window._set_all_output_actions(False)
    for group in ((1, 2), (0, 1), (0, 1, 2), (0,)):
        window.output_image_actions[group].setChecked(True)
    settings = window._current_settings()

    assert settings is not None
    assert settings.resolved_single_channel_indices == (0,)
    assert set(settings.resolved_merge_channel_groups) == {(1, 2), (0, 1), (0, 1, 2)}
    assert len(settings.required_output_channel_indices) == 3
    assert window.preview_combo.count() == 6

    window._preview_timer.stop()
    window.close()
    assert application is not None


def test_preview_defaults_to_colored_merge_and_follows_enabled_channels(
    sample_three_channel_ims,
    gui_settings,
    monkeypatch,
):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_three_channel_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None

    window = IMSFigureExporterWindow(gui_settings)
    window.metadata = metadata
    window._populate_channels(metadata)
    captured_workers = []
    monkeypatch.setattr(window, "_run_worker", lambda worker, _slot: captured_workers.append(worker))

    assert window.preview_combo.currentData() == AUTO_MERGE_PREVIEW
    assert window.preview_combo.currentText() == "Merge: Selected Channels — Green + Red/Marker + Blue"
    window._start_preview(show_warnings=True)
    assert captured_workers[-1].preview_selection == (0, 1, 2)

    window.channel_controls[2].include.setChecked(False)
    assert window.preview_combo.currentData() == AUTO_MERGE_PREVIEW
    assert window.preview_combo.currentText() == "Merge: Selected Channels — Green + Red/Marker"
    window._start_preview(show_warnings=True)
    assert captured_workers[-1].preview_selection == (0, 1)

    window.channel_controls[0].include.setChecked(False)
    assert window.preview_combo.currentData() == AUTO_MERGE_PREVIEW
    assert window.preview_combo.currentText() == "Merge: Selected Channels — Red/Marker"
    window._start_preview(show_warnings=True)
    assert captured_workers[-1].preview_selection == (1,)

    window._preview_timer.stop()
    window.close()
    assert application is not None


def test_objective_auto_detection_and_manual_override_reach_export_settings(sample_ims, gui_settings):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None

    window = IMSFigureExporterWindow(gui_settings)
    window.metadata = metadata
    window._populate_channels(metadata)
    window.z_start.setValue(1)
    window.z_end.setValue(metadata.size_z)
    window._update_objective_display()

    assert "Detected: 10X — UPLSAPO10X" in window.objective_details.text()
    assert "Metadata · High confidence" in window.objective_details.text()
    window.objective_combo.setCurrentIndex(window.objective_combo.findData("60X"))
    settings = window._current_settings()

    assert "Selected: 60X — UPLSAPO60XS" in window.objective_details.text()
    assert "Detection: Manual selection" in window.objective_details.text()
    assert "XY FOV:" in window.objective_details.text()
    assert "normalized" in window.objective_details.text()
    assert settings is not None
    assert settings.objective_override == "60X"
    window._preview_timer.stop()
    window.close()
    assert application is not None


def test_metadata_correction_dialog_keeps_pixel_shape_read_only(sample_ims, gui_settings):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None
    parent = IMSFigureExporterWindow(gui_settings)
    dialog = MetadataCorrectionDialog(parent, metadata)

    dialog.width_check.setChecked(True)
    dialog.width_spin.setValue(500.0)
    dialog.height_check.setChecked(True)
    dialog.height_spin.setValue(400.0)
    dialog.z_check.setChecked(True)
    dialog.z_spin.setValue(3.5)
    correction = dialog.correction()

    assert correction == MetadataCorrection(500.0, 400.0, 3.5)
    assert f"{500.0 / metadata.size_x:.6g} µm/px" in dialog.pixel_size_label.text()
    dialog.restore_button.click()
    assert dialog.correction().is_empty
    dialog.close()
    parent.close()
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
    first.fiji_directory = tmp_path / "Fiji.app"
    first.settings_store.save_fiji_directory(first.fiji_directory)
    corrected_path = (tmp_path / "wrong-calibration.ims").resolve()
    first.settings_store.save_metadata_corrections(
        {corrected_path: MetadataCorrection(500.0, 400.0, 3.5)}
    )
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
    assert second.fiji_directory == tmp_path / "Fiji.app"
    assert second.metadata_corrections[corrected_path] == MetadataCorrection(500.0, 400.0, 3.5)
    assert second.preview_refresh_interval_ms == 5000
    assert second.refresh_limit_actions[5000].isChecked()
    second.close()
    assert application is not None


def test_collapsible_section_states_persist_between_windows(tmp_path):
    application = QApplication.instance() or QApplication([])
    settings_path = tmp_path / "sections.ini"
    first = IMSFigureExporterWindow(QSettings(str(settings_path), QSettings.Format.IniFormat))

    first.collapsible_sections["channels"].header_button.click()
    first.collapsible_sections["scale_bar"].header_button.click()

    assert not first.collapsible_sections["channels"].is_expanded
    assert first.collapsible_sections["channels"].content_widget.isHidden()
    assert not first.collapsible_sections["scale_bar"].is_expanded
    assert first.collapsible_sections["batch_files"].is_expanded
    first.close()

    second = IMSFigureExporterWindow(QSettings(str(settings_path), QSettings.Format.IniFormat))
    assert not second.collapsible_sections["channels"].is_expanded
    assert second.collapsible_sections["channels"].content_widget.isHidden()
    assert not second.collapsible_sections["scale_bar"].is_expanded
    assert second.collapsible_sections["batch_files"].is_expanded
    assert second.collapsible_sections["z_range"].is_expanded
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


def test_open_oib_uses_background_dataset_worker(tmp_path, monkeypatch, gui_settings):
    QApplication.instance() or QApplication([])
    oib = tmp_path / "sample.oib"
    oib.write_bytes(b"placeholder")
    window = IMSFigureExporterWindow(gui_settings)
    captured = []
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *_args, **_kwargs: ([str(oib)], "OIB files"),
    )
    monkeypatch.setattr(window, "_run_worker", lambda worker, slot: captured.append((worker, slot)))

    window.open_ims()

    assert len(captured) == 1
    assert isinstance(captured[0][0], DatasetOpenWorker)
    assert captured[0][0].source_paths == (oib.resolve(),)
    assert captured[0][1] == window._dataset_open_finished
    window.close()


def test_open_ims_dialog_remembers_last_successful_folder(sample_ims, tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    settings_path = tmp_path / "last-input.ini"
    first = IMSFigureExporterWindow(QSettings(str(settings_path), QSettings.Format.IniFormat))
    monkeypatch.setattr(first, "update_preview", lambda: None)
    first_calls = []

    def choose_first(*args):
        first_calls.append(args)
        return [str(sample_ims)], "IMS files"

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", choose_first)
    first.open_ims()

    assert first_calls[0][2] == ""
    assert first.last_input_directory == sample_ims.parent
    first.close()

    second = IMSFigureExporterWindow(QSettings(str(settings_path), QSettings.Format.IniFormat))
    second_calls = []

    def choose_second(*args):
        second_calls.append(args)
        return [], "IMS files"

    monkeypatch.setattr(QFileDialog, "getOpenFileNames", choose_second)
    second.open_ims()

    assert second_calls[0][2] == str(sample_ims.parent)
    second.close()
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
    assert len(outcomes[0].summary_paths) == 2
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
