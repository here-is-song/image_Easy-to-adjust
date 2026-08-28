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
    2000,
    5000,
    10000,
    20000,
    50000,
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


def format_scale_bar_length(scale_bar_um: float) -> str:
    """Use millimetres for bars of at least 1000 µm."""

    if not np.isfinite(scale_bar_um) or scale_bar_um <= 0:
        raise ValueError("Scale-bar length must be positive.")
    if scale_bar_um >= 1000:
        value = scale_bar_um / 1000
        text = f"{value:g}"
        return f"{text} mm"
    return f"{scale_bar_um:g} µm"


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


def _fit_label_font(
    draw: ImageDraw.ImageDraw,
    label: str,
    requested_size: int,
    available_width: int,
    available_height: int,
    thickness: int,
    gap: int,
) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, tuple[int, int, int, int]]:
    """Use the requested size when possible, otherwise choose the largest complete fit."""

    best_font = _load_font(1)
    best_bbox = draw.textbbox((0, 0), label, font=best_font)
    lower = 1
    upper = max(1, requested_size)
    while lower <= upper:
        candidate_size = (lower + upper) // 2
        candidate_font = _load_font(candidate_size)
        candidate_bbox = draw.textbbox((0, 0), label, font=candidate_font)
        text_width = candidate_bbox[2] - candidate_bbox[0]
        text_height = candidate_bbox[3] - candidate_bbox[1]
        if text_width <= available_width and text_height + gap + thickness <= available_height:
            best_font = candidate_font
            best_bbox = candidate_bbox
            lower = candidate_size + 1
        else:
            upper = candidate_size - 1
    return best_font, best_bbox


def draw_scale_bar(
    image: NDArray[np.uint8],
    voxel_size_x_um: float,
    scale_bar_um: float | None = None,
    thickness_px: int | None = None,
    font_size_px: int | None = None,
    content_box: tuple[int, int, int, int] | None = None,
) -> tuple[NDArray[np.uint8], float]:
    """Draw a white, bottom-right scale bar and label on a copy of an image."""

    array = np.asarray(image)
    if array.dtype != np.uint8 or array.ndim not in (2, 3):
        raise ValueError("Scale-bar drawing requires a uint8 grayscale or RGB image.")
    if array.ndim == 3 and array.shape[2] != 3:
        raise ValueError("Color image must have exactly three RGB channels.")
    height, width = array.shape[:2]
    left, top, right, bottom = content_box or (0, 0, width, height)
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("Scale-bar content box must lie inside the image.")
    content_width = right - left
    content_height = bottom - top
    chosen_um = (
        choose_auto_scale_bar_um(content_width, voxel_size_x_um) if scale_bar_um is None else float(scale_bar_um)
    )
    bar_width = scale_bar_pixels(chosen_um, voxel_size_x_um)
    margin_x = max(4, int(round(content_width * 0.03)))
    margin_y = max(4, int(round(content_height * 0.03)))
    if bar_width > content_width - 2 * margin_x:
        raise ValueError("Scale bar is wider than the available image area.")

    pil_image = Image.fromarray(array.copy())
    draw = ImageDraw.Draw(pil_image)
    white: int | tuple[int, int, int] = 255 if array.ndim == 2 else (255, 255, 255)
    if thickness_px is not None and thickness_px <= 0:
        raise ValueError("Scale-bar thickness must be positive when specified.")
    if font_size_px is not None and font_size_px <= 0:
        raise ValueError("Scale-bar font size must be positive when specified.")
    thickness = int(thickness_px) if thickness_px is not None else max(3, int(round(content_height * 0.004)))
    font_size = int(font_size_px) if font_size_px is not None else max(10, int(round(content_height * 0.035)))
    label = format_scale_bar_length(chosen_um)
    gap = max(2, thickness)
    available_width = content_width - 2 * margin_x
    available_height = content_height - 2 * margin_y
    font, bbox = _fit_label_font(
        draw,
        label,
        font_size,
        available_width,
        available_height,
        thickness,
        gap,
    )
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    if text_width > available_width or text_height + gap + thickness > available_height:
        raise ValueError("Scale-bar label and bar do not fit inside the available image area.")

    # Right-align the complete text/bar group. A wider label moves the bar left
    # with it instead of allowing either side of the text to be clipped.
    group_width = max(bar_width, text_width)
    group_right = right - margin_x
    group_left = group_right - group_width
    x_left = group_left + (group_width - bar_width) // 2
    x_right = x_left + bar_width
    y_bar = bottom - margin_y - thickness
    text_left = group_left + (group_width - text_width) // 2
    text_top = y_bar - gap - text_height
    text_origin = (text_left - bbox[0], text_top - bbox[1])

    draw.rectangle((x_left, y_bar, x_right - 1, y_bar + thickness - 1), fill=white)
    draw.text(text_origin, label, fill=white, font=font)
    return np.asarray(pil_image), chosen_um
