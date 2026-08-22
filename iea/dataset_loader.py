"""Format-neutral dataset loader and OIB-to-IMS cache workflow."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

from .auto_display import ImarisLikeAutoDisplay
from .bioformats_reader import BioFormatsBackend
from .image_dataset import (
    DatasetFileRelationship,
    ImageDataset,
    ImageSession,
    PixelBackend,
)
from .imaris_writer import IMSWriterBackend
from .ims_backend import IMSPixelBackend

LOGGER = logging.getLogger(__name__)

LoaderProgress = Callable[[float, str], None]
BackendFactory = Callable[[Path], PixelBackend]


class DatasetLoaderError(RuntimeError):
    """Raised when a requested microscopy source cannot be opened safely."""


def find_same_name_ims(oib_path: Path) -> Path | None:
    """Find an exact-basename IMS sibling with a case-insensitive extension."""

    exact_default = oib_path.with_suffix(".ims")
    if exact_default.is_file():
        return exact_default
    matches = sorted(
        (
            child
            for child in oib_path.parent.iterdir()
            if child.is_file() and child.suffix.casefold() == ".ims" and child.stem == oib_path.stem
        ),
        key=lambda child: child.name,
    )
    return matches[0] if matches else None


class DatasetLoader:
    """Open IMS directly or create/reuse a same-name IMS cache for OIB."""

    def __init__(
        self,
        ims_backend_factory: BackendFactory = IMSPixelBackend,
        oib_backend_factory: BackendFactory = BioFormatsBackend,
        auto_display: ImarisLikeAutoDisplay | None = None,
        writer: IMSWriterBackend | None = None,
    ) -> None:
        self.ims_backend_factory = ims_backend_factory
        self.oib_backend_factory = oib_backend_factory
        self.auto_display = auto_display or ImarisLikeAutoDisplay()
        self.writer = writer or IMSWriterBackend()

    def open(
        self,
        path: str | Path,
        *,
        create_cache: bool = True,
        progress: LoaderProgress | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> ImageSession:
        requested = Path(path).resolve()
        if not requested.is_file():
            raise DatasetLoaderError(f"File not found: {requested}")
        suffix = requested.suffix.casefold()
        report = progress or (lambda _fraction, _phase: None)
        if suffix == ".ims":
            report(0.05, "Opening IMS...")
            dataset = self._open_ims(requested)
            report(1.0, "IMS opened")
            return ImageSession(
                dataset=dataset,
                relationship=DatasetFileRelationship(
                    original_path=requested,
                    cache_path=None,
                    source_format="IMS",
                    cache_format=None,
                    cache_status="not_applicable",
                ),
                original_source_path=requested,
                cache_path=None,
                active_backend=dataset.active_backend,
                messages=("IMS opened directly; Auto Display Adjustment skipped.",),
            )
        if suffix != ".oib":
            raise DatasetLoaderError(f"Unsupported microscopy file type: {requested.suffix or '(none)'}")
        try:
            return self._open_oib(requested, create_cache, report, is_cancelled)
        except DatasetLoaderError:
            raise
        except Exception as exc:
            raise DatasetLoaderError(f"Unable to read OIB via Bio-Formats: {exc}") from exc

    def _open_oib(
        self,
        oib_path: Path,
        create_cache: bool,
        progress: LoaderProgress,
        is_cancelled: Callable[[], bool] | None,
    ) -> ImageSession:
        started = time.perf_counter()
        existing_cache = find_same_name_ims(oib_path)
        LOGGER.info("[DatasetLoader] Source requested: %s", oib_path)
        LOGGER.info("[DatasetLoader] IMS cache found: %s", "yes" if existing_cache else "no")
        if existing_cache is not None:
            try:
                progress(0.05, "Validating existing IMS cache...")
                dataset = self._open_ims(existing_cache)
            except Exception as exc:
                LOGGER.warning("[DatasetLoader] Existing IMS appears invalid: %s", exc)
                progress(0.1, "Existing IMS appears invalid; reading OIB...")
                dataset = self._open_and_adjust_oib(oib_path, progress)
                return ImageSession(
                    dataset=dataset,
                    relationship=DatasetFileRelationship(
                        original_path=oib_path,
                        cache_path=existing_cache,
                        source_format="OIB",
                        cache_format="IMS",
                        cache_status="invalid",
                    ),
                    original_source_path=oib_path,
                    cache_path=existing_cache,
                    active_backend=dataset.active_backend,
                    messages=(
                        f"Existing IMS appears invalid: {exc}",
                        "Opened the original OIB without overwriting the invalid IMS cache.",
                    ),
                )
            progress(1.0, "Using existing IMS cache")
            LOGGER.info("[DatasetLoader] Backend: IMSBackend; Auto Display: skipped")
            return ImageSession(
                dataset=dataset,
                relationship=DatasetFileRelationship(
                    original_path=oib_path,
                    cache_path=existing_cache,
                    source_format="OIB",
                    cache_format="IMS",
                    cache_status="valid",
                ),
                original_source_path=oib_path,
                cache_path=existing_cache,
                active_backend=dataset.active_backend,
                messages=("Using existing IMS cache", "Auto Display Adjustment skipped."),
            )

        dataset = self._open_and_adjust_oib(oib_path, progress)
        target_cache = oib_path.with_suffix(".ims")
        if not create_cache:
            progress(1.0, "OIB opened without creating IMS cache")
            return ImageSession(
                dataset=dataset,
                relationship=DatasetFileRelationship(
                    original_path=oib_path,
                    cache_path=target_cache,
                    source_format="OIB",
                    cache_format="IMS",
                    cache_status="missing",
                ),
                original_source_path=oib_path,
                cache_path=target_cache,
                active_backend=dataset.active_backend,
                messages=("OIB opened; IMS cache creation was disabled.",),
            )

        temporary = target_cache.with_name(f"{target_cache.name}.tmp")
        if temporary.exists():
            temporary.unlink()
        try:
            progress(0.15, "Creating IMS...")
            result = self.writer.write(
                dataset,
                temporary,
                dataset.display_settings,
                progress=progress,
                is_cancelled=is_cancelled,
            )
            if not temporary.is_file() or temporary.stat().st_size == 0:
                raise DatasetLoaderError("ImarisWriter finalized without creating a valid temporary file.")
            os.replace(temporary, target_cache)
            progress(1.0, "IMS created")
        except Exception as exc:
            if temporary.exists():
                temporary.unlink()
            dataset.close()
            raise DatasetLoaderError(f"OIB conversion failed: {exc}") from exc
        elapsed = time.perf_counter() - started
        metadata = dataset.metadata
        LOGGER.info(
            "[DatasetLoader] Reader=Bio-Formats Dimensions=%s Channels=%s PixelType=%s IMS=%s Time=%.3fs",
            (
                f"{metadata.size_x}x{metadata.size_y}x{metadata.size_z}"
                if metadata is not None
                else "unknown"
            ),
            metadata.channel_count if metadata is not None else "unknown",
            metadata.dtype if metadata is not None else "unknown",
            target_cache,
            elapsed,
        )
        messages = ["IMS created", f"Streaming blocks written: {result.blocks_written}."]
        messages.extend(result.limitations)
        return ImageSession(
            dataset=dataset,
            relationship=DatasetFileRelationship(
                original_path=oib_path,
                cache_path=target_cache,
                source_format="OIB",
                cache_format="IMS",
                cache_status="created",
            ),
            original_source_path=oib_path,
            cache_path=target_cache,
            active_backend=dataset.active_backend,
            messages=tuple(messages),
        )

    def _open_ims(self, path: Path) -> ImageDataset:
        dataset = ImageDataset(self.ims_backend_factory(path), "IMS")
        try:
            dataset.open()
        except Exception:
            dataset.close()
            raise
        return dataset

    def _open_and_adjust_oib(self, path: Path, progress: LoaderProgress) -> ImageDataset:
        progress(0.02, "Reading OIB...")
        dataset = ImageDataset(self.oib_backend_factory(path), "OIB")
        try:
            dataset.open()
            metadata = dataset.metadata
            if metadata is None:
                raise DatasetLoaderError("Bio-Formats returned no normalized metadata.")
            LOGGER.info(
                "[DatasetLoader] Backend=BioFormats Dimensions=%dx%dx%d Channels=%d PixelType=%s",
                metadata.size_x,
                metadata.size_y,
                metadata.size_z,
                metadata.channel_count,
                metadata.dtype,
            )
            progress(0.08, "Analyzing display range...")
            self.auto_display.calculate_all(dataset)
            return dataset
        except Exception:
            dataset.close()
            raise


def open_microscopy_dataset(
    path: str | Path,
    *,
    create_cache: bool = True,
    progress: LoaderProgress | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> ImageSession:
    """Open any currently supported microscopy source through the common loader."""

    return DatasetLoader().open(
        path,
        create_cache=create_cache,
        progress=progress,
        is_cancelled=is_cancelled,
    )
