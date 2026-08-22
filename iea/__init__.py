"""Core package for image_easy-to-adjust (IEA)."""

__version__ = "0.3.0"

from .image_dataset import ImageDataset, ImageSession
from .ims_reader import IMSReader, IMSReaderError

__all__ = ["IMSReader", "IMSReaderError", "ImageDataset", "ImageSession"]
