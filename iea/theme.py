"""Central dark-theme palette and stylesheet for the IEA desktop interface."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

DARK_STYLESHEET = """
QWidget {
    background-color: #2A2A2A;
    color: #E8E8EA;
    selection-background-color: #5B78A6;
    selection-color: #FFFFFF;
}
QMainWindow, QDialog {
    background-color: #2A2A2A;
}
QLabel {
    background-color: transparent;
}
QMenuBar {
    background-color: #232324;
    color: #F2F2F2;
    border-bottom: 1px solid #4A4A4C;
}
QMenuBar::item {
    background-color: transparent;
    padding: 6px 10px;
}
QMenuBar::item:selected, QMenuBar::item:pressed {
    background-color: #3D3D3F;
}
QMenu {
    background-color: #232324;
    color: #F2F2F2;
    border: 1px solid #505052;
    padding: 4px;
}
QMenu::item {
    padding: 6px 28px 6px 10px;
    border-radius: 3px;
}
QMenu::item:selected {
    background-color: #3D3D3F;
}
QMenu::item:disabled {
    color: #77777A;
}
QMenu::separator {
    height: 1px;
    background-color: #4A4A4C;
    margin: 4px 6px;
}
QPushButton, QToolButton {
    background-color: #3D3D3F;
    color: #F2F2F2;
    border: 1px solid #57575A;
    border-radius: 4px;
    padding: 5px 10px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #4A4A4D;
    border-color: #747478;
}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked {
    background-color: #232324;
}
QPushButton:disabled, QToolButton:disabled {
    background-color: #303032;
    color: #77777A;
    border-color: #3D3D3F;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #3D3D3F;
    color: #F2F2F2;
    border: 1px solid #5A5A5D;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #5B78A6;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #7AA2DF;
}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    background-color: #303032;
    color: #77777A;
}
QComboBox::drop-down {
    width: 24px;
    border-left: 1px solid #5A5A5D;
}
QAbstractItemView, QTreeWidget {
    background-color: #232324;
    alternate-background-color: #303032;
    color: #E8E8EA;
    border: 1px solid #4A4A4C;
    outline: none;
}
QAbstractItemView::item:selected {
    background-color: #4F678D;
    color: #FFFFFF;
}
QHeaderView::section {
    background-color: #3D3D3F;
    color: #F2F2F2;
    border: none;
    border-right: 1px solid #505052;
    border-bottom: 1px solid #505052;
    padding: 5px;
}
QCheckBox {
    background-color: transparent;
    spacing: 6px;
}
QCheckBox:disabled {
    color: #77777A;
}
QSlider::groove:horizontal {
    height: 5px;
    background-color: #232324;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background-color: #6B8FC7;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background-color: #D5D5D8;
    border: 1px solid #8A8A8D;
    width: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QProgressBar {
    background-color: #232324;
    color: #F2F2F2;
    border: 1px solid #505052;
    border-radius: 4px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #5B78A6;
    border-radius: 3px;
}
QScrollArea {
    background-color: #232324;
    border: 1px solid #4A4A4C;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #232324;
    border: none;
    margin: 0;
}
QScrollBar:vertical { width: 12px; }
QScrollBar:horizontal { height: 12px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #555558;
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #707074;
}
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
    border: none;
}
QFrame {
    border-color: #4A4A4C;
}
QToolTip {
    background-color: #232324;
    color: #F2F2F2;
    border: 1px solid #68686B;
    padding: 4px;
}
"""


def apply_dark_theme(application: QApplication) -> None:
    """Apply a consistent palette before constructing application widgets."""

    application.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#2A2A2A"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#E8E8EA"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#232324"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#3D3D3F"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#232324"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#F2F2F2"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#E8E8EA"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#3D3D3F"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#F2F2F2"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#5A5A5D"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#4A4A4C"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#232324"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8A8A8D"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#5B78A6"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#77777A"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#77777A"))
    application.setPalette(palette)
    application.setStyleSheet(DARK_STYLESHEET)
