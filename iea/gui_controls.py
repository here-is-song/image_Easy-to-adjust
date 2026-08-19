"""Reusable lightweight controls for the Qt interface."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLayout, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QFrame):
    """A framed section whose content can be expanded from its title row."""

    expanded_changed = Signal(bool)

    def __init__(self, title: str, expanded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self.header_button = QToolButton()
        self.header_button.setText(title)
        self.header_button.setCheckable(True)
        self.header_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.header_button.setStyleSheet(
            "QToolButton { border: none; font-weight: 600; padding: 5px; text-align: left; }"
        )
        self.header_button.toggled.connect(self._apply_expanded_state)

        self.content_widget = QWidget()
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(2, 2, 2, 2)
        outer_layout.setSpacing(2)
        outer_layout.addWidget(self.header_button)
        outer_layout.addWidget(self.content_widget)
        self.set_expanded(expanded)

    @property
    def title(self) -> str:
        return self.header_button.text()

    @property
    def is_expanded(self) -> bool:
        return self.header_button.isChecked()

    def set_content_layout(self, layout: QLayout) -> None:
        self.content_widget.setLayout(layout)

    def set_expanded(self, expanded: bool) -> None:
        if self.header_button.isChecked() == expanded:
            self._apply_expanded_state(expanded)
        else:
            self.header_button.setChecked(expanded)

    def _apply_expanded_state(self, expanded: bool) -> None:
        self.header_button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content_widget.setVisible(expanded)
        self.updateGeometry()
        self.expanded_changed.emit(expanded)
