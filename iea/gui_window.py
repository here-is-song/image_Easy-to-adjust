"""PySide6 desktop interface for the IMS figure exporter."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, QRectF, QSettings, Qt, QThread, QTimer, QUrl, Slot
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QDesktopServices,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .exporter import default_output_directory
from .fiji_bridge import FijiBridgeError, discover_fiji_installation, resolve_fiji_executable
from .fv1200_calibration import FV1200_OBJECTIVES
from .gui_controls import CollapsibleSection, InteractivePreviewLabel, PersistentSelectionMenu
from .gui_dialogs import (
    CellCountingDemoDialog,
    CellCountingResultsDialog,
    ExportImageSettingsDialog,
    MetadataCorrectionDialog,
)
from .gui_workers import (
    BatchExportOutcome,
    CellCountWorker,
    DatasetOpenOutcome,
    DatasetOpenWorker,
    ExportWorker,
    FijiBridgeOutcome,
    FijiBridgeWorker,
    PreviewRenderResult,
    PreviewWorker,
)
from .image_dataset import ResolutionLevelInfo
from .ims_reader import IMSReader, IMSReaderError
from .metadata_correction import apply_metadata_correction
from .models import (
    ChannelMetadata,
    ChannelSelection,
    DisplayAdjustmentSettings,
    ExportSettings,
    ImageOutputSettings,
    IMSMetadata,
    MetadataCorrection,
    ScaleBarSettings,
)
from .objective_detector import apply_manual_objective, detect_objective
from .plugins.cell_counting import CellCountingResult, load_cell_counting_plugins
from .settings_store import SettingsStore
from .theme import apply_dark_theme

GITHUB_REPOSITORY_URL = "https://github.com/here-is-song/image_Easy-to-adjust"
AUTO_MERGE_PREVIEW = "auto_merge"


@dataclass
class ChannelControls:
    """Widgets associated with one channel; parsing remains outside the GUI layer."""

    include: QCheckBox
    color_swatch: QPushButton
    minimum: QDoubleSpinBox
    maximum: QDoubleSpinBox
    gamma: QDoubleSpinBox
    minimum_slider: QSlider
    maximum_slider: QSlider
    gamma_slider: QSlider
    color_override: tuple[float, float, float] | None = None
    use_data_minmax: QCheckBox | None = None


@dataclass(frozen=True)
class CachedChannelState:
    """One channel's temporary edits while the application remains open."""

    included: bool
    display_min: float
    display_max: float
    gamma: float
    color_override: tuple[float, float, float] | None
    use_data_minmax: bool | None


@dataclass
class CachedFileState:
    """Editable controls and preview view cached separately for one source file."""

    channels: dict[int, CachedChannelState]
    output_name_groups: tuple[tuple[str, ...], ...]
    preview_selection: object
    z_start: int
    z_end: int
    objective_override: object
    red_to_magenta: bool
    include_scale_bar: bool
    auto_scale: bool
    scale_length: float
    scale_thickness: int
    scale_font_size: int
    preview_pixmap: QPixmap | None
    preview_full_size: tuple[int, int] | None
    preview_resolution_level: ResolutionLevelInfo | None
    preview_available_levels: tuple[ResolutionLevelInfo, ...]
    preview_zoom: float
    output_zoom_factor: float
    preview_rotation_degrees: float
    preview_baked_rotation_degrees: float
    scroll_x: int
    scroll_y: int
    refresh_pending: bool


class IMSFigureExporterWindow(QMainWindow):
    """Main window for opening IMS data, inspecting settings, previewing, and export."""

    def __init__(self, app_settings: QSettings | None = None) -> None:
        super().__init__()
        application = QApplication.instance()
        if application is not None:
            apply_dark_theme(application)
        self.settings_store = SettingsStore(app_settings)
        stored = self.settings_store.load()
        self.metadata: IMSMetadata | None = None
        self.batch_metadata: dict[Path, IMSMetadata] = {}
        self.source_metadata: dict[Path, IMSMetadata] = {}
        self.metadata_corrections: dict[Path, MetadataCorrection] = (
            self.settings_store.load_metadata_corrections()
        )
        self.batch_source_status: dict[Path, str] = {}
        self.channel_controls: dict[int, ChannelControls] = {}
        self.output_image_actions: dict[tuple[int, ...], QAction] = {}
        self.output_selection_name_groups: tuple[tuple[str, ...], ...] | None = None
        self.output_directory = stored.gui.output_directory
        self.last_input_directory = stored.gui.last_input_directory
        self.fiji_directory = self.settings_store.load_fiji_directory()
        if self.fiji_directory is None:
            self.fiji_directory = discover_fiji_installation()
            if self.fiji_directory is not None:
                self.settings_store.save_fiji_directory(self.fiji_directory)
        self.output_width_px = stored.output.width_px or 1000
        self.output_height_px = stored.output.height_px or 1000
        self.output_dpi = stored.output.dpi
        self.output_format = stored.output.format
        self.output_resize_mode = stored.output.resize_mode
        self.copy_to_clipboard = stored.gui.copy_to_clipboard
        self.preview_refresh_interval_ms = stored.gui.preview_refresh_interval_ms
        self.section_expanded = stored.gui.section_expanded
        self.collapsible_sections: dict[str, CollapsibleSection] = {}
        self.last_output_directory: Path | None = None
        self._thread: QThread | None = None
        self._worker: QObject | None = None
        self.preview_pixmap: QPixmap | None = None
        self.preview_zoom = 1.0
        self.output_zoom_factor = 1.0
        self.preview_rotation_degrees = 0.0
        self.preview_baked_rotation_degrees = 0.0
        self.preview_full_size: tuple[int, int] | None = None
        self.preview_resolution_level: ResolutionLevelInfo | None = None
        self.preview_available_levels: tuple[ResolutionLevelInfo, ...] = ()
        self.cell_counting_plugins = load_cell_counting_plugins()
        self.last_cell_count_result: CellCountingResult | None = None
        self._active_path: Path | None = None
        self._file_state_cache: dict[Path, CachedFileState] = {}
        self._restoring_file_state = False
        self._restored_preview_view = False
        self._preview_refresh_pending = False
        self._manual_preview_refresh_pending = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self._run_scheduled_preview)
        self._preview_detail_timer = QTimer(self)
        self._preview_detail_timer.setSingleShot(True)
        self._preview_detail_timer.setInterval(180)
        self._preview_detail_timer.timeout.connect(self._refresh_preview_resolution)
        self._build_ui()

    def _save_export_settings(self) -> None:
        self.settings_store.save_export(
            ImageOutputSettings(
                format=self.output_format,
                width_px=self.output_width_px,
                height_px=self.output_height_px,
                dpi=self.output_dpi,
                resize_mode=self.output_resize_mode,
            ),
            self.output_directory,
            self.copy_to_clipboard,
        )

    def _build_menu_bar(self) -> None:
        """Create a conventional menu structure that can grow with future features."""

        file_menu = self.menuBar().addMenu("&File")
        self.open_action = QAction("Open Microscopy Files…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_ims)
        file_menu.addAction(self.open_action)

        self.edit_metadata_action = QAction("Edit Image Metadata…", self)
        self.edit_metadata_action.setEnabled(False)
        self.edit_metadata_action.triggered.connect(self.edit_image_metadata)
        file_menu.addAction(self.edit_metadata_action)

        self.open_output_action = QAction("Open Output Folder", self)
        self.open_output_action.setEnabled(False)
        self.open_output_action.triggered.connect(self.open_output_folder)
        file_menu.addAction(self.open_output_action)
        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        preview_menu = self.menuBar().addMenu("&Preview")
        self.refresh_preview_action = QAction("Refresh Preview", self)
        self.refresh_preview_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self.refresh_preview_action.setEnabled(False)
        self.refresh_preview_action.triggered.connect(self.update_preview)
        preview_menu.addAction(self.refresh_preview_action)

        self.reset_preview_view_action = QAction("Reset Preview View", self)
        self.reset_preview_view_action.setShortcut(QKeySequence("Ctrl+B"))
        self.reset_preview_view_action.triggered.connect(self.reset_preview_view)
        preview_menu.addAction(self.reset_preview_view_action)

        refresh_limit_menu = preview_menu.addMenu("Refresh Limit")
        self.refresh_limit_group = QActionGroup(self)
        self.refresh_limit_group.setExclusive(True)
        self.refresh_limit_actions: dict[int, QAction] = {}
        for label, interval_ms in (
            ("2 per second", 500),
            ("1 per second", 1000),
            ("Every 2 seconds", 2000),
            ("Every 5 seconds", 5000),
            ("Paused", 0),
        ):
            action = QAction(label, self, checkable=True)
            action.setData(interval_ms)
            action.setChecked(interval_ms == self.preview_refresh_interval_ms)
            action.triggered.connect(self._refresh_limit_action_triggered)
            self.refresh_limit_group.addAction(action)
            refresh_limit_menu.addAction(action)
            self.refresh_limit_actions[interval_ms] = action

        batch_menu = self.menuBar().addMenu("&Batch")
        select_process_all = QAction("Select All for Processing", self)
        select_process_all.triggered.connect(lambda: self._set_batch_column_checked(1, True))
        batch_menu.addAction(select_process_all)
        clear_process = QAction("Clear Processing Selection", self)
        clear_process.triggered.connect(lambda: self._set_batch_column_checked(1, False))
        batch_menu.addAction(clear_process)
        batch_menu.addSeparator()
        select_export_all = QAction("Select All for Export", self)
        select_export_all.triggered.connect(lambda: self._set_batch_column_checked(2, True))
        batch_menu.addAction(select_export_all)
        clear_export = QAction("Clear Export Selection", self)
        clear_export.triggered.connect(lambda: self._set_batch_column_checked(2, False))
        batch_menu.addAction(clear_export)

        self.output_images_menu = PersistentSelectionMenu("&Output Images", self)
        self.menuBar().addMenu(self.output_images_menu)
        self.output_images_menu.setEnabled(False)

        analysis_menu = self.menuBar().addMenu("&Analysis")
        self.cell_count_demo_action = QAction("Cell Counting Plugin Demo…", self)
        self.cell_count_demo_action.setEnabled(False)
        self.cell_count_demo_action.triggered.connect(self.open_cell_counting_demo)
        analysis_menu.addAction(self.cell_count_demo_action)

        self.fiji_menu = analysis_menu.addMenu("Fiji Bridge")
        self.send_to_fiji_action = QAction("Open Selected Data in Fiji…", self)
        self.send_to_fiji_action.setEnabled(False)
        self.send_to_fiji_action.triggered.connect(self.send_to_fiji)
        self.fiji_menu.addAction(self.send_to_fiji_action)
        self.configure_fiji_action = QAction("Configure Fiji Installation…", self)
        self.configure_fiji_action.triggered.connect(self.configure_fiji_installation)
        self.fiji_menu.addAction(self.configure_fiji_action)

        export_menu = self.menuBar().addMenu("&Export")
        self.export_settings_action = QAction("Export Image Settings…", self)
        self.export_settings_action.triggered.connect(self.open_export_settings)
        export_menu.addAction(self.export_settings_action)
        export_menu.addSeparator()
        self.export_action = QAction("Export Images", self)
        self.export_action.setShortcut(QKeySequence("Ctrl+C"))
        self.export_action.setEnabled(False)
        self.export_action.triggered.connect(self.export_tiffs)
        export_menu.addAction(self.export_action)

        help_menu = self.menuBar().addMenu("&Help")
        self.github_action = QAction("Open GitHub Repository", self)
        self.github_action.triggered.connect(self.open_github_repository)
        help_menu.addAction(self.github_action)
        help_menu.addSeparator()
        self.about_action = QAction("About IEA", self)
        self.about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(self.about_action)

    def _build_ui(self) -> None:
        self.setWindowTitle("image_easy-to-adjust (IEA)")
        icon_path = Path(__file__).resolve().parent / "resources" / "IEA.ico"
        if icon_path.exists():
            application_icon = QIcon(str(icon_path))
            self.setWindowIcon(application_icon)
            application = QApplication.instance()
            if application is not None:
                application.setWindowIcon(application_icon)
        self.resize(1200, 780)
        self._build_menu_bar()
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        file_row = QHBoxLayout()
        self.open_button = QPushButton("Open Microscopy Files…")
        self.open_button.clicked.connect(self.open_ims)
        self.file_label = QLabel("No microscopy file selected")
        self.file_label.setWordWrap(True)
        file_row.addWidget(self.open_button)
        file_row.addWidget(self.file_label, 1)
        root.addLayout(file_row)
        self.metadata_label = QLabel("Open an IMS file to view metadata.")
        root.addWidget(self.metadata_label)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(False)
        self.warning_label.setMinimumWidth(0)
        self.warning_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.warning_label.setStyleSheet("color: #F0B44D;")
        self.warning_label.setVisible(False)

        self.content_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        self.content_splitter.setHandleWidth(7)
        root.addWidget(self.content_splitter, 1)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_panel = QWidget()
        self.left_layout = QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(4, 4, 4, 4)
        batch_group = self._create_collapsible_section("batch_files", "Batch Files")
        batch_layout = QVBoxLayout()
        self.batch_tree = QTreeWidget()
        self.batch_tree.setColumnCount(3)
        self.batch_tree.setHeaderLabels(["Microscopy file", "Process", "Export"])
        self.batch_tree.setMinimumHeight(130)
        self.batch_tree.setRootIsDecorated(False)
        self.batch_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.batch_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.batch_tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.batch_tree.itemSelectionChanged.connect(self._batch_selection_changed)
        self.batch_tree.itemChanged.connect(self._batch_item_changed)
        batch_layout.addWidget(self.batch_tree)
        batch_group.set_content_layout(batch_layout)
        self.left_layout.addWidget(batch_group)
        self.channels_group = self._create_collapsible_section("channels", "Channels")
        self.channels_layout = QVBoxLayout()
        self.channel_rows_widget = QWidget()
        self.channel_rows_layout = QVBoxLayout(self.channel_rows_widget)
        self.channel_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.channels_layout.addWidget(self.channel_rows_widget)
        self.red_to_magenta = QCheckBox("Convert red to magenta")
        self.red_to_magenta.setChecked(True)
        self.red_to_magenta.toggled.connect(self._schedule_preview_refresh)
        self.channels_layout.addWidget(self.red_to_magenta)
        self.channels_group.set_content_layout(self.channels_layout)
        self.left_layout.addWidget(self.channels_group)
        self._build_settings_groups()
        self.left_layout.addStretch(1)
        left_scroll.setWidget(left_panel)
        left_scroll.setMinimumWidth(260)
        self.content_splitter.addWidget(left_scroll)

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
        self.reset_rotation_button = QPushButton("0°")
        self.reset_rotation_button.setToolTip("Reset preview rotation")
        self.reset_rotation_button.clicked.connect(self.reset_preview_rotation)
        preview_header.addWidget(self.reset_rotation_button)
        preview_header.addWidget(QLabel("Output size:"))
        self.output_zoom_input = QDoubleSpinBox()
        self.output_zoom_input.setRange(2.0, 1600.0)
        self.output_zoom_input.setDecimals(1)
        self.output_zoom_input.setSingleStep(5.0)
        self.output_zoom_input.setSuffix(" %")
        self.output_zoom_input.setValue(100.0)
        self.output_zoom_input.setToolTip("Image-content size written to Preview and exported images")
        self.output_zoom_input.valueChanged.connect(self._output_zoom_input_changed)
        preview_header.addWidget(self.output_zoom_input)
        preview_header.addWidget(QLabel("Rotation:"))
        self.rotation_input = QDoubleSpinBox()
        self.rotation_input.setRange(-180.0, 180.0)
        self.rotation_input.setDecimals(1)
        self.rotation_input.setSingleStep(1.0)
        self.rotation_input.setSuffix(" °")
        self.rotation_input.setValue(0.0)
        self.rotation_input.setToolTip("Clockwise rotation written to Preview and exported images")
        self.rotation_input.valueChanged.connect(self._rotation_input_changed)
        preview_header.addWidget(self.rotation_input)
        self.zoom_label = QLabel("100%")
        preview_header.addWidget(self.zoom_label)
        preview_header.addStretch(1)
        preview_layout.addLayout(preview_header)
        self.preview_label = InteractivePreviewLabel("Preview will appear here.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(1, 1)
        self.preview_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.preview_label.setToolTip(
            "Mouse wheel: view-only zoom · Left drag: view-only pan · Right drag: output rotation\n"
            "Output size and rotation change exported images."
        )
        self.preview_label.pan_requested.connect(self._pan_preview)
        self.preview_label.rotation_requested.connect(self._rotate_preview)
        self.preview_label.zoom_requested.connect(self._zoom_preview_by_factor)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(False)
        self.preview_scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_scroll.setWidget(self.preview_label)
        preview_layout.addWidget(self.preview_scroll, 1)
        preview_panel.setMinimumWidth(320)
        self.content_splitter.addWidget(preview_panel)
        self.content_splitter.setCollapsible(0, False)
        self.content_splitter.setCollapsible(1, False)
        self.content_splitter.setStretchFactor(0, 0)
        self.content_splitter.setStretchFactor(1, 1)
        self.content_splitter.setSizes([360, 820])
        self.content_splitter.handle(1).setToolTip("Drag left or right to resize the settings and preview areas")
        self.content_splitter.setStyleSheet(
            "QSplitter::handle { background-color: palette(mid); }"
            "QSplitter::handle:hover { background-color: palette(highlight); }"
        )

        root.addWidget(self.warning_label)

        bottom = QHBoxLayout()
        self.status_label = QLabel("Ready")
        bottom.addWidget(self.status_label, 1)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMaximumWidth(220)
        bottom.addWidget(self.progress_bar)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_processing)
        bottom.addWidget(self.cancel_button)
        self.open_folder_button = QPushButton("Open Folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self.open_output_folder)
        bottom.addWidget(self.open_folder_button)
        self.export_button = QPushButton("Export Images")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_tiffs)
        bottom.addWidget(self.export_button)
        root.addLayout(bottom)

    def _create_collapsible_section(self, key: str, title: str) -> CollapsibleSection:
        section = CollapsibleSection(title, self.section_expanded.get(key, True))
        section.expanded_changed.connect(
            lambda expanded, section_key=key: self.settings_store.save_section_expanded(section_key, expanded)
        )
        self.collapsible_sections[key] = section
        return section

    def _build_settings_groups(self) -> None:
        z_group = self._create_collapsible_section("z_range", "Z Range")
        z_form = QFormLayout()
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
        z_group.content_widget.setLayout(z_form)
        self.left_layout.addWidget(z_group)

        objective_group = self._create_collapsible_section("objective", "Objective")
        objective_form = QFormLayout()
        self.objective_combo = QComboBox()
        self.objective_combo.addItem("Auto", None)
        for objective_key in FV1200_OBJECTIVES:
            self.objective_combo.addItem(objective_key, objective_key)
        self.objective_combo.addItem("Unknown", "Unknown")
        self.objective_combo.currentIndexChanged.connect(self._objective_selection_changed)
        self.objective_details = QLabel("Open a file first.")
        self.objective_details.setWordWrap(True)
        objective_form.addRow("Objective:", self.objective_combo)
        objective_form.addRow(self.objective_details)
        objective_group.content_widget.setLayout(objective_form)
        self.left_layout.addWidget(objective_group)

        scale_group = self._create_collapsible_section("scale_bar", "Scale Bar")
        scale_form = QFormLayout()
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
        self.scale_thickness.setValue(10)
        self.scale_thickness.valueChanged.connect(self._schedule_preview_refresh)
        self.scale_font_size = QSpinBox()
        self.scale_font_size.setRange(0, 1000)
        self.scale_font_size.setSpecialValueText("Auto")
        self.scale_font_size.setSuffix(" px")
        self.scale_font_size.setValue(50)
        self.scale_font_size.valueChanged.connect(self._schedule_preview_refresh)
        scale_form.addRow(self.include_scale_bar)
        scale_form.addRow(self.auto_scale)
        scale_form.addRow("Manual length:", self.scale_length)
        scale_form.addRow("Bar thickness:", self.scale_thickness)
        scale_form.addRow("Text size:", self.scale_font_size)
        scale_group.content_widget.setLayout(scale_form)
        self.left_layout.addWidget(scale_group)

    @Slot()
    def open_export_settings(self) -> None:
        default_directory = default_output_directory(self.metadata.source_path) if self.metadata is not None else None
        dialog = ExportImageSettingsDialog(
            self,
            self.output_width_px,
            self.output_height_px,
            self.output_dpi,
            self.copy_to_clipboard,
            self.output_format,
            self.output_resize_mode,
            self.output_directory,
            default_directory,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.output_width_px = dialog.width_spin.value()
        self.output_height_px = dialog.height_spin.value()
        self.output_dpi = dialog.dpi_spin.value()
        self.copy_to_clipboard = dialog.copy_checkbox.isChecked()
        self.output_format = str(dialog.format_combo.currentData())
        self.output_resize_mode = str(dialog.resize_mode_combo.currentData())
        self.output_directory = dialog.selected_output_directory()
        self.last_output_directory = None
        self._save_export_settings()
        self._sync_output_folder_controls()
        clipboard_text = "on" if self.copy_to_clipboard else "off"
        self.status_label.setText(
            f"Export settings: {self.output_width_px} × {self.output_height_px} px, "
            f"{self.output_dpi} DPI, {self.output_format.upper()}, Clipboard {clipboard_text}."
        )
        self._schedule_preview_refresh()

    def _current_output_directory(self) -> Path | None:
        if self.output_directory is not None:
            return self.output_directory
        if self.metadata is not None:
            return default_output_directory(self.metadata.source_path)
        return None

    def _sync_output_folder_controls(self) -> None:
        target = self._current_output_directory()
        can_open = target is not None and target.exists()
        self.open_folder_button.setEnabled(can_open)
        self.open_output_action.setEnabled(can_open)

    @Slot()
    def open_ims(self) -> None:
        initial_directory = (
            str(self.last_input_directory)
            if self.last_input_directory is not None and self.last_input_directory.is_dir()
            else ""
        )
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Open microscopy files",
            initial_directory,
            "Microscopy files (*.ims *.IMS *.oib *.OIB *.tif *.TIF *.tiff *.TIFF);;"
            "IMS files (*.ims *.IMS);;OIB files (*.oib *.OIB);;TIFF files (*.tif *.TIF *.tiff *.TIFF)",
        )
        if not filenames:
            return
        requested_paths = tuple(Path(filename).resolve() for filename in filenames)
        if any(path.suffix.casefold() != ".ims" for path in requested_paths):
            self._run_worker(DatasetOpenWorker(requested_paths), self._dataset_open_finished)
            return
        loaded: dict[Path, IMSMetadata] = {}
        errors: list[str] = []
        for filename in filenames:
            reader = IMSReader(filename)
            try:
                metadata = reader.open()
                loaded[metadata.source_path] = metadata
            except IMSReaderError as exc:
                errors.append(f"{Path(filename).name}: {exc}")
            finally:
                reader.close()
        self._apply_loaded_metadata(
            loaded,
            {path: "IMS opened directly; Auto Display Adjustment skipped." for path in loaded},
            errors,
        )

    def _apply_loaded_metadata(
        self,
        loaded: dict[Path, IMSMetadata],
        source_status: dict[Path, str],
        errors: list[str] | tuple[str, ...],
    ) -> None:
        if not loaded:
            QMessageBox.critical(self, "Unable to open microscopy files", "\n".join(errors))
            return
        original_loaded = dict(loaded)
        loaded = {
            path: apply_metadata_correction(metadata, self.metadata_corrections.get(path.resolve()))
            for path, metadata in loaded.items()
        }
        self.last_input_directory = next(iter(loaded)).parent
        self.settings_store.save_last_input_directory(self.last_input_directory)
        self.batch_metadata = loaded
        self.source_metadata = original_loaded
        self.batch_source_status = source_status
        self.output_selection_name_groups = None
        self.last_output_directory = None
        self.batch_tree.blockSignals(True)
        self.batch_tree.clear()
        for path in loaded:
            item = QTreeWidgetItem([path.name, "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(0, str(path))
            item.setCheckState(1, Qt.CheckState.Checked)
            item.setCheckState(2, Qt.CheckState.Checked)
            self.batch_tree.addTopLevelItem(item)
        first_item = self.batch_tree.topLevelItem(0)
        self.batch_tree.setCurrentItem(first_item)
        self.batch_tree.blockSignals(False)
        self.objective_combo.setCurrentIndex(0)
        first_path = Path(str(first_item.data(0, Qt.ItemDataRole.UserRole)))
        self._activate_metadata(loaded[first_path], first_path)
        if errors:
            QMessageBox.warning(
                self,
                "Some microscopy files were skipped",
                "The following files could not be opened:\n" + "\n".join(errors),
            )

    @Slot(object)
    def _dataset_open_finished(self, outcome: object) -> None:
        if not isinstance(outcome, DatasetOpenOutcome):
            self._worker_failed("The dataset worker returned an unexpected result.")
            return
        loaded = {record.requested_path: record.metadata for record in outcome.records}
        statuses = {
            record.requested_path: " ".join(record.messages) or f"Backend: {record.active_backend}"
            for record in outcome.records
        }
        self._apply_loaded_metadata(loaded, statuses, outcome.errors)

    def _cache_active_file_state(self) -> None:
        """Keep the active file's edits in memory before another file replaces it."""

        if self._active_path is None or self.metadata is None or not self.channel_controls:
            return
        channels = {
            index: CachedChannelState(
                included=controls.include.isChecked(),
                display_min=controls.minimum.value(),
                display_max=controls.maximum.value(),
                gamma=controls.gamma.value(),
                color_override=controls.color_override,
                use_data_minmax=(
                    controls.use_data_minmax.isChecked()
                    if controls.use_data_minmax is not None
                    else None
                ),
            )
            for index, controls in self.channel_controls.items()
        }
        pixmap = (
            self.preview_pixmap.copy()
            if self.preview_pixmap is not None and not self.preview_pixmap.isNull()
            else None
        )
        self._file_state_cache[self._active_path] = CachedFileState(
            channels=channels,
            output_name_groups=self._checked_output_name_groups(),
            preview_selection=self.preview_combo.currentData(),
            z_start=self.z_start.value(),
            z_end=self.z_end.value(),
            objective_override=self.objective_combo.currentData(),
            red_to_magenta=self.red_to_magenta.isChecked(),
            include_scale_bar=self.include_scale_bar.isChecked(),
            auto_scale=self.auto_scale.isChecked(),
            scale_length=self.scale_length.value(),
            scale_thickness=self.scale_thickness.value(),
            scale_font_size=self.scale_font_size.value(),
            preview_pixmap=pixmap,
            preview_full_size=self.preview_full_size,
            preview_resolution_level=self.preview_resolution_level,
            preview_available_levels=self.preview_available_levels,
            preview_zoom=self.preview_zoom,
            output_zoom_factor=self.output_zoom_factor,
            preview_rotation_degrees=self.preview_rotation_degrees,
            preview_baked_rotation_degrees=self.preview_baked_rotation_degrees,
            scroll_x=self.preview_scroll.horizontalScrollBar().value(),
            scroll_y=self.preview_scroll.verticalScrollBar().value(),
            refresh_pending=self._preview_refresh_pending,
        )

    def _restore_cached_controls(self, state: CachedFileState) -> None:
        for index, channel_state in state.channels.items():
            controls = self.channel_controls.get(index)
            if controls is None:
                continue
            controls.include.setChecked(channel_state.included)
            controls.minimum.setValue(channel_state.display_min)
            controls.maximum.setValue(channel_state.display_max)
            controls.gamma.setValue(channel_state.gamma)
            controls.color_override = channel_state.color_override
            source_color = self.metadata.channels[index].color if self.metadata is not None else (1.0, 1.0, 1.0)
            self._set_color_swatch(controls.color_swatch, channel_state.color_override or source_color)
            if controls.use_data_minmax is not None and channel_state.use_data_minmax is not None:
                controls.use_data_minmax.setChecked(channel_state.use_data_minmax)
        self._sync_output_action_availability()
        self._refresh_output_color_labels()

    def _restore_preview_selection(self, selection: object) -> None:
        index = next(
            (
                position
                for position in range(self.preview_combo.count())
                if self.preview_combo.itemData(position) == selection
            ),
            -1,
        )
        if index >= 0:
            self.preview_combo.setCurrentIndex(index)

    def _restore_cached_scroll(self, path: Path, x: int, y: int) -> None:
        if self._active_path != path:
            return
        self.preview_scroll.horizontalScrollBar().setValue(x)
        self.preview_scroll.verticalScrollBar().setValue(y)

    def _activate_metadata(
        self,
        metadata: IMSMetadata,
        requested_path: Path | None = None,
        *,
        invalidate_cached_preview: bool = False,
    ) -> None:
        self._cache_active_file_state()
        self._preview_timer.stop()
        self._preview_detail_timer.stop()
        self._manual_preview_refresh_pending = False
        active_path = requested_path or metadata.source_path
        cache_key = active_path.resolve()
        state = self._file_state_cache.get(cache_key)
        if state is not None and invalidate_cached_preview:
            state.preview_pixmap = None
            state.preview_resolution_level = None
            state.preview_available_levels = ()
        self._active_path = cache_key
        self.metadata = metadata
        self._restoring_file_state = True
        self.preview_pixmap = None
        self.preview_full_size = self._preview_base_size()
        self.preview_resolution_level = None
        self.preview_available_levels = ()
        self.preview_zoom = 1.0
        self.output_zoom_factor = 1.0
        self.preview_rotation_degrees = 0.0
        self.preview_baked_rotation_degrees = 0.0
        self._restored_preview_view = state is not None
        self.preview_label.clear()
        self.preview_label.setText("Loading preview…")
        self.file_label.setText(str(active_path))
        voxel_text = " x ".join(
            f"{value:.6g}" if value is not None else "N/A"
            for value in (
                metadata.voxel_size_x_um,
                metadata.voxel_size_y_um,
                metadata.voxel_size_z_um,
            )
        )
        self.metadata_label.setText(
            f"{metadata.size_x} x {metadata.size_y} x {metadata.size_z} | "
            f"{metadata.channel_count} channels | "
            f"{voxel_text} um"
            + (
                " | Manual physical calibration"
                if (
                    self.metadata_corrections.get(active_path.resolve()) is not None
                    and not self.metadata_corrections[active_path.resolve()].is_empty
                )
                else ""
            )
        )
        self._update_warning_display(metadata.warnings)
        self._sync_output_folder_controls()
        if state is not None:
            self.output_selection_name_groups = state.output_name_groups
        self._populate_channels(metadata)
        self.z_start.setRange(1, metadata.size_z)
        self.z_end.setRange(1, metadata.size_z)
        self.z_end.setValue(min(metadata.size_z, state.z_end) if state is not None else metadata.size_z)
        self.z_start.setValue(min(self.z_end.value(), state.z_start) if state is not None else 1)
        if state is not None:
            self._restore_cached_controls(state)
            self.red_to_magenta.setChecked(state.red_to_magenta)
            self.include_scale_bar.setChecked(state.include_scale_bar)
            self.auto_scale.setChecked(state.auto_scale)
            self.scale_length.setValue(state.scale_length)
            self.scale_thickness.setValue(state.scale_thickness)
            self.scale_font_size.setValue(state.scale_font_size)
            objective_index = self.objective_combo.findData(state.objective_override)
            self.objective_combo.setCurrentIndex(max(0, objective_index))
            self._restore_preview_selection(state.preview_selection)
        self._toggle_scale_controls(self.include_scale_bar.isChecked())
        self._toggle_scale_length(self.auto_scale.isChecked())
        self._update_z_info()
        self._update_objective_display()
        self._update_export_enabled()
        self.refresh_preview_action.setEnabled(True)
        self.cell_count_demo_action.setEnabled(True)
        self.send_to_fiji_action.setEnabled(True)
        self.edit_metadata_action.setEnabled(True)
        source_status = self.batch_source_status.get(active_path)
        status_suffix = f" {source_status}" if source_status else ""
        self.status_label.setText(
            f"{len(self.batch_metadata)} microscopy file(s) loaded. Active: {active_path.name}.{status_suffix}"
        )
        self._preview_refresh_pending = state.refresh_pending if state is not None else False
        if state is not None:
            self.preview_full_size = state.preview_full_size
            self.preview_resolution_level = state.preview_resolution_level
            self.preview_available_levels = state.preview_available_levels
            self.preview_zoom = state.preview_zoom
            self.output_zoom_factor = state.output_zoom_factor
            self.preview_rotation_degrees = state.preview_rotation_degrees
            self.preview_baked_rotation_degrees = state.preview_baked_rotation_degrees
        self._sync_transform_inputs()
        if state is not None and state.preview_pixmap is not None and not state.preview_pixmap.isNull():
            self.preview_pixmap = state.preview_pixmap.copy()
            self._render_preview_pixmap()
            QTimer.singleShot(
                0,
                lambda path=cache_key, x=state.scroll_x, y=state.scroll_y: self._restore_cached_scroll(
                    path, x, y
                ),
            )
            self.status_label.setText(f"Restored temporary edits and preview for {active_path.name}.")
        self._restoring_file_state = False
        if self.preview_pixmap is None:
            self.update_preview()
        elif self._preview_refresh_pending and self.preview_refresh_interval_ms > 0:
            self._preview_timer.start(self.preview_refresh_interval_ms)

    @Slot()
    def edit_image_metadata(self) -> None:
        active_path = self._active_source_path()
        if active_path is None or self.metadata is None:
            return
        resolved_path = active_path.resolve()
        source = self.source_metadata.get(active_path) or self.source_metadata.get(resolved_path) or self.metadata
        dialog = MetadataCorrectionDialog(
            self,
            source,
            self.metadata_corrections.get(resolved_path),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        correction = dialog.correction()
        if correction.is_empty:
            self.metadata_corrections.pop(resolved_path, None)
            status = "Source physical metadata restored."
        else:
            self.metadata_corrections[resolved_path] = correction
            status = "Manual physical metadata correction applied."
        self.settings_store.save_metadata_corrections(self.metadata_corrections)
        effective = apply_metadata_correction(source, None if correction.is_empty else correction)
        self.batch_metadata[active_path] = effective
        self._activate_metadata(effective, active_path, invalidate_cached_preview=True)
        self.status_label.setText(f"{status} Original microscopy file was not modified.")

    @Slot()
    def _batch_selection_changed(self) -> None:
        selected = self.batch_tree.selectedItems()
        if not selected:
            return
        path = Path(str(selected[0].data(0, Qt.ItemDataRole.UserRole)))
        metadata = self.batch_metadata.get(path)
        if metadata is not None and path.resolve() != self._active_path:
            self._activate_metadata(metadata, path)

    @Slot(QTreeWidgetItem, int)
    def _batch_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        self.batch_tree.blockSignals(True)
        if column == 1 and item.checkState(1) == Qt.CheckState.Unchecked:
            item.setCheckState(2, Qt.CheckState.Unchecked)
        elif column == 2 and item.checkState(2) == Qt.CheckState.Checked:
            item.setCheckState(1, Qt.CheckState.Checked)
        self.batch_tree.blockSignals(False)
        self._update_export_enabled()

    def _set_batch_column_checked(self, column: int, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.batch_tree.blockSignals(True)
        for index in range(self.batch_tree.topLevelItemCount()):
            item = self.batch_tree.topLevelItem(index)
            item.setCheckState(column, state)
            if column == 1 and not checked:
                item.setCheckState(2, Qt.CheckState.Unchecked)
            elif column == 2 and checked:
                item.setCheckState(1, Qt.CheckState.Checked)
        self.batch_tree.blockSignals(False)
        self._update_export_enabled()

    def _selected_export_paths(self) -> tuple[Path, ...]:
        paths: list[Path] = []
        for index in range(self.batch_tree.topLevelItemCount()):
            item = self.batch_tree.topLevelItem(index)
            if item.checkState(1) == Qt.CheckState.Checked and item.checkState(2) == Qt.CheckState.Checked:
                paths.append(Path(str(item.data(0, Qt.ItemDataRole.UserRole))))
        return tuple(paths)

    def _update_export_enabled(self) -> None:
        enabled = bool(self._selected_export_paths()) and self._thread is None
        self.export_button.setEnabled(enabled)
        self.export_action.setEnabled(enabled)

    def _populate_channels(self, metadata: IMSMetadata) -> None:
        while self.channel_rows_layout.count():
            item = self.channel_rows_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.channel_controls.clear()
        for channel in metadata.channels:
            row = QFrame()
            row.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QGridLayout(row)
            include = QCheckBox(channel.name)
            include.setChecked(True)
            swatch = QPushButton()
            swatch.setFixedSize(22, 22)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setAccessibleName(f"Change RGB color for {channel.name}")
            self._set_color_swatch(swatch, channel.color)
            swatch.clicked.connect(
                lambda _checked=False, channel_index=channel.index: self._choose_channel_color(channel_index)
            )
            minimum = self._range_spinbox(channel.display_min, 0.0)
            maximum = self._range_spinbox(channel.display_max, 1.0)
            gamma = self._gamma_spinbox(channel.display_gamma)
            slider_minimum, slider_maximum = self._range_slider_bounds(channel.display_min, channel.display_max)
            minimum_slider = self._parameter_slider()
            maximum_slider = self._parameter_slider()
            gamma_slider = self._parameter_slider()
            self._bind_spinbox_and_slider(minimum, minimum_slider, slider_minimum, slider_maximum)
            self._bind_spinbox_and_slider(maximum, maximum_slider, slider_minimum, slider_maximum)
            self._bind_spinbox_and_slider(gamma, gamma_slider, 0.1, 5.0)
            include.toggled.connect(self._schedule_preview_refresh)
            include.toggled.connect(self._sync_output_action_availability)
            minimum.valueChanged.connect(self._schedule_preview_refresh)
            maximum.valueChanged.connect(self._schedule_preview_refresh)
            gamma.valueChanged.connect(self._schedule_preview_refresh)
            use_data_minmax: QCheckBox | None = None
            range_source = "IMS Min/Max" if channel.display_range_source == "ims" else "Data min/max fallback"
            gamma_source = "IMS Gamma" if channel.display_gamma_source == "ims" else "Default Gamma"
            source = f"{range_source}; {gamma_source}"
            layout.addWidget(include, 0, 0, 1, 2)
            layout.addWidget(swatch, 0, 2)
            layout.addWidget(QLabel("Min"), 1, 0)
            layout.addWidget(minimum, 1, 1)
            layout.addWidget(minimum_slider, 1, 2)
            layout.addWidget(QLabel("Max"), 2, 0)
            layout.addWidget(maximum, 2, 1)
            layout.addWidget(maximum_slider, 2, 2)
            layout.addWidget(QLabel("Gamma"), 3, 0)
            layout.addWidget(gamma, 3, 1)
            layout.addWidget(gamma_slider, 3, 2)
            layout.addWidget(QLabel(source), 4, 0, 1, 3)
            if channel.display_range_source != "ims":
                use_data_minmax = QCheckBox("Use selected data min/max")
                use_data_minmax.setChecked(True)
                minimum.setEnabled(False)
                maximum.setEnabled(False)
                minimum_slider.setEnabled(False)
                maximum_slider.setEnabled(False)
                use_data_minmax.toggled.connect(minimum.setDisabled)
                use_data_minmax.toggled.connect(maximum.setDisabled)
                use_data_minmax.toggled.connect(minimum_slider.setDisabled)
                use_data_minmax.toggled.connect(maximum_slider.setDisabled)
                use_data_minmax.toggled.connect(self._schedule_preview_refresh)
                layout.addWidget(use_data_minmax, 5, 0, 1, 3)
            self.channel_rows_layout.addWidget(row)
            self.channel_controls[channel.index] = ChannelControls(
                include=include,
                color_swatch=swatch,
                minimum=minimum,
                maximum=maximum,
                gamma=gamma,
                minimum_slider=minimum_slider,
                maximum_slider=maximum_slider,
                gamma_slider=gamma_slider,
                use_data_minmax=use_data_minmax,
            )
        self._populate_output_images_menu(metadata)
        self._populate_preview_choices()

    def _update_warning_display(self, warnings: tuple[str, ...]) -> None:
        warning_text = "    ".join(" ".join(warning.splitlines()) for warning in warnings)
        self.warning_label.setText(warning_text)
        self.warning_label.setToolTip(warning_text)
        self.warning_label.setVisible(bool(warning_text))

    @staticmethod
    def _range_spinbox(value: float | None, fallback: float) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(4)
        spinbox.setRange(-1_000_000_000_000.0, 1_000_000_000_000.0)
        spinbox.setValue(value if value is not None else fallback)
        return spinbox

    @staticmethod
    def _gamma_spinbox(value: float) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setDecimals(3)
        spinbox.setRange(0.1, 5.0)
        spinbox.setSingleStep(0.05)
        spinbox.setValue(value)
        return spinbox

    @staticmethod
    def _set_color_swatch(swatch: QPushButton, color: tuple[float, float, float]) -> None:
        rgb = tuple(round(min(max(component, 0.0), 1.0) * 255) for component in color)
        swatch.setStyleSheet(
            f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]}); "
            "border: 1px solid #8A8A8A; border-radius: 3px;"
        )
        swatch.setToolTip(f"Click to change RGB color (R {rgb[0]}, G {rgb[1]}, B {rgb[2]})")

    @Slot(int)
    def _choose_channel_color(self, channel_index: int) -> None:
        if self.metadata is None or channel_index not in self.channel_controls:
            return
        channel = self.metadata.channels[channel_index]
        controls = self.channel_controls[channel_index]
        current = controls.color_override or channel.color
        selected = QColorDialog.getColor(
            QColor.fromRgbF(*current),
            self,
            f"Select RGB Color — {channel.name}",
        )
        if not selected.isValid():
            return
        controls.color_override = (selected.redF(), selected.greenF(), selected.blueF())
        self._set_color_swatch(controls.color_swatch, controls.color_override)
        self._refresh_output_color_labels()
        self.status_label.setText(
            f"Channel color updated: {channel.name} → "
            f"RGB({selected.red()}, {selected.green()}, {selected.blue()})."
        )
        self._schedule_preview_refresh()

    def _populate_output_images_menu(self, metadata: IMSMetadata) -> None:
        """Build checkable single-, two-, and three-color export choices."""

        self.output_images_menu.clear()
        self.output_image_actions.clear()

        clear_action = self.output_images_menu.addAction("Clear All Selections")
        clear_action.triggered.connect(lambda: self._set_all_output_actions(False))
        select_all_action = self.output_images_menu.addAction("Select All Listed Outputs")
        select_all_action.triggered.connect(lambda: self._set_all_output_actions(True))
        self.output_images_menu.addSeparator()

        channel_indices = tuple(channel.index for channel in metadata.channels)
        channel_names = {channel.index: self._channel_menu_label(channel) for channel in metadata.channels}
        raw_channel_names = {channel.index: channel.name for channel in metadata.channels}
        requested_groups = (
            {frozenset(name.casefold() for name in group) for group in self.output_selection_name_groups}
            if self.output_selection_name_groups is not None
            else None
        )
        categories = (
            ("Three-color Merge", 3),
            ("Two-color Merge", 2),
            ("Single-color", 1),
        )
        for title, group_size in categories:
            submenu = self.output_images_menu.add_persistent_menu(title)
            groups = tuple(combinations(channel_indices, group_size))
            submenu.setEnabled(bool(groups))
            for group in groups:
                label = " + ".join(channel_names[index] for index in group)
                action = QAction(label, self, checkable=True)
                # Preserve the former default: every single channel plus one merge
                # containing all channels when the file has two or three channels.
                default_checked = group_size == 1 or (
                    group_size == len(channel_indices) and group_size > 1
                )
                group_name_key = frozenset(raw_channel_names[index].casefold() for index in group)
                action.setChecked(
                    default_checked if requested_groups is None else group_name_key in requested_groups
                )
                action.toggled.connect(self._output_selection_changed)
                submenu.addAction(action)
                self.output_image_actions[group] = action

        if len(channel_indices) > 3:
            multi_menu = self.output_images_menu.add_persistent_menu("Four-or-more-color Merge")
            action = QAction(" + ".join(channel_names[index] for index in channel_indices), self, checkable=True)
            group_name_key = frozenset(raw_channel_names[index].casefold() for index in channel_indices)
            action.setChecked(True if requested_groups is None else group_name_key in requested_groups)
            action.toggled.connect(self._output_selection_changed)
            multi_menu.addAction(action)
            self.output_image_actions[channel_indices] = action

        self.output_images_menu.setEnabled(bool(channel_indices))
        self._sync_output_action_availability()
        if self.output_selection_name_groups is None:
            self.output_selection_name_groups = self._checked_output_name_groups()

    @staticmethod
    def _channel_menu_label(channel: ChannelMetadata) -> str:
        return IMSFigureExporterWindow._channel_menu_label_for_color(channel.name, channel.color)

    @staticmethod
    def _channel_menu_label_for_color(name: str, color: tuple[float, float, float]) -> str:
        red, green, blue = color
        maximum = max(red, green, blue)
        if maximum <= 0:
            color_name = "Gray"
        else:
            active = tuple(component >= maximum * 0.6 for component in (red, green, blue))
            color_name = {
                (True, False, False): "Red",
                (False, True, False): "Green",
                (False, False, True): "Blue",
                (True, True, False): "Yellow",
                (False, True, True): "Cyan",
                (True, False, True): "Magenta",
                (True, True, True): "White",
            }.get(active, "Mixed")
        return f"[{color_name}] {name}"

    def _refresh_output_color_labels(self) -> None:
        if self.metadata is None:
            return
        channels = {channel.index: channel for channel in self.metadata.channels}
        for group, action in self.output_image_actions.items():
            labels: list[str] = []
            for index in group:
                channel = channels[index]
                controls = self.channel_controls[index]
                color = controls.color_override or channel.color
                labels.append(self._channel_menu_label_for_color(channel.name, color))
            action.setText(" + ".join(labels))

    def _set_all_output_actions(self, checked: bool) -> None:
        for action in self.output_image_actions.values():
            if action.isEnabled():
                action.blockSignals(True)
                action.setChecked(checked)
                action.blockSignals(False)
        self._output_selection_changed()

    def _selected_output_groups(self) -> tuple[tuple[int, ...], ...]:
        enabled_channels = {
            index for index, controls in self.channel_controls.items() if controls.include.isChecked()
        }
        return tuple(
            group
            for group, action in self.output_image_actions.items()
            if action.isChecked() and set(group).issubset(enabled_channels)
        )

    def _checked_output_name_groups(self) -> tuple[tuple[str, ...], ...]:
        if self.metadata is None:
            return ()
        channel_names = {channel.index: channel.name for channel in self.metadata.channels}
        return tuple(
            tuple(channel_names[index] for index in group)
            for group, action in self.output_image_actions.items()
            if action.isChecked()
        )

    @Slot()
    def _sync_output_action_availability(self) -> None:
        enabled_channels = {
            index for index, controls in self.channel_controls.items() if controls.include.isChecked()
        }
        for group, action in self.output_image_actions.items():
            action.setEnabled(set(group).issubset(enabled_channels))
        self._populate_preview_choices()

    @Slot()
    def _output_selection_changed(self) -> None:
        self.output_selection_name_groups = self._checked_output_name_groups()
        self._populate_preview_choices()
        selected_count = len(self._selected_output_groups())
        self.status_label.setText(f"Output image selection updated: {selected_count} image(s) per IMS file.")
        self._schedule_preview_refresh()

    @staticmethod
    def _parameter_slider() -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 10_000)
        slider.setMinimumWidth(120)
        return slider

    @staticmethod
    def _range_slider_bounds(display_min: float | None, display_max: float | None) -> tuple[float, float]:
        minimum = display_min if display_min is not None else 0.0
        maximum = display_max if display_max is not None else max(minimum + 1.0, 1.0)
        span = max(maximum - minimum, 1.0)
        lower = min(0.0, minimum - span * 0.1)
        upper = max(maximum + span * 0.1, lower + 1.0)
        return lower, upper

    @staticmethod
    def _bind_spinbox_and_slider(
        spinbox: QDoubleSpinBox,
        slider: QSlider,
        lower: float,
        upper: float,
    ) -> None:
        steps = slider.maximum() - slider.minimum()

        def update_spinbox(position: int) -> None:
            fraction = (position - slider.minimum()) / steps
            spinbox.setValue(lower + fraction * (upper - lower))

        def update_slider(value: float) -> None:
            fraction = (value - lower) / (upper - lower)
            position = round(slider.minimum() + min(max(fraction, 0.0), 1.0) * steps)
            slider.blockSignals(True)
            slider.setValue(position)
            slider.blockSignals(False)

        slider.valueChanged.connect(update_spinbox)
        spinbox.valueChanged.connect(update_slider)
        update_slider(spinbox.value())

    def _populate_preview_choices(self) -> None:
        current = self.preview_combo.currentData()
        self.preview_combo.blockSignals(True)
        self.preview_combo.clear()
        if self.metadata is not None:
            channel_names = {channel.index: channel.name for channel in self.metadata.channels}
            enabled_channels = tuple(
                channel.index
                for channel in self.metadata.channels
                if self.channel_controls[channel.index].include.isChecked()
            )
            if enabled_channels:
                selected_label = " + ".join(channel_names[index] for index in enabled_channels)
                self.preview_combo.addItem(
                    f"Merge: Selected Channels — {selected_label}",
                    AUTO_MERGE_PREVIEW,
                )
            for group in self._selected_output_groups():
                if len(group) > 1 and group != enabled_channels:
                    label = " + ".join(channel_names[index] for index in group)
                    self.preview_combo.addItem(f"Merge: {label}", group)
            for channel in self.metadata.channels:
                if channel.index in enabled_channels:
                    self.preview_combo.addItem(f"Color: {channel.name}", (channel.index,))
        index = next(
            (
                position
                for position in range(self.preview_combo.count())
                if self.preview_combo.itemData(position) == current
            ),
            -1,
        )
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
        if voxel is None:
            self.z_info.setText(
                f"Start: slice {start}\n"
                f"End: slice {end}\n"
                "Physical Z spacing: N/A"
            )
            return
        thickness = (end - start + 1) * voxel
        origin_z = self.metadata.origin_z_um or 0.0
        self.z_info.setText(
            f"Start: slice {start} ({origin_z + (start - 1) * voxel:.4g} um)\n"
            f"End: slice {end} ({origin_z + (end - 1) * voxel:.4g} um)\n"
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

    @Slot()
    def _objective_selection_changed(self) -> None:
        self._update_objective_display()

    def _update_objective_display(self) -> None:
        if self.metadata is None:
            self.objective_details.setText("Open a file first.")
            return
        detected = self.metadata.objective_detection or detect_objective(self.metadata)
        override = self.objective_combo.currentData()
        selected = apply_manual_objective(detected, str(override) if override is not None else None)

        detected_text = (
            f"{detected.objective_key} — {detected.model}" if detected.objective_key is not None else "Unknown"
        )
        selected_text = (
            f"{selected.objective_key} — {selected.model}" if selected.objective_key is not None else "Unknown"
        )
        z_spacing = f"{selected.measured_z_spacing_um:.6g} µm" if selected.measured_z_spacing_um is not None else "N/A"
        if selected.measured_fov_x_um is not None or selected.measured_fov_y_um is not None:
            fov_x = f"{selected.measured_fov_x_um:.6g}" if selected.measured_fov_x_um is not None else "N/A"
            fov_y = f"{selected.measured_fov_y_um:.6g}" if selected.measured_fov_y_um is not None else "N/A"
            zoom = f"{selected.scan_zoom:.6g}" if selected.scan_zoom is not None else "N/A"
            fov_text = f"{fov_x} × {fov_y} µm · ScanZoom {zoom}"
            if selected.normalized_fov_um is not None:
                fov_text += f" · normalized {selected.normalized_fov_um:.6g} µm"
        else:
            fov_text = "N/A"
        na = f"{selected.na:.2f}" if selected.na is not None else "N/A"
        immersion = selected.immersion or "N/A"
        warning = f"\nWarning: {selected.warning}" if selected.warning else ""
        detection_text = (
            "Manual selection"
            if selected.detection_source == "Manual"
            else f"{selected.detection_source} · {selected.confidence} confidence"
        )
        self.objective_details.setText(
            f"Detected: {detected_text}\n"
            f"Selected: {selected_text}\n"
            f"NA: {na} · Immersion: {immersion}\n"
            f"Z spacing: {z_spacing}\n"
            f"XY FOV: {fov_text}\n"
            f"Detection: {detection_text}{warning}"
        )

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
        adjustments = self._display_adjustments()
        for index in channels:
            display_range = adjustments[index].display_range
            if display_range is not None and display_range[1] <= display_range[0]:
                message = f"Channel {index}: Max must be greater than Min."
                if show_warnings:
                    QMessageBox.warning(self, "Invalid display range", message)
                else:
                    self.status_label.setText(message)
                return None
        output_groups = self._selected_output_groups()
        single_indices = tuple(group[0] for group in output_groups if len(group) == 1)
        merge_groups = tuple(group for group in output_groups if len(group) > 1)
        return ExportSettings(
            z_start=self.z_start.value(),
            z_end=self.z_end.value(),
            channel_indices=channels,
            single_channel_indices=single_indices,
            merge_channel_indices=merge_groups[0] if merge_groups else (),
            merge_channel_groups=merge_groups,
            objective_override=(
                str(self.objective_combo.currentData()) if self.objective_combo.currentData() is not None else None
            ),
            red_to_magenta=self.red_to_magenta.isChecked(),
            scale_bar=ScaleBarSettings(
                enabled=self.include_scale_bar.isChecked(),
                length_um=(None if self.auto_scale.isChecked() else self.scale_length.value()),
                thickness_px=(None if self.scale_thickness.value() == 0 else self.scale_thickness.value()),
                font_size_px=(None if self.scale_font_size.value() == 0 else self.scale_font_size.value()),
            ),
            output=ImageOutputSettings(
                format=self.output_format,
                width_px=self.output_width_px,
                height_px=self.output_height_px,
                dpi=self.output_dpi,
                resize_mode=self.output_resize_mode,
            ),
            zoom_factor=self.output_zoom_factor,
            rotation_degrees=self._preview_total_rotation(),
        )

    def _display_adjustments(self) -> dict[int, DisplayAdjustmentSettings]:
        adjustments: dict[int, DisplayAdjustmentSettings] = {}
        for index, controls in self.channel_controls.items():
            use_fallback = controls.use_data_minmax is not None and controls.use_data_minmax.isChecked()
            adjustments[index] = DisplayAdjustmentSettings(
                display_min=None if use_fallback else controls.minimum.value(),
                display_max=None if use_fallback else controls.maximum.value(),
                gamma=controls.gamma.value(),
                color=controls.color_override,
            )
        return adjustments

    def _channel_selections(self) -> tuple[ChannelSelection, ...]:
        if self.metadata is None:
            return ()
        display_adjustments = self._display_adjustments()
        settings = self._current_settings(show_warnings=False)
        single_indices = set(settings.resolved_single_channel_indices) if settings is not None else set()
        merge_indices = (
            {index for group in settings.resolved_merge_channel_groups for index in group}
            if settings is not None
            else set()
        )
        selections: list[ChannelSelection] = []
        for channel in self.metadata.channels:
            controls = self.channel_controls[channel.index]
            if not controls.include.isChecked():
                continue
            display_adjustment = display_adjustments[channel.index]
            selections.append(
                ChannelSelection(
                    index=channel.index,
                    name=channel.name,
                    display_min=display_adjustment.display_min,
                    display_max=display_adjustment.display_max,
                    gamma=display_adjustment.gamma,
                    color=display_adjustment.color,
                    export_single=channel.index in single_indices,
                    include_in_merge=channel.index in merge_indices,
                )
            )
        return tuple(selections)

    @Slot()
    def update_preview(self) -> None:
        self._preview_timer.stop()
        self._preview_refresh_pending = False
        if self._thread is not None:
            self._preview_refresh_pending = True
            self._manual_preview_refresh_pending = True
            self.status_label.setText("Manual preview refresh queued…")
            return
        self._manual_preview_refresh_pending = False
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
        if selected_preview is None:
            return
        if selected_preview == AUTO_MERGE_PREVIEW:
            preview_selection: int | tuple[int, ...] = settings.channel_indices
        elif isinstance(selected_preview, (tuple, list)):
            preview_selection = tuple(int(index) for index in selected_preview)
        else:
            preview_selection = (int(selected_preview),)
        if not set(preview_selection).issubset(settings.channel_indices):
            message = "Select all channels in this preview before displaying it."
            if show_warnings:
                QMessageBox.warning(self, "Channels not selected", message)
            else:
                self.status_label.setText(message)
            return
        if self.preview_pixmap is None and not self._restored_preview_view:
            self._set_initial_preview_zoom()
        target_width, target_height = self._preview_target_size()
        active_path = self._active_source_path() or self.metadata.source_path
        worker = PreviewWorker(
            active_path,
            settings,
            self._display_adjustments(),
            preview_selection,
            target_width,
            target_height,
            self.metadata_corrections.get(active_path.resolve()),
            self._preview_total_rotation(),
            self.output_zoom_factor,
        )
        self._run_worker(worker, self._preview_finished)

    def _schedule_preview_refresh(self, *_: object) -> None:
        if self.metadata is None or self._restoring_file_state:
            return
        self._preview_refresh_pending = True
        if self.preview_refresh_interval_ms == 0:
            self._preview_timer.stop()
            self.status_label.setText("Automatic preview refresh paused; use Refresh Preview to update.")
            return
        self._preview_timer.start(self.preview_refresh_interval_ms)
        self.status_label.setText("Preview update scheduled…")

    @Slot()
    def _run_scheduled_preview(self) -> None:
        if not self._preview_refresh_pending:
            return
        if self._thread is not None:
            return
        self._preview_refresh_pending = False
        self._start_preview(show_warnings=False)

    def _refresh_limit_action_triggered(self, *_: object) -> None:
        action = self.refresh_limit_group.checkedAction()
        if action is None:
            return
        self.preview_refresh_interval_ms = int(action.data())
        self.settings_store.save_refresh_interval(self.preview_refresh_interval_ms)
        if self.preview_refresh_interval_ms == 0:
            self._preview_timer.stop()
        elif self._preview_refresh_pending:
            self._preview_timer.start(self.preview_refresh_interval_ms)
        self.status_label.setText(f"Preview refresh limit: {action.text()}.")

    @Slot()
    def export_tiffs(self) -> None:
        settings = self._current_settings()
        if settings is None or self.metadata is None:
            return
        if not settings.required_output_channel_indices:
            QMessageBox.warning(
                self,
                "No image outputs selected",
                "Choose at least one item from the Output Images menu.",
            )
            return
        source_paths = self._selected_export_paths()
        if not source_paths:
            QMessageBox.warning(self, "No files selected", "Select at least one batch file for export.")
            return
        worker = ExportWorker(
            source_paths,
            settings,
            self._channel_selections(),
            self.output_directory,
            self.metadata_corrections,
        )
        self._run_worker(worker, self._export_finished)

    @Slot()
    def open_cell_counting_demo(self) -> None:
        if self.metadata is None:
            return
        dialog = CellCountingDemoDialog(
            self,
            self.metadata,
            self.cell_counting_plugins,
            self.z_start.value(),
            self.z_end.value(),
            self.preview_pixmap,
            self._preview_base_size(),
            self.output_resize_mode,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        worker = CellCountWorker(
            self.metadata.source_path,
            dialog.request(),
            dialog.selected_plugin(),
        )
        self._run_worker(worker, self._cell_count_finished)

    def _active_source_path(self) -> Path | None:
        selected = self.batch_tree.selectedItems()
        if selected:
            return Path(str(selected[0].data(0, Qt.ItemDataRole.UserRole)))
        return self.metadata.source_path if self.metadata is not None else None

    @Slot()
    def configure_fiji_installation(self) -> bool:
        initial = str(self.fiji_directory or self.last_input_directory or Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select the Fiji.app folder",
            initial,
        )
        if not selected:
            return False
        directory = Path(selected).resolve()
        try:
            resolve_fiji_executable(directory)
        except FijiBridgeError as exc:
            QMessageBox.warning(self, "Invalid Fiji installation", str(exc))
            return False
        self.fiji_directory = directory
        self.settings_store.save_fiji_directory(directory)
        self.status_label.setText(f"Fiji installation: {directory}")
        return True

    @Slot()
    def send_to_fiji(self) -> None:
        settings = self._current_settings()
        source_path = self._active_source_path()
        if settings is None or source_path is None:
            return
        if self.fiji_directory is None:
            if not self.configure_fiji_installation():
                return
        try:
            resolve_fiji_executable(self.fiji_directory)
        except FijiBridgeError:
            if not self.configure_fiji_installation():
                return
        worker = FijiBridgeWorker(
            source_path,
            self.fiji_directory,
            settings.channel_indices,
            settings.z_start,
            settings.z_end,
            self.metadata_corrections.get(source_path.resolve()),
        )
        self._run_worker(worker, self._fiji_bridge_finished)

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
        if isinstance(worker, ExportWorker):
            worker.progress.connect(self._export_progress)
            self.progress_bar.setRange(0, len(worker.source_paths))
            self.progress_bar.setValue(0)
            self.cancel_button.setEnabled(True)
        elif isinstance(worker, DatasetOpenWorker):
            worker.progress.connect(self._dataset_open_progress)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.cancel_button.setEnabled(True)
        elif isinstance(worker, FijiBridgeWorker):
            worker.progress.connect(self._fiji_bridge_progress)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.cancel_button.setEnabled(True)
        else:
            self.progress_bar.setRange(0, 0)
            self.cancel_button.setEnabled(False)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._worker_finished)
        self._thread = thread
        self._worker = worker
        self.open_button.setEnabled(False)
        self.open_action.setEnabled(False)
        self.edit_metadata_action.setEnabled(False)
        self.batch_tree.setEnabled(False)
        self.export_settings_action.setEnabled(False)
        self.output_images_menu.setEnabled(False)
        self.cell_count_demo_action.setEnabled(False)
        self.send_to_fiji_action.setEnabled(False)
        self.update_button.setEnabled(False)
        self.refresh_preview_action.setEnabled(False)
        self.export_button.setEnabled(False)
        self.export_action.setEnabled(False)
        self.status_label.setText("Processing…")
        thread.start()

    @Slot(int, int, str)
    def _export_progress(self, completed: int, total: int, filename: str) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(completed)
        if filename and completed < total:
            self.status_label.setText(f"Processing {completed + 1} / {total}: {filename}")

    @Slot(int, str)
    def _dataset_open_progress(self, percent: int, phase: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(min(max(percent, 0), 100))
        self.status_label.setText(phase)

    @Slot(int, str)
    def _fiji_bridge_progress(self, percent: int, phase: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(min(max(percent, 0), 100))
        self.status_label.setText(phase)

    @Slot()
    def cancel_processing(self) -> None:
        if isinstance(self._worker, (ExportWorker, DatasetOpenWorker, FijiBridgeWorker)):
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling safely…")

    @Slot(object)
    def _preview_finished(self, image: object) -> None:
        current_total_rotation = self._preview_total_rotation()
        if isinstance(image, PreviewRenderResult):
            result = image
            array = np.asarray(result.image)
            self.preview_full_size = result.full_size
            self.preview_resolution_level = result.level
            self.preview_available_levels = result.available_levels
            self.preview_baked_rotation_degrees = self._normalized_preview_rotation(
                result.baked_rotation_degrees
            )
            self.preview_rotation_degrees = self._normalized_preview_rotation(
                current_total_rotation - self.preview_baked_rotation_degrees
            )
        else:
            array = np.asarray(image)
            self.preview_full_size = (array.shape[1], array.shape[0])
            self.preview_resolution_level = ResolutionLevelInfo(
                0,
                array.shape[1],
                array.shape[0],
                1,
            )
            self.preview_available_levels = (self.preview_resolution_level,)
        if array.ndim == 2:
            qimage = QImage(
                array.data,
                array.shape[1],
                array.shape[0],
                array.strides[0],
                QImage.Format.Format_Grayscale8,
            )
        else:
            qimage = QImage(
                array.data,
                array.shape[1],
                array.shape[0],
                array.strides[0],
                QImage.Format.Format_RGB888,
            )
        self.preview_pixmap = QPixmap.fromImage(qimage.copy())
        self._render_preview_pixmap()
        level_text = (
            f"ResolutionLevel {self.preview_resolution_level.index} · "
            f"{self.preview_resolution_level.size_x} × {self.preview_resolution_level.size_y}"
            if self.preview_resolution_level is not None
            else f"{array.shape[1]} × {array.shape[0]}"
        )
        self.status_label.setText(f"Preview updated: {level_text}.")

    @Slot(object)
    def _cell_count_finished(self, result: object) -> None:
        if not isinstance(result, CellCountingResult):
            self._worker_failed("The cell-counting plugin returned an unexpected result.")
            return
        self.last_cell_count_result = result
        self.status_label.setText(f"Cell counting completed: {result.total_count} objects.")
        CellCountingResultsDialog(self, result).exec()

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
        base_width, base_height = self._rotated_full_size()
        width_ratio = max(1, viewport.width() - 8) / base_width
        height_ratio = max(1, viewport.height() - 8) / base_height
        self._set_preview_zoom(min(width_ratio, height_ratio, 1.0))

    def _set_preview_zoom(self, zoom: float) -> None:
        self.preview_zoom = min(16.0, max(0.02, zoom))
        if self.preview_pixmap is not None and not self.preview_pixmap.isNull():
            self._render_preview_pixmap()
        if self.metadata is not None:
            self._preview_detail_timer.start()

    def _set_initial_preview_zoom(self) -> None:
        if self.metadata is None:
            return
        viewport = self.preview_scroll.viewport().size()
        base_width, base_height = self._preview_base_size()
        width_ratio = max(1, viewport.width() - 8) / base_width
        height_ratio = max(1, viewport.height() - 8) / base_height
        self.preview_zoom = min(width_ratio, height_ratio, 1.0)

    def _preview_base_size(self) -> tuple[int, int]:
        if self.metadata is None:
            return 1200, 1200
        return (
            self.output_width_px or self.metadata.size_x,
            self.output_height_px or self.metadata.size_y,
        )

    def _preview_target_size(self) -> tuple[int, int]:
        if self.metadata is None:
            return 1200, 1200
        pixel_ratio = max(1.0, self.preview_scroll.devicePixelRatioF())
        base_width, base_height = self._preview_base_size()
        detail_zoom = self.preview_zoom * max(1.0, self.output_zoom_factor)
        return (
            max(1, round(base_width * detail_zoom * pixel_ratio)),
            max(1, round(base_height * detail_zoom * pixel_ratio)),
        )

    def _rotated_full_size(self) -> tuple[float, float]:
        if self.preview_full_size is not None:
            width, height = self.preview_full_size
        elif self.preview_pixmap is not None:
            width, height = self.preview_pixmap.width(), self.preview_pixmap.height()
        else:
            return 1.0, 1.0
        bounds = QTransform().rotate(self.preview_rotation_degrees).mapRect(
            QRectF(0.0, 0.0, float(width), float(height))
        )
        return max(1.0, bounds.width()), max(1.0, bounds.height())

    def _render_preview_pixmap(self) -> None:
        if self.preview_pixmap is None or self.preview_pixmap.isNull():
            return
        transformed = self.preview_pixmap.transformed(
            QTransform().rotate(self.preview_rotation_degrees),
            Qt.TransformationMode.SmoothTransformation,
        )
        target_width, target_height = self._rotated_full_size()
        target_width = max(1, round(target_width * self.preview_zoom))
        target_height = max(1, round(target_height * self.preview_zoom))
        scaled = transformed.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.resize(scaled.size())
        level_suffix = (
            f" · L{self.preview_resolution_level.index}"
            if self.preview_resolution_level is not None
            else ""
        )
        self.zoom_label.setText(
            f"View {self.preview_zoom * 100:.0f}% · Output {self.output_zoom_factor * 100:.0f}% · "
            f"{self._preview_total_rotation():.0f}°{level_suffix}"
        )
        self._sync_transform_inputs()

    @Slot(float)
    def _zoom_preview_by_factor(self, factor: float) -> None:
        horizontal = self.preview_scroll.horizontalScrollBar()
        vertical = self.preview_scroll.verticalScrollBar()
        viewport = self.preview_scroll.viewport()
        cursor = viewport.mapFromGlobal(self.cursor().pos())
        old_width = max(1, self.preview_label.width())
        old_height = max(1, self.preview_label.height())
        relative_x = (horizontal.value() + cursor.x()) / old_width
        relative_y = (vertical.value() + cursor.y()) / old_height
        self._set_preview_zoom(self.preview_zoom * factor)
        horizontal.setValue(round(relative_x * self.preview_label.width() - cursor.x()))
        vertical.setValue(round(relative_y * self.preview_label.height() - cursor.y()))

    @Slot(int, int)
    def _pan_preview(self, delta_x: int, delta_y: int) -> None:
        horizontal = self.preview_scroll.horizontalScrollBar()
        vertical = self.preview_scroll.verticalScrollBar()
        horizontal.setValue(horizontal.value() - delta_x)
        vertical.setValue(vertical.value() - delta_y)

    @Slot(float)
    def _rotate_preview(self, delta_degrees: float) -> None:
        self.preview_rotation_degrees = self._normalized_preview_rotation(
            self.preview_rotation_degrees + delta_degrees
        )
        self._render_preview_pixmap()
        self._schedule_preview_refresh()

    @staticmethod
    def _normalized_preview_rotation(degrees: float) -> float:
        normalized = float(degrees) % 360.0
        return normalized - 360.0 if normalized > 180.0 else normalized

    def _preview_total_rotation(self) -> float:
        return self._normalized_preview_rotation(
            self.preview_baked_rotation_degrees + self.preview_rotation_degrees
        )

    def _sync_transform_inputs(self) -> None:
        self.output_zoom_input.blockSignals(True)
        self.output_zoom_input.setValue(self.output_zoom_factor * 100.0)
        self.output_zoom_input.blockSignals(False)
        self.rotation_input.blockSignals(True)
        self.rotation_input.setValue(self._preview_total_rotation())
        self.rotation_input.blockSignals(False)

    @Slot(float)
    def _output_zoom_input_changed(self, percent: float) -> None:
        self.output_zoom_factor = min(16.0, max(0.02, percent / 100.0))
        self._sync_transform_inputs()
        self._schedule_preview_refresh()

    @Slot(float)
    def _rotation_input_changed(self, degrees: float) -> None:
        self.preview_rotation_degrees = self._normalized_preview_rotation(
            degrees - self.preview_baked_rotation_degrees
        )
        self._render_preview_pixmap()
        self._schedule_preview_refresh()

    @Slot()
    def reset_preview_rotation(self) -> None:
        self.preview_rotation_degrees = self._normalized_preview_rotation(
            -self.preview_baked_rotation_degrees
        )
        self._render_preview_pixmap()
        self._schedule_preview_refresh()

    @Slot()
    def reset_preview_view(self) -> None:
        """Restore the preview to 100%, zero rotation, and a centred position."""

        if self.preview_pixmap is None or self.preview_pixmap.isNull():
            return
        self.preview_rotation_degrees = self._normalized_preview_rotation(
            -self.preview_baked_rotation_degrees
        )
        self._set_preview_zoom(1.0)
        horizontal = self.preview_scroll.horizontalScrollBar()
        vertical = self.preview_scroll.verticalScrollBar()
        horizontal.setValue(horizontal.maximum() // 2)
        vertical.setValue(vertical.maximum() // 2)
        self.status_label.setText("Preview view reset to 100% and 0°.")

    @Slot()
    def _refresh_preview_resolution(self) -> None:
        if not self.preview_available_levels or self.preview_resolution_level is None:
            return
        target_width, target_height = self._preview_target_size()
        adequate = [
            level
            for level in self.preview_available_levels
            if level.size_x >= target_width and level.size_y >= target_height
        ]
        desired = (
            min(adequate, key=lambda level: (level.pixel_count_xy, level.index))
            if adequate
            else max(
                self.preview_available_levels,
                key=lambda level: (level.pixel_count_xy, -level.index),
            )
        )
        if desired.index != self.preview_resolution_level.index:
            if self.preview_refresh_interval_ms == 0:
                self._preview_refresh_pending = True
                self.status_label.setText("Automatic preview refresh paused; use Refresh Preview to update.")
                return
            self._start_preview(show_warnings=False)

    @Slot(object)
    def _export_finished(self, outcome: object) -> None:
        batch_outcome: BatchExportOutcome = outcome  # type: ignore[assignment]
        result_list = list(batch_outcome.results)
        info_paths = list(batch_outcome.info_paths)
        summary_paths = list(batch_outcome.summary_paths)
        if info_paths:
            self.last_output_directory = info_paths[-1].parent
            self.open_folder_button.setEnabled(True)
            self.open_output_action.setEnabled(True)
        clipboard_note = ""
        clipboard_copied = False
        merge_result = next(
            (result for result in reversed(result_list) if result.output_kind == "merge"),
            None,
        )
        if self.copy_to_clipboard and merge_result is not None:
            try:
                self._copy_image_to_clipboard(merge_result.path)
                clipboard_copied = True
                clipboard_note = "\nThe merged image was copied to the Clipboard."
            except Exception as exc:
                clipboard_note = f"\nClipboard copy failed: {exc}"
        elif self.copy_to_clipboard and result_list:
            clipboard_note = "\nClipboard copy was skipped because no merge output was selected."
        status_prefix = "Export cancelled" if batch_outcome.cancelled else "Export completed"
        self.status_label.setText(
            f"{status_prefix}: {len(result_list)} image files from "
            f"{len(info_paths)} IMS file(s)." + (" Merged image copied to Clipboard." if clipboard_copied else "")
        )
        output_directories = sorted({str(path.parent) for path in info_paths})
        output_text = "\n".join(output_directories) or "No output files were created."
        error_text = "\n\nSkipped files:\n" + "\n".join(batch_outcome.errors) if batch_outcome.errors else ""
        warning_text = (
            "\n\nCompatibility adjustments:\n" + "\n".join(batch_outcome.warnings) if batch_outcome.warnings else ""
        )
        if len(summary_paths) == 1:
            summary_text = "\n\nPPT summary:\n" + summary_paths[0].read_text(encoding="utf-8")
        elif summary_paths:
            summary_text = f"\n\nPPT summaries: {len(summary_paths)} text files"
        else:
            summary_text = ""
        QMessageBox.information(
            self,
            status_prefix,
            f"{len(result_list)} image files from {len(info_paths)} IMS file(s) were created."
            f"{clipboard_note}\n\nOutput folder(s):\n{output_text}"
            f"\n\nExport records: {len(info_paths)}"
            f"\nPPT summary files: {len(summary_paths)}{summary_text}{warning_text}{error_text}",
        )

    @staticmethod
    def _copy_image_to_clipboard(path: Path) -> None:
        with Image.open(path) as source:
            array = np.asarray(source.convert("RGB")).copy()
        qimage = QImage(
            array.data,
            array.shape[1],
            array.shape[0],
            array.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
        QApplication.clipboard().setImage(qimage)

    @Slot(str)
    def _worker_failed(self, reason: str) -> None:
        self.status_label.setText("Processing failed.")
        QMessageBox.critical(self, "Processing failed", reason)

    @Slot(object)
    def _fiji_bridge_finished(self, outcome: object) -> None:
        if not isinstance(outcome, FijiBridgeOutcome):
            self._worker_failed("The Fiji bridge returned an unexpected result.")
            return
        if outcome.cancelled:
            self.status_label.setText("Sending data to Fiji was cancelled.")
            return
        if outcome.result is None:
            self._worker_failed("Fiji did not receive an image.")
            return
        self.status_label.setText(f"Opened in Fiji: {outcome.result.ome_tiff_path.name}")
        QMessageBox.information(
            self,
            "Opened in Fiji",
            "The selected raw channels and Z range were exported as OME-TIFF and opened in Fiji.\n\n"
            f"Temporary bridge file:\n{outcome.result.ome_tiff_path}\n\n"
            "Display Min/Max/Gamma are intentionally not baked into the raw data.",
        )

    @Slot()
    def _worker_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.open_button.setEnabled(True)
        self.open_action.setEnabled(True)
        self.edit_metadata_action.setEnabled(self.metadata is not None)
        self.batch_tree.setEnabled(True)
        self.export_settings_action.setEnabled(True)
        self.output_images_menu.setEnabled(self.metadata is not None)
        self.cell_count_demo_action.setEnabled(self.metadata is not None)
        self.send_to_fiji_action.setEnabled(self.metadata is not None)
        self.update_button.setEnabled(self.metadata is not None)
        self.refresh_preview_action.setEnabled(self.metadata is not None)
        self.cancel_button.setEnabled(False)
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
        self._update_export_enabled()
        if self._manual_preview_refresh_pending:
            self._manual_preview_refresh_pending = False
            self._run_scheduled_preview()
        elif self._preview_refresh_pending and self.preview_refresh_interval_ms > 0:
            self._preview_timer.start(self.preview_refresh_interval_ms)

    @Slot()
    def open_output_folder(self) -> None:
        target = self.last_output_directory or self._current_output_directory()
        if target is not None and target.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    @Slot()
    def open_github_repository(self) -> None:
        if not QDesktopServices.openUrl(QUrl(GITHUB_REPOSITORY_URL)):
            QMessageBox.warning(
                self,
                "Unable to open GitHub",
                f"Please open this address manually:\n{GITHUB_REPOSITORY_URL}",
            )

    @Slot()
    def show_about_dialog(self) -> None:
        QMessageBox.about(
            self,
            "About IEA",
            f"<h3>image_easy-to-adjust (IEA)</h3>"
            f"<p>Version {__version__}</p>"
            "<p>The source code for this software is publicly available. It was developed by Song Xuanyu "
            "with assistance from Codex.</p>"
            "<p>IEA is designed for simple batch processing of microscopy image files and is currently "
            "developed primarily "
            "to meet the author's own workflow needs.</p>"
            '<p>Contact: <a href="mailto:songxuanyuhappy@gmail.com">songxuanyuhappy@gmail.com</a></p>'
            f'<p>Source code: <a href="{GITHUB_REPOSITORY_URL}">{GITHUB_REPOSITORY_URL}</a></p>',
        )


def launch_gui() -> int:
    """Launch the application and return the Qt event-loop exit code."""

    application = QApplication.instance() or QApplication([])
    application.setApplicationName("IEA")
    application.setApplicationDisplayName("image_easy-to-adjust")
    window = IMSFigureExporterWindow()
    window.show()
    return application.exec()
