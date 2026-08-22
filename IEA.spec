# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_dir = Path(SPECPATH)
optional_datas = []
optional_binaries = []
optional_hiddenimports = []
for package_name in (
    "PyImarisWriter",
    "bioio",
    "bioio_base",
    "bioio_bioformats",
    "bffile",
    "cjdk",
    "jgo",
    "ome_types",
    "resource_backed_dask_array",
    "scyjava",
):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    except Exception:
        continue
    optional_datas.extend(package_datas)
    optional_binaries.extend(package_binaries)
    optional_hiddenimports.extend(package_hiddenimports)

analysis = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=optional_binaries,
    datas=[
        (str(project_dir / "iea" / "resources" / "IEA.ico"), "iea/resources"),
        *optional_datas,
    ],
    hiddenimports=optional_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="image_easy-to-adjust",
    icon=str(project_dir / "IEA.ico"),
    console=False,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
