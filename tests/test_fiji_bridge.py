from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile

from iea.fiji_bridge import (
    FijiBridgeError,
    export_dataset_to_ome_tiff,
    launch_fiji,
    resolve_fiji_executable,
)
from tests.test_image_dataset import make_memory_dataset


def test_resolve_fiji_executable_accepts_app_folder(tmp_path: Path) -> None:
    app = tmp_path / "Fiji.app"
    app.mkdir()
    launcher = app / "fiji-windows-x64.exe"
    launcher.write_bytes(b"launcher")

    assert resolve_fiji_executable(app) == launcher.resolve()


def test_resolve_fiji_executable_rejects_incomplete_folder(tmp_path: Path) -> None:
    with pytest.raises(FijiBridgeError, match="No Fiji Windows launcher"):
        resolve_fiji_executable(tmp_path)


def test_ome_tiff_bridge_preserves_raw_channels_z_and_calibration(tmp_path: Path) -> None:
    data = np.arange(1 * 2 * 3 * 4 * 5, dtype=np.uint16).reshape((1, 2, 3, 4, 5))
    dataset = make_memory_dataset(data, tmp_path / "source.ims")
    output = tmp_path / "bridge.ome.tif"
    updates: list[tuple[float, str]] = []

    export_dataset_to_ome_tiff(
        dataset,
        output,
        (1, 0),
        2,
        3,
        progress=lambda fraction, phase: updates.append((fraction, phase)),
    )

    with tifffile.TiffFile(output) as tif:
        exported = tif.asarray()
        ome_xml = tif.ome_metadata or ""
    np.testing.assert_array_equal(exported, data[0, (1, 0), 1:3])
    assert "PhysicalSizeX=\"0.5\"" in ome_xml
    assert "PhysicalSizeZ=\"1.5\"" in ome_xml
    assert "Channel 1" in ome_xml and "Channel 0" in ome_xml
    assert updates[-1][0] == 1.0


def test_launch_fiji_uses_external_process(tmp_path: Path, monkeypatch) -> None:
    app = tmp_path / "Fiji.app"
    app.mkdir()
    launcher = app / "fiji-windows-x64.exe"
    launcher.write_bytes(b"launcher")
    image = tmp_path / "image.ome.tif"
    image.write_bytes(b"image")
    calls = []
    monkeypatch.setattr("iea.fiji_bridge.subprocess.Popen", lambda *args, **kwargs: calls.append((args, kwargs)))

    result = launch_fiji(app, image)

    assert result.ome_tiff_path == image.resolve()
    assert calls[0][0][0] == [str(launcher.resolve()), str(image.resolve())]
    assert calls[0][1]["cwd"] == str(app.resolve())
