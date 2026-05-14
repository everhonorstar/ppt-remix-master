from __future__ import annotations

import hashlib
import re
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
from xml.etree import ElementTree as ET

from .config import RemixConfig
from .image_utils import IMAGE_EXTENSIONS, analyze_transparency, image_size, likely_skip_image
from .json_io import read_json, write_json

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def ensure_pptx(input_path: Path) -> None:
    if input_path.suffix.lower() != ".pptx":
        raise ValueError("Only .pptx files are supported in v1")
    if not zipfile.is_zipfile(input_path):
        raise ValueError(f"Not a valid PPTX zip package: {input_path}")


def unpack_pptx(input_path: Path, job_dir: Path) -> Path:
    ensure_pptx(input_path)
    job_dir.mkdir(parents=True, exist_ok=True)
    status = read_json(job_dir / "job_status.json", {})
    if input_path.name != "input.pptx":
        status["source_filename"] = input_path.name
        status["source_stem"] = input_path.stem
        write_json(job_dir / "job_status.json", status)
    source = job_dir / "input.pptx"
    if input_path.resolve() != source.resolve():
        shutil.copy2(input_path, source)
    extracted = job_dir / "work" / "pptx"
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    with zipfile.ZipFile(source) as archive:
        archive.extractall(extracted)
    return extracted


def build_manifests(job_dir: Path, config: RemixConfig) -> None:
    root = job_dir / "work" / "pptx"
    if not root.exists():
        raise FileNotFoundError("PPTX has not been prepared yet")
    images = _build_image_manifest(job_dir, root, config)
    texts = _build_text_manifest(job_dir, root)
    write_json(job_dir / "image_manifest.json", images)
    write_json(job_dir / "text_manifest.json", texts)
    status = read_json(job_dir / "job_status.json", {})
    status.update({"stage": "prepared", "image_count": len(images), "text_count": len(texts)})
    write_json(job_dir / "job_status.json", status)


def _build_image_manifest(job_dir: Path, root: Path, config: RemixConfig) -> list[dict]:
    media_root = root / "ppt" / "media"
    exported_root = job_dir / "exported_images"
    exported_root.mkdir(parents=True, exist_ok=True)
    media_items: dict[str, dict] = {}
    hash_first: dict[str, str] = {}
    if media_root.exists():
        for media_file in sorted(media_root.iterdir()):
            if media_file.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            digest = hashlib.sha256(media_file.read_bytes()).hexdigest()
            width, height = image_size(media_file)
            transparency = analyze_transparency(media_file)
            skip, reason = likely_skip_image(media_file.name, width, height, config.min_image_width, config.min_image_height)
            exported = exported_root / media_file.name
            shutil.copy2(media_file, exported)
            media_items[media_file.name] = {
                "media_name": media_file.name,
                "media_path": f"ppt/media/{media_file.name}",
                "exported_path": str(exported.relative_to(job_dir)),
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 6) if width and height else None,
                "transparency": transparency,
                "sha256": digest,
                "duplicate_of": hash_first.get(digest),
                "suggested_skip": skip,
                "skip_reason": reason,
                "references": [],
                "status": "pending" if not skip and digest not in hash_first else "skipped" if skip else "duplicate",
            }
            hash_first.setdefault(digest, media_file.name)
    _attach_image_references(root, media_items)
    return list(media_items.values())


def _attach_image_references(root: Path, media_items: dict[str, dict]) -> None:
    slides_root = root / "ppt" / "slides"
    for slide_path in sorted(slides_root.glob("slide*.xml")):
        slide_num = _number_from_name(slide_path.stem)
        rel_path = slides_root / "_rels" / f"{slide_path.name}.rels"
        rels = _read_relationships(rel_path)
        try:
            tree = ET.parse(slide_path)
        except ET.ParseError:
            continue
        for pic in tree.findall(".//p:pic", NS):
            blip = pic.find(".//a:blip", NS)
            if blip is None:
                continue
            rid = blip.attrib.get(f"{{{NS['r']}}}embed") or blip.attrib.get(f"{{{NS['r']}}}link")
            if not rid or rid not in rels:
                continue
            target = rels[rid]
            media_name = Path(target).name
            if media_name in media_items:
                reference = {"slide": slide_num, "relationship_id": rid, "target": target}
                src_rect = _src_rect(pic)
                if src_rect:
                    reference["src_rect"] = src_rect
                media_items[media_name]["references"].append(reference)


def _src_rect(pic: ET.Element) -> dict[str, int] | None:
    node = pic.find(".//a:srcRect", NS)
    if node is None:
        return None
    rect: dict[str, int] = {}
    for key in ("l", "t", "r", "b"):
        value = node.attrib.get(key)
        if value is None:
            continue
        try:
            rect[key] = int(value)
        except ValueError:
            continue
    return rect or None


def _read_relationships(rel_path: Path) -> dict[str, str]:
    if not rel_path.exists():
        return {}
    tree = ET.parse(rel_path)
    result = {}
    for rel in tree.getroot():
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rid and target:
            result[rid] = target
    return result


def _build_text_manifest(job_dir: Path, root: Path) -> list[dict]:
    del job_dir
    items: list[dict] = []
    slides_root = root / "ppt" / "slides"
    for slide_path in sorted(slides_root.glob("slide*.xml")):
        slide_num = _number_from_name(slide_path.stem)
        tree = ET.parse(slide_path)
        idx = 0
        for node in tree.findall(".//a:t", NS):
            text = node.text or ""
            if not text.strip():
                continue
            idx += 1
            items.append(
                {
                    "id": f"slide{slide_num}_text{idx}",
                    "slide": slide_num,
                    "xml_path": str(slide_path.relative_to(root)),
                    "original_text": text,
                    "new_text": "",
                    "char_count": len(text),
                    "status": "pending",
                }
            )
    return items


def assemble_pptx(job_dir: Path, approved: bool) -> Path:
    if not approved:
        raise ValueError("assemble requires --approved")
    input_pptx = job_dir / "input.pptx"
    if input_pptx.exists():
        unpack_pptx(input_pptx, job_dir)
    root = job_dir / "work" / "pptx"
    if not root.exists():
        raise FileNotFoundError("PPTX work directory missing")
    _apply_generated_images(job_dir, root)
    _apply_rewritten_text(job_dir, root)
    output_dir = job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    status = read_json(job_dir / "job_status.json", {})
    output = output_dir / _remixed_filename(job_dir, status)
    _zip_dir(root, output)
    status["stage"] = "assembled"
    status["output_pptx"] = str(output)
    write_json(job_dir / "job_status.json", status)
    return output


def _remixed_filename(job_dir: Path, status: dict) -> str:
    source_filename = status.get("source_filename")
    if isinstance(source_filename, str) and source_filename.strip():
        source_stem = Path(source_filename).stem.strip()
    else:
        source_stem = job_dir.name.strip()
    source_stem = source_stem or "remixed"
    return f"{source_stem}_remixed.pptx"


def _apply_generated_images(job_dir: Path, root: Path) -> None:
    manifest = read_json(job_dir / "image_manifest.json", [])
    by_name = {item["media_name"]: item for item in manifest}
    for item in manifest:
        replacement = item.get("replacement_path")
        duplicate_of = item.get("duplicate_of")
        if not replacement and duplicate_of and duplicate_of in by_name:
            replacement = by_name[duplicate_of].get("replacement_path")
        if not replacement:
            continue
        source = job_dir / replacement
        target = root / item["media_path"]
        alpha_reference = job_dir / item.get("exported_path", "")
        if source.exists() and target.exists():
            _copy_image_preserving_alpha(source, target, alpha_reference, item)


def _apply_rewritten_text(job_dir: Path, root: Path) -> None:
    manifest = read_json(job_dir / "text_manifest.json", [])
    grouped: dict[str, list[dict]] = {}
    for item in manifest:
        if item.get("new_text"):
            grouped.setdefault(item["xml_path"], []).append(item)
    for xml_path, entries in grouped.items():
        path = root / xml_path
        xml = path.read_text(encoding="utf-8")
        replacements = iter(entries)

        def replace_text_node(match: re.Match[str]) -> str:
            original_text = match.group(2)
            if not original_text.strip():
                return match.group(0)
            try:
                entry = next(replacements)
            except StopIteration:
                return match.group(0)
            return f"{match.group(1)}{escape(entry['new_text'])}{match.group(3)}"

        updated = re.sub(r"(<a:t\b[^>]*>)(.*?)(</a:t>)", replace_text_node, xml, flags=re.DOTALL)
        path.write_text(updated, encoding="utf-8")


def _copy_image_preserving_alpha(source: Path, target: Path, alpha_reference: Path, item: dict | object) -> None:
    try:
        from PIL import Image
    except Exception:
        shutil.copy2(source, target)
        return
    try:
        transparency = item.get("transparency") if isinstance(item, dict) else item
        alpha_source = alpha_reference if alpha_reference.exists() else target
        if not _requires_transparent_background(transparency):
            shutil.copy2(source, target)
            return
        with Image.open(alpha_source) as original_image:
            original = original_image.copy()
        with Image.open(source) as generated_image:
            generated = generated_image.copy()
        if _has_meaningful_alpha(generated):
            output = generated.convert("RGBA")
        elif original.mode == "RGBA":
            alpha = original.getchannel("A")
            if generated.size != original.size:
                alpha = alpha.resize(generated.size, Image.Resampling.LANCZOS)
            output = generated.convert("RGBA")
            output.putalpha(alpha)
        else:
            shutil.copy2(source, target)
            return
        if isinstance(item, dict):
            output = _fit_transparent_subject_to_crop(output, item)
        output.save(target)
    except Exception:
        shutil.copy2(source, target)


def _requires_transparent_background(transparency: object) -> bool:
    return isinstance(transparency, dict) and bool(transparency.get("requires_transparent_background"))


def _has_meaningful_alpha(image) -> bool:
    if image.mode not in {"RGBA", "LA"}:
        return False
    alpha_min, alpha_max = image.getchannel("A").getextrema()
    return alpha_min < 250 and alpha_max > 0


def _fit_transparent_subject_to_crop(image, item: dict):
    from PIL import Image

    crop = _visible_crop_rect(item, image.size)
    if crop is None:
        return image
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return image
    left, top, right, bottom = crop
    crop_width = max(1, right - left)
    crop_height = max(1, bottom - top)
    pad_x = max(2, round(crop_width * 0.02))
    pad_y = max(2, round(crop_height * 0.02))
    safe = (left + pad_x, top + pad_y, right - pad_x, bottom - pad_y)
    if _bbox_inside(bbox, safe):
        return image

    bbox_width = max(1, bbox[2] - bbox[0])
    bbox_height = max(1, bbox[3] - bbox[1])
    safe_width = max(1, safe[2] - safe[0])
    safe_height = max(1, safe[3] - safe[1])
    scale = min(1.0, safe_width / bbox_width, safe_height / bbox_height)
    subject = image.crop(bbox)
    if scale < 1.0:
        new_size = (max(1, round(subject.width * scale)), max(1, round(subject.height * scale)))
        subject = subject.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    target_left = round(safe[0] + (safe_width - subject.width) / 2)
    target_top = round(safe[1] + (safe_height - subject.height) / 2)
    canvas.alpha_composite(subject, (target_left, target_top))
    return canvas


def _bbox_inside(bbox: tuple[int, int, int, int], rect: tuple[int, int, int, int]) -> bool:
    return bbox[0] >= rect[0] and bbox[1] >= rect[1] and bbox[2] <= rect[2] and bbox[3] <= rect[3]


def _visible_crop_rect(item: dict, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    refs = item.get("references")
    if not isinstance(refs, list):
        return None
    rects = [ref.get("src_rect") for ref in refs if isinstance(ref, dict) and isinstance(ref.get("src_rect"), dict)]
    if not rects:
        return None
    width, height = size
    left = max(_crop_value(rect, "l", width, 0) for rect in rects)
    top = max(_crop_value(rect, "t", height, 0) for rect in rects)
    right = min(width - _crop_value(rect, "r", width, 0) for rect in rects)
    bottom = min(height - _crop_value(rect, "b", height, 0) for rect in rects)
    if left >= right or top >= bottom:
        return None
    return (left, top, right, bottom)


def _crop_value(rect: dict, key: str, length: int, default: int) -> int:
    value = rect.get(key, default)
    try:
        return round(length * max(0, int(value)) / 100000)
    except (TypeError, ValueError):
        return default


def _zip_dir(source_dir: Path, output_path: Path) -> None:
    if output_path.exists():
        output_path.unlink()
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())


def _number_from_name(value: str) -> int | None:
    match = re.search(r"(\d+)$", value)
    return int(match.group(1)) if match else None
