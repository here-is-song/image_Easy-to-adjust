import json
from pathlib import Path

import numpy as np
import tifffile

from main import run


def test_cli_inspection_and_full_milestone_export(sample_ims, tmp_path, capsys):
    output_dir = tmp_path / "cli-output"
    exit_code = run(
        [
            str(sample_ims),
            "--channel",
            "0",
            "--channel",
            "1",
            "--merge",
            "--z-start",
            "2",
            "--z-end",
            "3",
            "--no-scale-bar",
            "--output-dir",
            str(output_dir),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Image size: 5 × 4 × 3" in captured.out
    assert "Export completed:" in captured.out
    exported = sorted(Path(output_dir).glob("*.tif"))
    assert [path.name for path in exported] == [
        "sample_Green.tif",
        "sample_Merge.tif",
        "sample_Red_Marker.tif",
    ]
    assert tifffile.imread(output_dir / "sample_Merge.tif").shape == (4, 5, 3)
    export_info = json.loads((output_dir / "export_info.json").read_text(encoding="utf-8"))
    assert export_info["z_start_slice"] == 2
    assert export_info["z_end_slice"] == 3
    summary_path = output_dir / "sample_PPT_summary.txt"
    assert summary_path.exists()
    assert "Microscope: Olympus FV1200" in summary_path.read_text(encoding="utf-8")
    assert "PPT summary:" in captured.out


def test_cli_reads_and_exports_tiff(tmp_path, capsys):
    source = tmp_path / "mvx10.tif"
    output_dir = tmp_path / "tiff-output"
    tifffile.imwrite(
        source,
        np.arange(20, dtype=np.uint16).reshape(4, 5),
        photometric="minisblack",
        metadata=None,
    )

    exit_code = run(
        [
            str(source),
            "--channel",
            "0",
            "--no-scale-bar",
            "--output-dir",
            str(output_dir),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Image size: 5 × 4 × 1" in captured.out
    assert tifffile.imread(output_dir / "mvx10_Channel 0.tif").shape == (4, 5)
    summary = (output_dir / "mvx10_PPT_summary.txt").read_text(encoding="utf-8")
    assert "Microscope: Olympus MVX10" in summary
    assert "Objective lens: MV PLAPO 2XC, Zoom: 1.25X, single-layer image;" in summary
