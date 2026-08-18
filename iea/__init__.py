"""Core package for image_easy-to-adjust (IEA)."""

__version__ = "0.2.0"

from .ims_reader import IMSReader, IMSReaderError

__all__ = ["IMSReader", "IMSReaderError"]
