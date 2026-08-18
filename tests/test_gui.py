from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap

from app.gui import IMSFigureExporterWindow
from app.ims_reader import IMSReader


def test_gui_window_constructs_without_a_display():
    application = QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow()
    assert window.windowTitle() == "IMS Publication Figure Exporter"
    assert not window.export_button.isEnabled()
    window.close()
    assert application is not None


def test_preview_zoom_changes_display_but_not_source_pixmap():
    application = QApplication.instance() or QApplication([])
    window = IMSFigureExporterWindow()
    window.preview_pixmap = QPixmap(100, 80)
    original_size = window.preview_pixmap.size()
    window._set_preview_zoom(2.0)
    assert window.preview_label.pixmap().size().width() == 200
    assert window.preview_label.pixmap().size().height() == 160
    assert window.preview_pixmap.size() == original_size
    window.close()


def test_parameter_change_schedules_preview_using_selected_limit(sample_ims):
    application = QApplication.instance() or QApplication([])
    with IMSReader(sample_ims) as reader:
        metadata = reader.metadata
    assert metadata is not None

    window = IMSFigureExporterWindow()
    window.metadata = metadata
    window._populate_channels(metadata)
    window.preview_refresh_limit.setCurrentIndex(2)
    window.scale_thickness.setValue(4)

    assert window._preview_refresh_pending
    assert window._preview_timer.isActive()
    assert window._preview_timer.interval() == 2000

    window._preview_timer.stop()
    window.close()
    assert application is not None
