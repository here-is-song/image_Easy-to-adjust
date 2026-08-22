"""Built-in and third-party cell-counting plugin discovery."""

from __future__ import annotations

from importlib.metadata import entry_points

from .api import CellSegmenterPlugin
from .threshold_demo import ThresholdConnectedComponentsPlugin


def load_cell_counting_plugins() -> dict[str, CellSegmenterPlugin]:
    """Load built-ins plus packages registered under the IEA entry-point group."""

    built_in = ThresholdConnectedComponentsPlugin()
    plugins: dict[str, CellSegmenterPlugin] = {built_in.plugin_id: built_in}
    for entry_point in entry_points(group="iea.cell_counting"):
        try:
            loaded = entry_point.load()
            plugin = loaded() if isinstance(loaded, type) else loaded
            if isinstance(plugin, CellSegmenterPlugin):
                plugins[plugin.plugin_id] = plugin
        except Exception:
            # A broken optional plugin must not prevent IEA from starting.
            continue
    return plugins

