"""Persistent GUI preference storage isolated from the main window."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

from .models import GuiPreferences, ImageOutputSettings


@dataclass(frozen=True)
class StoredApplicationSettings:
    output: ImageOutputSettings
    gui: GuiPreferences


class SettingsStore:
    """Read and write validated IEA preferences through QSettings."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings or self._default_settings()

    @staticmethod
    def _default_settings() -> QSettings:
        settings = QSettings("image_easy-to-adjust", "IEA")
        if not settings.allKeys():
            legacy = QSettings("IMSFigureExporter", "IMSFigureExporter")
            for key in legacy.allKeys():
                settings.setValue(key, legacy.value(key))
            settings.sync()
        return settings

    def load(self) -> StoredApplicationSettings:
        width = max(1, self.settings.value("export/width_px", 1000, type=int))
        height = max(1, self.settings.value("export/height_px", 1000, type=int))
        dpi = max(1, self.settings.value("export/dpi", 300, type=int))
        saved_format = str(self.settings.value("export/format", "tif"))
        output_format = saved_format if saved_format in {"tif", "png"} else "tif"
        saved_directory = str(self.settings.value("export/output_directory", "")).strip()
        interval = self.settings.value("preview/refresh_interval_ms", 1000, type=int)
        if interval not in {500, 1000, 2000, 5000}:
            interval = 1000
        return StoredApplicationSettings(
            output=ImageOutputSettings(
                format=output_format,
                width_px=width,
                height_px=height,
                dpi=dpi,
                resize_mode=(
                    str(self.settings.value("export/resize_mode", "fit"))
                    if str(self.settings.value("export/resize_mode", "fit")) in {"fit", "stretch", "crop"}
                    else "fit"
                ),
            ),
            gui=GuiPreferences(
                output_directory=(Path(saved_directory) if saved_directory else None),
                copy_to_clipboard=self.settings.value("export/copy_to_clipboard", False, type=bool),
                preview_refresh_interval_ms=interval,
            ),
        )

    def save_export(
        self,
        output: ImageOutputSettings,
        output_directory: Path | None,
        copy_to_clipboard: bool,
    ) -> None:
        self.settings.setValue("export/width_px", output.width_px)
        self.settings.setValue("export/height_px", output.height_px)
        self.settings.setValue("export/dpi", output.dpi)
        self.settings.setValue("export/format", output.format)
        self.settings.setValue("export/resize_mode", output.resize_mode)
        self.settings.setValue("export/copy_to_clipboard", copy_to_clipboard)
        self.settings.setValue(
            "export/output_directory",
            str(output_directory) if output_directory else "",
        )
        self.settings.sync()

    def save_refresh_interval(self, interval_ms: int) -> None:
        self.settings.setValue("preview/refresh_interval_ms", interval_ms)
        self.settings.sync()
