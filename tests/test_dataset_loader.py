from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from iea.dataset_loader import DatasetLoader, DatasetLoaderError
from iea.image_dataset import DisplaySettings
from iea.imaris_writer import IMSWriterBackend
from iea.ims_reader import IMSReader
from tests.test_image_dataset import make_memory_dataset


class FakeAutoDisplay:
    def __init__(self) -> None:
        self.calls = 0

    def calculate_all(self, dataset):
        self.calls += 1
        settings = tuple(
            DisplaySettings(5.0, 90.0, 1.0, channel.color, source="OIB_AUTO")
            for channel in dataset.metadata.channels
        )
        dataset.apply_display_settings(settings)
        return settings


class FakeWriter:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def write(self, _dataset, output_path, _settings, progress=None, is_cancelled=None):
        self.calls += 1
        if self.fail:
            Path(output_path).write_bytes(b"partial")
            raise RuntimeError("simulated writer failure")
        Path(output_path).write_bytes(b"valid-cache")

        class Result:
            blocks_written = 3
            limitations = ()

        return Result()


def backend_factory(data: np.ndarray, opened: list[Path], *, fail: bool = False):
    def factory(path: Path):
        opened.append(path)
        if fail:
            raise RuntimeError("invalid IMS")
        return make_memory_dataset(data, path).backend

    return factory


def test_oib_without_cache_uses_oib_auto_adjustment_and_creates_cache(tmp_path: Path) -> None:
    oib = tmp_path / "sample.OIB"
    oib.write_bytes(b"read-only-original")
    data = np.arange(24, dtype=np.uint16).reshape((1, 1, 2, 3, 4))
    ims_opened: list[Path] = []
    oib_opened: list[Path] = []
    auto = FakeAutoDisplay()
    writer = FakeWriter()
    loader = DatasetLoader(
        ims_backend_factory=backend_factory(data, ims_opened),
        oib_backend_factory=backend_factory(data, oib_opened),
        auto_display=auto,
        writer=writer,
    )

    session = loader.open(oib)

    assert session.relationship.cache_status == "created"
    assert session.active_backend == "MemoryBackend"
    assert auto.calls == 1
    assert writer.calls == 1
    assert oib_opened == [oib.resolve()]
    assert not ims_opened
    assert oib.read_bytes() == b"read-only-original"
    assert oib.with_suffix(".ims").read_bytes() == b"valid-cache"
    projection, _, _ = session.dataset.project_z_range(0, 1, 2)
    np.testing.assert_array_equal(projection, np.max(data[0, 0], axis=0))


def test_valid_cache_never_opens_oib_or_runs_auto_display(tmp_path: Path) -> None:
    oib = tmp_path / "sample.oib"
    cache = tmp_path / "sample.IMS"
    oib.write_bytes(b"original")
    cache.write_bytes(b"cache")
    cache_mtime = cache.stat().st_mtime_ns
    data = np.zeros((1, 1, 1, 2, 2), dtype=np.uint16)
    ims_opened: list[Path] = []
    oib_opened: list[Path] = []
    auto = FakeAutoDisplay()
    writer = FakeWriter()
    loader = DatasetLoader(
        ims_backend_factory=backend_factory(data, ims_opened),
        oib_backend_factory=backend_factory(data, oib_opened),
        auto_display=auto,
        writer=writer,
    )

    session = loader.open(oib)

    assert session.relationship.cache_status == "valid"
    assert ims_opened == [cache.resolve()]
    assert not oib_opened
    assert auto.calls == 0
    assert writer.calls == 0
    assert cache.read_bytes() == b"cache"
    assert cache.stat().st_mtime_ns == cache_mtime


def test_opening_ims_directly_skips_oib_and_auto_display(tmp_path: Path) -> None:
    ims = tmp_path / "direct.ims"
    ims.write_bytes(b"cache")
    data = np.zeros((1, 1, 1, 2, 2), dtype=np.uint16)
    ims_opened: list[Path] = []
    oib_opened: list[Path] = []
    auto = FakeAutoDisplay()
    loader = DatasetLoader(
        ims_backend_factory=backend_factory(data, ims_opened),
        oib_backend_factory=backend_factory(data, oib_opened),
        auto_display=auto,
        writer=FakeWriter(),
    )

    session = loader.open(ims)

    assert session.relationship.cache_status == "not_applicable"
    assert ims_opened == [ims.resolve()]
    assert not oib_opened
    assert auto.calls == 0


def test_writer_failure_preserves_oib_and_removes_temporary_file(tmp_path: Path) -> None:
    oib = tmp_path / "failure.oib"
    oib.write_bytes(b"untouched")
    before = oib.stat().st_mtime_ns
    data = np.zeros((1, 1, 1, 2, 2), dtype=np.uint16)
    loader = DatasetLoader(
        oib_backend_factory=backend_factory(data, []),
        auto_display=FakeAutoDisplay(),
        writer=FakeWriter(fail=True),
    )

    with pytest.raises(DatasetLoaderError, match="conversion failed"):
        loader.open(oib)

    assert oib.read_bytes() == b"untouched"
    assert oib.stat().st_mtime_ns == before
    assert not (tmp_path / "failure.ims").exists()
    assert not (tmp_path / "failure.ims.tmp").exists()


def test_invalid_cache_falls_back_without_overwriting_it(tmp_path: Path) -> None:
    oib = tmp_path / "damaged.oib"
    cache = tmp_path / "damaged.ims"
    oib.write_bytes(b"original")
    cache.write_bytes(b"broken-cache")
    data = np.zeros((1, 1, 1, 2, 2), dtype=np.uint16)
    oib_opened: list[Path] = []
    auto = FakeAutoDisplay()
    writer = FakeWriter()
    loader = DatasetLoader(
        ims_backend_factory=backend_factory(data, [], fail=True),
        oib_backend_factory=backend_factory(data, oib_opened),
        auto_display=auto,
        writer=writer,
    )

    session = loader.open(oib)

    assert session.relationship.cache_status == "invalid"
    assert oib_opened == [oib.resolve()]
    assert auto.calls == 1
    assert writer.calls == 0
    assert cache.read_bytes() == b"broken-cache"


@pytest.mark.skipif(not IMSWriterBackend.is_available(), reason="PyImarisWriter is not installed")
def test_created_cache_is_reopened_without_reading_oib_pixels(tmp_path: Path) -> None:
    oib = tmp_path / "round-trip.oib"
    oib.write_bytes(b"original")
    raw = np.arange(60, dtype=np.uint16).reshape((1, 1, 3, 4, 5))
    oib_opened: list[Path] = []
    auto = FakeAutoDisplay()
    loader = DatasetLoader(
        oib_backend_factory=backend_factory(raw, oib_opened),
        auto_display=auto,
        writer=IMSWriterBackend(block_xy=64, thread_count=1),
    )

    first_session = loader.open(oib)
    first_session.close()
    second_session = loader.open(oib)

    assert first_session.relationship.cache_status == "created"
    assert second_session.relationship.cache_status == "valid"
    assert second_session.active_backend == "IMSBackend"
    assert oib_opened == [oib.resolve()]
    assert auto.calls == 1
    with IMSReader(oib.with_suffix(".ims")) as reader:
        np.testing.assert_array_equal(reader.read_z_range(0, 1, 3), raw[0, 0])
    second_session.close()
