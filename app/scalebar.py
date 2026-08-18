"""Automatic physical scale-bar selection and raster drawing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont


SCALE_BAR_CANDIDATES_UM: tuple[float, ...] = (
    1,
    2,
    5,
    10,
    20,
    50,
    100,
    200,
    500,
    1000,
)


def choose_auto_scale_bar_um(
    width_pixels: int,
    voxel_size_x_um: float,
    candidates: tuple[float, ...] = SCALE_BAR_CANDIDATES_UM,
) -> float:
    """Choose the candidate closest to 15% of the physical image width."""

    if width_pixels <= 0 or not np.isfinite(voxel_size_x_um) or voxel_size_x_um <= 0:
        raise ValueError("Image width and X voxel size must be positive.")
    target = width_pixels * voxel_size_x_um * 0.15
    return float(min(candidates, key=lambda candidate: (abs(candidate - target), candidate)))


def scale_bar_pixels(scale_bar_um: float, voxel_size_x_um: float) -> int:
    """Convert a physical bar length to the nearest positive pixel length."""

    if scale_bar_um <= 0 or voxel_size_x_um <= 0:
        raise ValueError("Scale-bar length and X voxel size must be positive.")
    return max(1, int(round(scale_bar_um / voxel_size_x_um)))


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    )
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_scale_bar(
    image: NDArray[np.uint8],
    voxel_size_x_um: float,
    scale_bar_um: float | None = None,
    thickness_px: int | None = None,
    font_size_px: int | None = None,
) -> tuple[NDArray[np.uint8], float]:
    """Draw a white, bottom-right scale bar and label on a copy of an image."""

    array = np.asarray(image)
    if array.dtype != np.uint8 or array.ndim not in (2, 3):
        raise ValueError("Scale-bar drawing requires a uint8 grayscale or RGB image.")
    if array.ndim == 3 and array.shape[2] != 3:
        raise ValueError("Color image must have exactly three RGB channels.")
    height, width = array.shape[:2]
    chosen_um = (
        choose_auto_scale_bar_um(width, voxel_size_x_um)
        if scale_bar_um is None
        else float(scale_bar_um)
    )
    bar_width = scale_bar_pixels(chosen_um, voxel_size_x_um)
    margin_x = max(4, int(round(width * 0.03)))
    margin_y = max(4, int(round(height * 0.03)))
    if bar_width > width - 2 * margin_x:
        raise ValueError("Scale bar is wider than the available image area.")

    pil_image = Image.fromarray(array.copy())
    draw = ImageDraw.Draw(pil_image)
    white: int | tuple[int, int, int] = 255 if array.ndim == 2 else (255, 255, 255)
    if thickness_px is not None and thickness_px <= 0:
        raise ValueError("Scale-bar thickness must be positive when specified.")
    if font_size_px is not None and font_size_px <= 0:
        raise ValueError("Scale-bar font size must be positive when specified.")
    thickness = (
        int(thickness_px)
        if thickness_px is not None
        else max(3, int(round(height * 0.004)))
    )
    x_right = width - margin_x
    x_left = x_right - bar_width
    y_bar = height - margin_y - thickness
    draw.rectangle((x_left, y_bar, x_right, y_bar + thickness - 1), fill=white)

    font_size = (
        int(font_size_px)
        if font_size_px is not None
        else max(10, int(round(height * 0.035)))
    )
    font = _load_font(font_size)
    label_value = int(chosen_um) if chosen_um.is_integer() else chosen_um
    label = f"{label_value} µm"
    bbox = draw.textbbox((0, 0), label, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = int(round((x_left + x_right - text_width) / 2))
    text_y = max(0, y_bar - text_height - max(2, thickness))
    draw.text((text_x, text_y), label, fill=white, font=font)
    return np.asarray(pil_image), chosen_um
