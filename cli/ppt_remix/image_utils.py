from __future__ import annotations

import imghdr
import struct
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


def image_size(path: Path) -> tuple[int | None, int | None]:
    kind = imghdr.what(path)
    try:
        if kind == "png":
            with path.open("rb") as fh:
                fh.seek(16)
                width, height = struct.unpack(">II", fh.read(8))
                return int(width), int(height)
        if kind == "gif":
            with path.open("rb") as fh:
                fh.seek(6)
                width, height = struct.unpack("<HH", fh.read(4))
                return int(width), int(height)
        if kind in {"jpeg", "jpg"}:
            return _jpeg_size(path)
    except Exception:
        return None, None
    return None, None


def analyze_transparency(path: Path) -> dict[str, bool | float | int | str | None]:
    result: dict[str, bool | float | int | str | None] = {
        "has_alpha": False,
        "alpha_min": None,
        "alpha_max": None,
        "transparent_pixel_ratio": 0.0,
        "near_transparent_pixel_ratio": 0.0,
        "transparent_edge_ratio": 0.0,
        "requires_transparent_background": False,
        "background_instruction": "keep opaque background",
        "classification": "opaque",
    }
    try:
        from PIL import Image

        image = Image.open(path)
        has_alpha = image.mode in {"RGBA", "LA"} or "transparency" in image.info
        result["has_alpha"] = has_alpha
        if image.mode in {"RGBA", "LA"}:
            alpha = image.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()
            result["alpha_min"] = int(alpha_min)
            result["alpha_max"] = int(alpha_max)
            transparent_pixel_ratio = _alpha_ratio(alpha, 0)
            near_transparent_pixel_ratio = _alpha_ratio(alpha, 16)
            transparent_edge_ratio = _alpha_edge_ratio(alpha, 16)
            result["transparent_pixel_ratio"] = transparent_pixel_ratio
            result["near_transparent_pixel_ratio"] = near_transparent_pixel_ratio
            result["transparent_edge_ratio"] = transparent_edge_ratio
            result["requires_transparent_background"] = _requires_transparent_background(
                transparent_pixel_ratio,
                near_transparent_pixel_ratio,
                transparent_edge_ratio,
            )
        elif "transparency" in image.info:
            result["alpha_min"] = 0
            result["alpha_max"] = 255
            result["transparent_pixel_ratio"] = 1.0
            result["near_transparent_pixel_ratio"] = 1.0
            result["transparent_edge_ratio"] = 1.0
            result["requires_transparent_background"] = True
        if result["requires_transparent_background"]:
            result["background_instruction"] = "generate subject/object on transparent background; no white canvas"
            result["classification"] = "transparent_cutout"
        elif has_alpha:
            result["classification"] = "alpha_channel_without_transparent_background"
    except Exception:
        return result
    return result


def _alpha_ratio(alpha, threshold: int) -> float:
    histogram = alpha.histogram()
    total = sum(histogram) or 1
    count = sum(histogram[: threshold + 1])
    return round(count / total, 6)


def _alpha_edge_ratio(alpha, threshold: int) -> float:
    width, height = alpha.size
    if width == 0 or height == 0:
        return 0.0
    pixels = alpha.load()
    edge_values = []
    for x in range(width):
        edge_values.append(pixels[x, 0])
        edge_values.append(pixels[x, height - 1])
    for y in range(height):
        edge_values.append(pixels[0, y])
        edge_values.append(pixels[width - 1, y])
    if not edge_values:
        return 0.0
    count = sum(1 for value in edge_values if value <= threshold)
    return round(count / len(edge_values), 6)


def _requires_transparent_background(
    transparent_pixel_ratio: float,
    near_transparent_pixel_ratio: float,
    transparent_edge_ratio: float,
) -> bool:
    return (
        transparent_pixel_ratio >= 0.01
        or near_transparent_pixel_ratio >= 0.02
        or transparent_edge_ratio >= 0.25
    )


def _jpeg_size(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as fh:
        fh.read(2)
        while True:
            marker_start = fh.read(1)
            if not marker_start:
                return None, None
            if marker_start != b"\xff":
                continue
            marker = fh.read(1)
            while marker == b"\xff":
                marker = fh.read(1)
            if marker in [b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"]:
                fh.read(3)
                height, width = struct.unpack(">HH", fh.read(4))
                return int(width), int(height)
            length_data = fh.read(2)
            if len(length_data) != 2:
                return None, None
            length = struct.unpack(">H", length_data)[0]
            fh.seek(length - 2, 1)


def likely_skip_image(name: str, width: int | None, height: int | None, min_width: int, min_height: int) -> tuple[bool, str]:
    lower = name.lower()
    if "logo" in lower:
        return True, "filename suggests logo"
    if "qr" in lower or "qrcode" in lower:
        return True, "filename suggests qr code"
    if width is not None and height is not None:
        if width < min_width or height < min_height:
            return True, "image is smaller than minimum remix size"
        ratio = max(width, height) / max(1, min(width, height))
        if ratio > 8:
            return True, "image is an extreme banner/line asset"
    return False, ""
