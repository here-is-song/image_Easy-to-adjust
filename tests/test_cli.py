import json
from pathlib import Path

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
