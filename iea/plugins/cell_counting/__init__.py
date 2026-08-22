"""Cell-counting plugin API and built-in demo implementation."""

from .api import (
    CellCountingRequest,
    CellCountingResult,
    CellCountMeasurement,
    CellSegmenterPlugin,
    ChannelCountSummary,
    NormalizedROI,
    SegmentationOutput,
    run_cell_counting,
    write_cell_count_csv,
)
from .registry import load_cell_counting_plugins
from .threshold_demo import ThresholdConnectedComponentsPlugin

__all__ = [
    "CellCountMeasurement",
    "CellCountingRequest",
    "CellCountingResult",
    "CellSegmenterPlugin",
    "ChannelCountSummary",
    "NormalizedROI",
    "SegmentationOutput",
    "ThresholdConnectedComponentsPlugin",
    "load_cell_counting_plugins",
    "run_cell_counting",
    "write_cell_count_csv",
]
