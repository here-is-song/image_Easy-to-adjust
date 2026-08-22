"""Reusable lightweight controls for the Qt interface."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QEnterEvent, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QFrame, QLabel, QLayout, QMenu, QToolButton, QVBoxLayout, QWidget


class InteractivePreviewLabel(QLabel):
    """Image surface with mouse gestures, leaving the actual transform to its parent."""

    pan_requested = Signal(int, int)
    rotation_requested = Signal(float)
    zoom_requested = Signal(float)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._drag_position: QPoint | None = None
        self._drag_button = Qt.MouseButton.NoButton
        self.setMouseTracking(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self._drag_position = event.position().toPoint()
            self._drag_button = event.button()
            self.setCursor(
                Qt.CursorShape.ClosedHandCursor
                if event.button() == Qt.MouseButton.LeftButton
                else Qt.CursorShape.SizeAllCursor
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_position is None:
            super().mouseMoveEvent(event)
            return
        current = event.position().toPoint()
        delta = current - self._drag_position
        self._drag_position = current
        if self._drag_button == Qt.MouseButton.LeftButton:
            self.pan_requested.emit(delta.x(), delta.y())
        elif self._drag_button == Qt.MouseButton.RightButton:
            self.rotation_requested.emit((delta.x() - delta.y()) * 0.35)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == self._drag_button:
            self._drag_position = None
            self._drag_button = Qt.MouseButton.NoButton
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom_requested.emit(1.25**steps)
            event.accept()
            return
        super().wheelEvent(event)


class PersistentSelectionMenu(QMenu):
    """Keep checkable choices open until the pointer leaves the menu tree."""

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        root_menu: PersistentSelectionMenu | None = None,
    ) -> None:
        super().__init__(title, parent)
        self._root_menu = root_menu or self
        if root_menu is None:
            # A short bridge prevents accidental closing while the pointer moves
            # through the small gap between a parent menu and its submenu.
            self._leave_timer = QTimer(self)
            self._leave_timer.setSingleShot(True)
            self._leave_timer.setInterval(120)
            self._leave_timer.timeout.connect(self._close_if_pointer_outside)
            self.aboutToHide.connect(self._leave_timer.stop)

    def add_persistent_menu(self, title: str) -> PersistentSelectionMenu:
        submenu = PersistentSelectionMenu(title, self, self._root_menu)
        self.addMenu(submenu)
        return submenu

    def enterEvent(self, event: QEnterEvent) -> None:
        self._root_menu._leave_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._root_menu._leave_timer.start()
        super().leaveEvent(event)

    def _close_if_pointer_outside(self) -> None:
        pointer = QCursor.pos()
        menus = (self._root_menu, *self._root_menu.findChildren(PersistentSelectionMenu))
        if any(menu.isVisible() and menu.rect().contains(menu.mapFromGlobal(pointer)) for menu in menus):
            return
        self._root_menu.close()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        action = self.actionAt(event.position().toPoint())
        if action is not None and action.isEnabled() and action.isCheckable():
            action.trigger()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        action = self.activeAction()
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if action is not None and action.isEnabled() and action.isCheckable():
                action.trigger()
                event.accept()
                return
        super().keyPressEvent(event)


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
