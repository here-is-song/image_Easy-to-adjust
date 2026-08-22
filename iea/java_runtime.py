"""Windows compatibility helpers for the Bio-Formats JPype runtime."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path


class JavaRuntimeError(RuntimeError):
    """Raised when the Java bridge cannot be prepared safely."""


def prepare_jpype_ascii_runtime() -> Path | None:
    """Copy JPype's small native bridge to an ASCII path when required.

    Java 11 on Windows cannot load JPype's native library from some Unicode
    installation paths. The actual microscopy file remains in place; only the
    Python/Java bridge package is mirrored into the user's temporary directory.
    """

    if sys.platform != "win32":
        return None
    if "jpype" in sys.modules or "_jpype" in sys.modules:
        loaded = sys.modules.get("_jpype")
        loaded_path = getattr(loaded, "__file__", "")
        if loaded_path and not str(loaded_path).isascii():
            raise JavaRuntimeError(
                "JPype was loaded from a non-ASCII path before Bio-Formats initialization. "
                "Restart IEA and open the OIB again."
            )
        return None

    jpype_spec = importlib.util.find_spec("jpype")
    native_spec = importlib.util.find_spec("_jpype")
    if jpype_spec is None or jpype_spec.origin is None or native_spec is None or native_spec.origin is None:
        raise JavaRuntimeError("JPype is not installed; reinstall the IEA OIB dependencies.")
    package_dir = Path(jpype_spec.origin).resolve().parent
    native_file = Path(native_spec.origin).resolve()
    site_root = package_dir.parent
    support_jar = site_root / "org.jpype.jar"
    if not support_jar.is_file():
        raise JavaRuntimeError(f"JPype support library was not found: {support_jar}")
    source_paths = (package_dir, native_file, support_jar)
    if all(str(path).isascii() for path in source_paths):
        return None

    try:
        version = importlib.metadata.version("JPype1")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    runtime_name = (
        f"jpype-{version}-py{sys.version_info.major}{sys.version_info.minor}-"
        f"{platform.machine().casefold()}"
    )
    runtime_root = Path(tempfile.gettempdir()).resolve() / "image_easy-to-adjust" / runtime_name
    if not str(runtime_root).isascii():
        raise JavaRuntimeError("IEA could not locate an ASCII temporary directory for the Java bridge.")
    target_package = runtime_root / "jpype"
    target_native = runtime_root / native_file.name
    target_jar = runtime_root / support_jar.name
    runtime_ready = (
        target_package.is_dir()
        and target_native.is_file()
        and target_native.stat().st_size == native_file.stat().st_size
        and target_jar.is_file()
        and target_jar.stat().st_size == support_jar.stat().st_size
    )
    if not runtime_ready:
        try:
            runtime_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(package_dir, target_package, dirs_exist_ok=True)
            shutil.copy2(native_file, target_native)
            shutil.copy2(support_jar, target_jar)
        except OSError as exc:
            raise JavaRuntimeError(f"Unable to prepare the JPype ASCII runtime: {exc}") from exc

    sys.path.insert(0, str(runtime_root))
    importlib.invalidate_caches()
    os.environ["IEA_JPYPE_RUNTIME"] = str(runtime_root)
    return runtime_root
