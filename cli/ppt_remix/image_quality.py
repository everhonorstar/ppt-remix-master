from __future__ import annotations

from pathlib import Path
from typing import Any


def stabilize_transparent_replacement(source_path: Path, output_path: Path, item: dict[str, Any]) -> dict[str, Any]:
    transparency = item.get("transparency")
    result: dict[str, Any] = {
        "action": "skipped",
        "issues": [],
        "strategy": "",
    }
    if not _requires_transparent_background(transparency):
        return result
    try:
        from PIL import Image
    except Exception as exc:
        result.update({"action": "unavailable", "issues": [f"pillow_unavailable:{exc}"]})
        return result
    try:
        with Image.open(source_path) as source_image:
            source = source_image.convert("RGBA")
        with Image.open(output_path) as generated_image:
            generated = generated_image.copy()
    except Exception as exc:
        result.update({"action": "failed", "issues": [f"open_failed:{exc}"]})
        return result

    issues = _transparent_replacement_issues(source, generated)
    if _requires_safe_fallback(issues):
        output = _source_safe_remix(source)
        action = "fallback"
        strategy = "source_alpha_safe_remix"
    else:
        output = generated.convert("RGBA")
        action = "accepted"
        strategy = "generated_rgba"
        if output.size != source.size:
            output = output.resize(source.size, Image.Resampling.LANCZOS)
            issues.append("resized_to_source_dimensions")
            action = "normalized"
            strategy = "resize_preserve_generated_alpha"
        output = _clean_alpha_edges(output)

    _replace_output_image(output, output_path)
    result.update(
        {
            "action": action,
            "issues": issues,
            "strategy": strategy,
            "source_size": list(source.size),
            "output_size": list(output.size),
        }
    )
    return result


def _replace_output_image(image, output_path: Path) -> None:
    temp_path = output_path.with_name(f".{output_path.name}.tmp.png")
    try:
        image.save(temp_path)
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _transparent_replacement_issues(source, generated) -> list[str]:
    issues: list[str] = []
    if generated.size != source.size:
        issues.append("size_mismatch")
    if _aspect_delta(source.size, generated.size) > 0.03:
        issues.append("aspect_ratio_mismatch")
    generated_rgba = generated.convert("RGBA")
    if not _has_meaningful_alpha(generated_rgba):
        issues.append("missing_or_flat_alpha")
    else:
        source_ratio = _near_transparent_ratio(source)
        generated_ratio = _near_transparent_ratio(generated_rgba)
        if abs(source_ratio - generated_ratio) > max(0.12, source_ratio * 0.35):
            issues.append("alpha_coverage_mismatch")
    if _looks_like_checkerboard_content(generated_rgba):
        issues.append("checkerboard_like_content")
    return issues


def _requires_safe_fallback(issues: list[str]) -> bool:
    hard_failures = {
        "size_mismatch",
        "aspect_ratio_mismatch",
        "missing_or_flat_alpha",
        "alpha_coverage_mismatch",
        "checkerboard_like_content",
    }
    return any(issue in hard_failures for issue in issues)


def _source_safe_remix(source):
    from PIL import Image, ImageEnhance

    base = source.convert("RGBA")
    alpha = base.getchannel("A")
    rgb = Image.new("RGB", base.size, (0, 0, 0))
    rgb.paste(base.convert("RGB"), mask=alpha)
    rgb = ImageEnhance.Color(rgb).enhance(1.06)
    rgb = ImageEnhance.Brightness(rgb).enhance(1.015)
    output = Image.new("RGBA", base.size, (0, 0, 0, 0))
    output.paste(_remap_common_classroom_colors(rgb).convert("RGB"), mask=alpha)
    output.putalpha(alpha)
    return _clean_alpha_edges(output)


def _remap_common_classroom_colors(image):
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = pixels[x, y]
            if a < 8:
                continue
            if b > 80 and b > r * 1.15 and b > g * 0.9:
                pixels[x, y] = (max(0, r - 4), min(255, g + 10), min(255, b + 18), a)
            elif r > 120 and r > g * 1.25 and r > b * 1.15:
                pixels[x, y] = (min(255, r + 10), max(0, g - 4), max(0, b - 8), a)
            elif r > 185 and g > 135 and b < 95:
                pixels[x, y] = (min(255, r + 8), min(255, g + 18), max(0, b - 6), a)
            elif r > 160 and b > 100 and g < 150:
                pixels[x, y] = (min(255, r + 12), min(255, g + 18), min(255, b + 8), a)
    return rgba


def _clean_alpha_edges(image):
    output = image.convert("RGBA")
    alpha = output.getchannel("A").point(lambda value: 0 if value < 5 else value)
    output.putalpha(alpha)
    return output


def _requires_transparent_background(transparency: object) -> bool:
    return isinstance(transparency, dict) and bool(transparency.get("requires_transparent_background"))


def _has_meaningful_alpha(image) -> bool:
    if image.mode not in {"RGBA", "LA"}:
        return False
    alpha_min, alpha_max = image.getchannel("A").getextrema()
    return alpha_min < 250 and alpha_max > 0


def _near_transparent_ratio(image, threshold: int = 16) -> float:
    alpha = image.convert("RGBA").getchannel("A")
    histogram = alpha.histogram()
    total = sum(histogram) or 1
    return sum(histogram[: threshold + 1]) / total


def _aspect_delta(source_size: tuple[int, int], generated_size: tuple[int, int]) -> float:
    source_width, source_height = source_size
    generated_width, generated_height = generated_size
    if min(source_width, source_height, generated_width, generated_height) <= 0:
        return 1.0
    source_ratio = source_width / source_height
    generated_ratio = generated_width / generated_height
    return abs(source_ratio - generated_ratio) / source_ratio


def _looks_like_checkerboard_content(image) -> bool:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    if width == 0 or height == 0:
        return False
    step = max(1, round(max(width, height) / 220))
    opaque = 0
    neutral_gray = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            r, g, b, a = pixels[x, y]
            if a < 220:
                continue
            opaque += 1
            if 175 <= r <= 242 and abs(r - g) <= 8 and abs(r - b) <= 8:
                neutral_gray += 1
    if opaque < 50:
        return False
    return neutral_gray / opaque > 0.18
