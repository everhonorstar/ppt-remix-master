from __future__ import annotations

import concurrent.futures
import html
import re
import shutil
from pathlib import Path

from .config import RemixConfig, load_config
from .json_io import read_json, write_json
from .pptx_ops import assemble_pptx, build_manifests, unpack_pptx
from .providers import ImageProvider, TextProvider, VisionProvider


def prepare(input_pptx: Path, job_dir: Path, config_path: Path | None = None) -> None:
    config = load_config(config_path)
    unpack_pptx(input_pptx, job_dir)
    build_manifests(job_dir, config)


def remix_images(job_dir: Path, concurrency: int = 3, config_path: Path | None = None) -> None:
    config = load_config(config_path)
    vision = VisionProvider(config.vision_provider)
    image = ImageProvider(config.image_provider)
    manifest = read_json(job_dir / "image_manifest.json", [])
    generated_dir = job_dir / "generated_images"
    prompts_dir = job_dir / "image_prompts"
    cache_root = _asset_cache_root(job_dir)
    generated_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    sha_to_replacement = {
        item["sha256"]: item.get("replacement_path")
        for item in manifest
        if item.get("replacement_path")
    }

    def process(item: dict) -> dict:
        if item.get("suggested_skip"):
            item["status"] = "skipped"
            return item
        if item.get("duplicate_of"):
            original = next((x for x in manifest if x["media_name"] == item["duplicate_of"]), None)
            if original and original.get("replacement_path"):
                item["replacement_path"] = original["replacement_path"]
            item["status"] = "duplicate"
            return item
        if sha_to_replacement.get(item["sha256"]):
            item["replacement_path"] = sha_to_replacement[item["sha256"]]
            item["status"] = "duplicate"
            return item
        try:
            prompt_path = prompts_dir / f"{Path(item['media_name']).stem}.json"
            output = generated_dir / item["media_name"]
            cache_hit = _restore_cached_asset(cache_root, item, prompt_path, output)
            if cache_hit:
                item["prompt_path"] = str(prompt_path.relative_to(job_dir))
                item["replacement_path"] = str(output.relative_to(job_dir))
                item["status"] = "cached"
                sha_to_replacement[item["sha256"]] = item["replacement_path"]
                return item
            source = job_dir / item["exported_path"]
            analysis = vision.analyze_image(source, item)
            prompt = _build_remix_prompt(analysis, item)
            write_json(prompt_path, prompt)
            image.generate_image(prompt, source, output)
            _store_cached_asset(cache_root, item, prompt_path, output)
            item["prompt_path"] = str(prompt_path.relative_to(job_dir))
            item["replacement_path"] = str(output.relative_to(job_dir))
            item["status"] = "generated"
            sha_to_replacement[item["sha256"]] = item["replacement_path"]
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
        return item

    pending = [item for item in manifest if item.get("status") == "pending"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        updates = list(executor.map(process, pending))
    by_name = {item["media_name"]: item for item in manifest}
    for item in updates:
        by_name[item["media_name"]] = item
    for item in manifest:
        if item.get("duplicate_of") and not item.get("replacement_path"):
            original = by_name.get(item["duplicate_of"])
            if original and original.get("replacement_path"):
                item["replacement_path"] = original["replacement_path"]
                item["status"] = "duplicate"
    write_json(job_dir / "image_manifest.json", manifest)
    _update_status(job_dir, "images_remixed")


def _asset_cache_root(job_dir: Path) -> Path:
    cache_name = _cache_name_from_job(job_dir.name)
    return job_dir.parent / "cache" / cache_name


def _cache_name_from_job(name: str) -> str:
    stem = Path(name).stem.strip()
    stem = re.sub(r"[（(［\[]\s*\d+\s*[）)］\]]$", "", stem).strip()
    stem = re.sub(r"[\s._-]*(?:[Pp])?\d+$", "", stem).strip()
    stem = stem or Path(name).stem.strip() or "default"
    return _safe_cache_name(stem)


def _safe_cache_name(value: str) -> str:
    return re.sub(r"[/:\\]+", "_", value)


def _cache_entry_dir(cache_root: Path, item: dict) -> Path:
    return cache_root / item["sha256"]


def _restore_cached_asset(cache_root: Path, item: dict, prompt_path: Path, output_path: Path) -> bool:
    entry_dir = _cache_entry_dir(cache_root, item)
    cached_prompt = entry_dir / "prompt.json"
    cached_image = entry_dir / f"generated{Path(item['media_name']).suffix.lower()}"
    cached_meta = entry_dir / "metadata.json"
    if not (cached_prompt.exists() and cached_image.exists() and cached_meta.exists()):
        return False
    shutil.copy2(cached_prompt, prompt_path)
    shutil.copy2(cached_image, output_path)
    return True


def _store_cached_asset(cache_root: Path, item: dict, prompt_path: Path, output_path: Path) -> None:
    if not (prompt_path.exists() and output_path.exists()):
        return
    entry_dir = _cache_entry_dir(cache_root, item)
    entry_dir.mkdir(parents=True, exist_ok=True)
    cached_prompt = entry_dir / "prompt.json"
    cached_image = entry_dir / f"generated{Path(item['media_name']).suffix.lower()}"
    shutil.copy2(prompt_path, cached_prompt)
    shutil.copy2(output_path, cached_image)
    write_json(
        entry_dir / "metadata.json",
        {
            "source_sha256": item.get("sha256"),
            "source_media": item.get("media_name"),
            "width": item.get("width"),
            "height": item.get("height"),
            "transparency": item.get("transparency"),
        },
    )


def rewrite_text(job_dir: Path, config_path: Path | None = None) -> None:
    config = load_config(config_path)
    provider = TextProvider(config.text_provider)
    manifest = read_json(job_dir / "text_manifest.json", [])
    for item in manifest:
        if item.get("status") not in {"pending", ""}:
            continue
        try:
            item["new_text"] = provider.rewrite_text(item["original_text"], config.text_length_tolerance)
            item["new_char_count"] = len(item["new_text"])
            item["status"] = "rewritten"
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
    write_json(job_dir / "text_manifest.json", manifest)
    _update_status(job_dir, "text_rewritten")


def preview(job_dir: Path) -> Path:
    images = read_json(job_dir / "image_manifest.json", [])
    texts = read_json(job_dir / "text_manifest.json", [])
    preview_dir = job_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    for item in images:
        for key in ("exported_path", "replacement_path"):
            if item.get(key):
                source = job_dir / item[key]
                target_dir = preview_dir / ("original_images" if key == "exported_path" else "generated_images")
                target_dir.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    shutil.copy2(source, target_dir / source.name)
    html_path = preview_dir / "index.html"
    html_path.write_text(_preview_html(images, texts), encoding="utf-8")
    write_json(preview_dir / "summary.json", _summary(images, texts))
    _update_status(job_dir, "preview_ready")
    return html_path


def assemble(job_dir: Path, approved: bool) -> Path:
    return assemble_pptx(job_dir, approved=approved)


def run(input_pptx: Path, output_dir: Path, config_path: Path | None = None, concurrency: int = 3) -> Path:
    job_dir = output_dir / input_pptx.stem
    prepare(input_pptx, job_dir, config_path)
    remix_images(job_dir, concurrency, config_path)
    rewrite_text(job_dir, config_path)
    return preview(job_dir)


def _build_remix_prompt(analysis: dict, item: dict) -> dict:
    _validate_vision_prompt(analysis)
    prompt = {
        "source_media": item["media_name"],
        "target_width": item.get("width"),
        "target_height": item.get("height"),
        **analysis,
    }
    prompt.pop("source", None)
    if isinstance(item.get("transparency"), dict):
        prompt["transparency"] = item["transparency"]
    _enforce_transparent_prompt_rules(prompt)
    return prompt


def _enforce_transparent_prompt_rules(prompt: dict) -> None:
    transparency = prompt.get("transparency")
    if not isinstance(transparency, dict) or not transparency.get("requires_transparent_background"):
        return
    rule = (
        "真实 PNG alpha 透明背景；主体之外必须是透明像素，不是可见背景。"
        "不要生成灰白棋盘格、透明格子、马赛克背景、checkerboard、transparent grid、白底或纯色底。"
    )
    prompt["prompt"] = _append_once(str(prompt.get("prompt", "")), rule)
    prompt["style"] = _append_once(str(prompt.get("style", "")), "真实透明 alpha 通道，边缘干净，不带透明预览棋盘格。")
    negative = str(prompt.get("negative_prompt", ""))
    prompt["negative_prompt"] = _append_once(
        negative,
        "棋盘格、透明格子、马赛克背景、灰白格子、checkerboard、transparent grid、白色画布、灰色画布、实心背景",
    )
    environment = prompt.get("environment")
    if isinstance(environment, dict):
        location = str(environment.get("location", ""))
        if location and location not in {"无", "透明背景", "无（透明背景）"}:
            environment["location"] = _strip_transparency_preview_words(location)
        else:
            environment["location"] = "真实透明 alpha 背景"
        objects = environment.get("objects")
        if isinstance(objects, list):
            environment["objects"] = [
                obj for obj in objects if not _mentions_transparency_preview(str(obj))
            ]


def _append_once(text: str, addition: str) -> str:
    if addition in text:
        return text
    return f"{text}；{addition}" if text else addition


def _strip_transparency_preview_words(text: str) -> str:
    for word in ("灰白棋盘格", "棋盘格", "透明格子", "马赛克背景", "灰白格子", "checkerboard", "transparent grid"):
        text = text.replace(word, "")
    return text.strip(" ；,，、") or "真实透明 alpha 背景"


def _mentions_transparency_preview(text: str) -> bool:
    lowered = text.lower()
    return any(
        word in lowered
        for word in ("棋盘格", "透明格子", "马赛克背景", "灰白格子", "checkerboard", "transparent grid")
    )


def _validate_vision_prompt(analysis: dict) -> None:
    required = {
        "prompt": str,
        "style": str,
        "composition": dict,
        "character": dict,
        "environment": dict,
        "color_palette": dict,
        "transparency": dict,
        "negative_prompt": str,
        "remix_notes": dict,
    }
    missing = [key for key, expected in required.items() if not isinstance(analysis.get(key), expected) or not analysis.get(key)]
    if missing:
        raise ValueError(f"Vision response missing required structured prompt fields: {', '.join(missing)}")


def _preview_html(images: list[dict], texts: list[dict]) -> str:
    image_rows = []
    for item in images:
        original = f"original_images/{html.escape(Path(item.get('exported_path', '')).name)}" if item.get("exported_path") else ""
        generated = f"generated_images/{html.escape(Path(item.get('replacement_path', '')).name)}" if item.get("replacement_path") else ""
        original_img = f'<img src="{original}">' if original else ""
        generated_img = f'<img src="{generated}">' if generated else ""
        image_rows.append(
            "<tr>"
            f"<td>{html.escape(item['media_name'])}</td>"
            f"<td>{html.escape(item.get('status', ''))}</td>"
            f"<td>{html.escape(item.get('skip_reason', ''))}</td>"
            f"<td>{original_img}</td>"
            f"<td>{generated_img}</td>"
            "</tr>"
        )
    text_rows = [
        "<tr>"
        f"<td>{html.escape(str(item.get('slide')))}</td>"
        f"<td>{html.escape(item.get('original_text', ''))}</td>"
        f"<td>{html.escape(item.get('new_text', ''))}</td>"
        f"<td>{html.escape(item.get('status', ''))}</td>"
        "</tr>"
        for item in texts
    ]
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>PPT Remix Preview</title>"
        "<style>body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:24px;color:#1f2937}"
        "table{border-collapse:collapse;width:100%;margin:16px 0}td,th{border:1px solid #d1d5db;padding:8px;vertical-align:top}"
        "img{max-width:220px;max-height:160px}h1,h2{margin-top:24px}</style></head><body>"
        "<h1>PPT Remix Preview</h1><h2>Images</h2><table><tr><th>Media</th><th>Status</th><th>Skip Reason</th><th>Original</th><th>Generated</th></tr>"
        + "".join(image_rows)
        + "</table><h2>Text</h2><table><tr><th>Slide</th><th>Original</th><th>Rewritten</th><th>Status</th></tr>"
        + "".join(text_rows)
        + "</table></body></html>"
    )


def _summary(images: list[dict], texts: list[dict]) -> dict:
    return {
        "images": _counts(images),
        "texts": _counts(texts),
    }


def _counts(items: list[dict]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        status = item.get("status", "unknown")
        result[status] = result.get(status, 0) + 1
    return result


def _update_status(job_dir: Path, stage: str) -> None:
    status = read_json(job_dir / "job_status.json", {})
    status["stage"] = stage
    write_json(job_dir / "job_status.json", status)
