"""Persistent GUI preference storage isolated from the main window."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

from .models import GuiPreferences, ImageOutputSettings, MetadataCorrection

SECTION_KEYS = ("batch_files", "channels", "z_range", "objective", "scale_bar")


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
        last_input_directory = str(self.settings.value("input/last_directory", "")).strip()
        interval = self.settings.value("preview/refresh_interval_ms", 1000, type=int)
        if interval not in {0, 500, 1000, 2000, 5000}:
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
                last_input_directory=(Path(last_input_directory) if last_input_directory else None),
                copy_to_clipboard=self.settings.value("export/copy_to_clipboard", False, type=bool),
                preview_refresh_interval_ms=interval,
                section_expanded={
                    key: self.settings.value(f"layout/sections/{key}/expanded", True, type=bool) for key in SECTION_KEYS
                },
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

    def save_last_input_directory(self, directory: Path) -> None:
        self.settings.setValue("input/last_directory", str(directory))
        self.settings.sync()

    def load_fiji_directory(self) -> Path | None:
        saved = str(self.settings.value("integration/fiji_directory", "")).strip()
        return Path(saved) if saved else None

    def save_fiji_directory(self, directory: Path) -> None:
        self.settings.setValue("integration/fiji_directory", str(directory))
        self.settings.sync()

    def load_metadata_corrections(self) -> dict[Path, MetadataCorrection]:
        raw = str(self.settings.value("metadata/corrections", "")).strip()
        if not raw:
            return {}
        try:
            records = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        corrections: dict[Path, MetadataCorrection] = {}
        if not isinstance(records, dict):
            return corrections
        for path_text, values in records.items():
            if not isinstance(path_text, str) or not isinstance(values, dict):
                continue
            try:
                correction = MetadataCorrection(
                    physical_width_um=_positive_optional(values.get("physical_width_um")),
                    physical_height_um=_positive_optional(values.get("physical_height_um")),
                    z_spacing_um=_positive_optional(values.get("z_spacing_um")),
                )
            except (TypeError, ValueError):
                continue
            if not correction.is_empty:
                corrections[Path(path_text)] = correction
        return corrections

    def save_metadata_corrections(self, corrections: dict[Path, MetadataCorrection]) -> None:
        records = {
            str(path): {
                "physical_width_um": correction.physical_width_um,
                "physical_height_um": correction.physical_height_um,
                "z_spacing_um": correction.z_spacing_um,
            }
            for path, correction in corrections.items()
            if not correction.is_empty
        }
        self.settings.setValue("metadata/corrections", json.dumps(records, ensure_ascii=False))
        self.settings.sync()

    def save_section_expanded(self, section_key: str, expanded: bool) -> None:
        if section_key not in SECTION_KEYS:
            raise ValueError(f"Unknown collapsible section: {section_key}")
        self.settings.setValue(f"layout/sections/{section_key}/expanded", expanded)
        self.settings.sync()


def _positive_optional(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if number > 0 else None
