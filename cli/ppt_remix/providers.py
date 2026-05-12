from __future__ import annotations

import base64
import os
import re
import shutil
from pathlib import Path
from typing import Any

import requests

from .config import ProviderConfig
from .image_utils import image_kind


class ProviderError(RuntimeError):
    pass


class VisionProvider:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def analyze_image(self, image_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        if self.config.provider == "local_mock":
            return {
                "prompt": "原创PPT配图：参考原图的主题、版式和视觉密度，生成一张适合替换原幻灯片素材的原创图片。",
                "style": "保持原图相近的插画或摄影风格，画面干净，适合教学课件使用",
                "composition": {
                    "aspect_ratio": _aspect_ratio_label(metadata),
                    "camera_angle": "参考原图视角",
                    "framing": "参考原图主体位置、景别和留白关系",
                    "depth_of_field": "参考原图清晰层次",
                },
                "character": {
                    "age": "如原图有人物，保持相近年龄段",
                    "gender": "如原图有人物，二创时自然交换性别",
                    "appearance": "保持角色功能和情绪，不复制具体长相",
                    "pose": "保留动作含义，必要时镜像左右动作",
                    "clothing": "保持场景身份合理的服装，不复制特定角色",
                },
                "environment": {
                    "location": "参考原图场景",
                    "objects": [],
                    "lighting": "参考原图光线氛围",
                    "mood": "积极、清晰、适合课件",
                },
                "color_palette": {
                    "dominant_colors": [],
                    "tone": "参考原图整体色调",
                },
                "transparency": _transparency_prompt(metadata),
                "negative_prompt": "不要文字、水印、logo，不要复制特定现有角色，不要低清晰度，不要畸形手指，不要杂乱构图",
                "remix_notes": {
                    "originality": "保留原图在PPT中的用途和版式关系，但用原创角色、场景细节和视觉元素重新表达",
                    "role_in_slide": "作为PPT页面中的视觉素材替换原图",
                    "safe_transformations": ["人物可自然交换性别", "有意义的左右动作可镜像", "场景物件可做同类替换"],
                },
                "source": metadata,
            }
        if self.config.provider == "gemini":
            return _gemini_vision(self.config, image_path, metadata)
        return _openai_compatible_vision(self.config, image_path, metadata)


class ImageProvider:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def generate_image(self, prompt: dict[str, Any], source_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.config.provider == "local_mock":
            shutil.copy2(source_path, output_path)
            return output_path
        if self.config.provider in {"openai", "openai_compatible"}:
            return _generic_image_generation(self.config, prompt, source_path, output_path)
        return _generic_image_generation(self.config, prompt, source_path, output_path)


class TextProvider:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def rewrite_text(self, text: str, tolerance: float) -> str:
        clean = text.strip()
        if not clean:
            return text
        if self.config.provider == "local_mock":
            return _local_rewrite(clean)
        if self.config.provider in {"openai", "openai_compatible", "claude"}:
            return _openai_compatible_text(self.config, clean, tolerance)
        return _openai_compatible_text(self.config, clean, tolerance)


def _api_key(config: ProviderConfig) -> str:
    if config.api_key:
        return config.api_key
    if config.api_key_env.startswith(("AIza", "sk-", "sk_")):
        return config.api_key_env
    if not config.api_key_env:
        raise ProviderError("api_key_env is required for non-local providers")
    value = os.environ.get(config.api_key_env)
    if not value:
        raise ProviderError(f"Missing API key environment variable: {config.api_key_env}")
    return value


def _with_retries(config: ProviderConfig, fn):
    last_error: Exception | None = None
    for _ in range(max(1, config.retry + 1)):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
    raise ProviderError(_sanitize_secret(str(last_error)))


def _openai_compatible_vision(config: ProviderConfig, image_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    def call():
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        url = config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {_api_key(config)}", "Content-Type": "application/json"}
        payload = {
            "model": config.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _vision_prompt_instruction(metadata),
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/*;base64,{encoded}"}},
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }
        response = requests.post(url, headers=headers, json=payload, timeout=config.timeout)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        import json

        return json.loads(content)

    result = _with_retries(config, call)
    result["source"] = metadata
    return result


def _gemini_vision(config: ProviderConfig, image_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    def call():
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        mime = _mime_type(image_path)
        base_url = (config.base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        url = f"{base_url}/v1beta/models/{config.model}:generateContent?key={_api_key(config)}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": _vision_prompt_instruction(metadata)
                        },
                        {"inline_data": {"mime_type": mime, "data": encoded}},
                    ]
                }
            ],
            "generationConfig": {
                "temperature": config.extra_options.get("temperature", 0.2),
                "response_mime_type": "application/json",
            },
        }
        response = requests.post(url, json=payload, timeout=config.timeout)
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        import json

        return json.loads(text)

    result = _with_retries(config, call)
    result["source"] = metadata
    return result


def _generic_image_generation(config: ProviderConfig, prompt: dict[str, Any], source_path: Path, output_path: Path) -> Path:
    def call():
        url = config.base_url.rstrip("/") + "/images/generations"
        headers = {"Authorization": f"Bearer {_api_key(config)}", "Content-Type": "application/json"}
        payload = {
            "model": config.model,
            "prompt": _image_generation_prompt(prompt),
            **config.extra_options,
        }
        response = requests.post(url, headers=headers, json=payload, timeout=config.timeout)
        _raise_for_status(response)
        data = response.json().get("data", [{}])[0]
        if data.get("b64_json"):
            output_path.write_bytes(base64.b64decode(data["b64_json"]))
            return output_path
        if data.get("url"):
            image = requests.get(data["url"], timeout=config.timeout)
            image.raise_for_status()
            output_path.write_bytes(image.content)
            return output_path
        raise ProviderError("Image provider response did not include b64_json or url")

    result = _with_retries(config, call)
    _preserve_source_alpha(prompt, source_path, result)
    return result


def _preserve_source_alpha(prompt: dict[str, Any], source_path: Path, output_path: Path) -> None:
    try:
        from PIL import Image
    except Exception:
        return
    try:
        if not _requires_transparent_background(prompt.get("transparency")):
            return
        with Image.open(source_path) as source_image:
            source = source_image.copy()
        if source.mode != "RGBA":
            return
        with Image.open(output_path) as generated_image:
            generated = generated_image.copy()
        if _has_meaningful_alpha(generated):
            return
        alpha = source.getchannel("A")
        if generated.size != source.size:
            alpha = alpha.resize(generated.size, Image.Resampling.LANCZOS)
        output = generated.convert("RGBA")
        output.putalpha(alpha)
        output.save(output_path)
    except Exception:
        return


def _requires_transparent_background(transparency: Any) -> bool:
    return isinstance(transparency, dict) and bool(transparency.get("requires_transparent_background"))


def _has_meaningful_alpha(image) -> bool:
    if image.mode not in {"RGBA", "LA"}:
        return False
    alpha_min, alpha_max = image.getchannel("A").getextrema()
    return alpha_min < 250 and alpha_max > 0


def _vision_prompt_instruction(metadata: dict[str, Any]) -> str:
    aspect_ratio = _aspect_ratio_label(metadata)
    transparency = _transparency_prompt(metadata)
    transparency_instruction = (
        "原图包含透明区域。JSON 的 transparency.requires_transparent_background 必须为 true；"
        "prompt/style/environment/negative_prompt 中必须明确要求真实透明 PNG alpha 背景、无白色画布、无实心背景。"
        "如果画面里出现灰白棋盘格、透明格、马赛克格、checkerboard 或 transparent grid，"
        "那只是查看器用来表示透明的占位，不属于图片内容；禁止把它描述为背景、材质、环境或图案，"
        "禁止写入 environment.objects/color_palette/prompt。negative_prompt 必须包含："
        "棋盘格、透明格子、马赛克背景、灰白格子、checkerboard、transparent grid。"
        if transparency["requires_transparent_background"]
        else "原图不需要透明背景。JSON 的 transparency.requires_transparent_background 可以为 false。"
    )
    return (
        "解构这张PPT图片，生成适合ChatGPT或其他生图模型生成原创图片的 JSON prompt，"
        "用于参考这张图片重新创作，不要直接生成图片。只返回合法 JSON，不要 Markdown，不要解释。\n\n"
        "要求：详细到可以直接指导生图；保留原图的主题功能、构图关系、视觉风格、色彩和课件适配性，"
        "但表达为原创图片提示，不要要求复制原图、不要提及受版权保护的具体角色或品牌。"
        "如果有人物，记录年龄段、性别、外观、动作、服装、情绪和故事角色；用于二创替换时，"
        "可以在不改变教学含义的前提下自然交换人物性别，并镜像有意义的左右动作。"
        "不要镜像或生成可读文字，避免乱码文字。"
        f"{transparency_instruction}\n\n"
        "必须返回这些顶层字段：\n"
        "{\n"
        '  "prompt": "一段完整中文生图主提示，开头建议使用：原创...；描述主体、动作、场景、氛围和用途",\n'
        '  "style": "风格描述，例如高质量3D卡通动画电影风格/扁平插画/写实照片等，包含材质、光线、清晰度",\n'
        '  "composition": {\n'
        f'    "aspect_ratio": "{aspect_ratio}",\n'
        '    "camera_angle": "视角",\n'
        '    "framing": "景别、主体位置、前中后景关系",\n'
        '    "depth_of_field": "景深和清晰层次"\n'
        "  },\n"
        '  "character": {\n'
        '    "age": "没有人物则写无",\n'
        '    "gender": "没有人物则写无；有人物则写原图性别，并注明二创可自然交换性别",\n'
        '    "appearance": "脸型、发型、表情、气质等，不复制具体人物",\n'
        '    "pose": "姿势、手部动作、朝向，注明左右关系",\n'
        '    "clothing": "服装和配饰"\n'
        "  },\n"
        '  "environment": {\n'
        '    "location": "地点",\n'
        '    "objects": ["画面中的关键物件"],\n'
        '    "lighting": "光线",\n'
        '    "mood": "情绪氛围"\n'
        "  },\n"
        '  "color_palette": {\n'
        '    "dominant_colors": ["主要颜色"],\n'
        '    "tone": "色调，例如低饱和、柔和、明亮"\n'
        "  },\n"
        '  "transparency": {\n'
        f'    "has_alpha": {str(transparency["has_alpha"]).lower()},\n'
        f'    "alpha_min": {transparency["alpha_min"] if transparency["alpha_min"] is not None else "null"},\n'
        f'    "alpha_max": {transparency["alpha_max"] if transparency["alpha_max"] is not None else "null"},\n'
        f'    "transparent_pixel_ratio": {transparency["transparent_pixel_ratio"]},\n'
        f'    "near_transparent_pixel_ratio": {transparency["near_transparent_pixel_ratio"]},\n'
        f'    "transparent_edge_ratio": {transparency["transparent_edge_ratio"]},\n'
        f'    "requires_transparent_background": {str(transparency["requires_transparent_background"]).lower()},\n'
        f'    "background_instruction": "{transparency["background_instruction"]}",\n'
        f'    "classification": "{transparency["classification"]}"\n'
        "  },\n"
        '  "negative_prompt": "不要出现的内容：文字、水印、logo、乱码、复制特定角色、畸形手指、杂乱背景等；透明图还必须排除棋盘格、透明格子、马赛克背景、灰白格子、checkerboard、transparent grid",\n'
        '  "remix_notes": {\n'
        '    "originality": "如何保持原创而不是复制原图",\n'
        '    "role_in_slide": "该图在PPT页面中的作用",\n'
        '    "safe_transformations": ["可做的二创变化，例如性别交换、左右动作镜像、细节替换"]\n'
        "  }\n"
        "}"
    )


def _image_generation_prompt(prompt: dict[str, Any]) -> str:
    parts: list[str] = []
    main = prompt.get("prompt") or prompt.get("remix_prompt")
    if main:
        parts.append(str(main))
    if prompt.get("style"):
        parts.append(f"风格：{prompt['style']}")
    composition = prompt.get("composition")
    if isinstance(composition, dict):
        parts.append("构图：" + _dict_to_phrase(composition))
    character = prompt.get("character")
    if isinstance(character, dict):
        parts.append("角色：" + _dict_to_phrase(character))
    environment = prompt.get("environment")
    if isinstance(environment, dict):
        parts.append("环境：" + _dict_to_phrase(environment))
    color_palette = prompt.get("color_palette")
    if isinstance(color_palette, dict):
        parts.append("色彩：" + _dict_to_phrase(color_palette))
    transparency = prompt.get("transparency")
    if isinstance(transparency, dict):
        parts.append("透明背景：" + _dict_to_phrase(transparency))
        if transparency.get("requires_transparent_background"):
            parts.append(
                "背景必须是真实 PNG alpha 透明像素，主体之外不要生成白底、纯色底、纸张底、画布底、"
                "灰白棋盘格、透明格子、马赛克背景、checkerboard 或 transparent grid。"
            )
    remix_notes = prompt.get("remix_notes")
    if isinstance(remix_notes, dict):
        parts.append("二创要求：" + _dict_to_phrase(remix_notes))
    target_width = prompt.get("target_width")
    target_height = prompt.get("target_height")
    if target_width and target_height:
        parts.append(f"输出画面比例参考原图 {target_width}:{target_height}，适合作为PPT素材替换。")
    parts.append("生成原创图片，不要复制原图，不要包含可读文字、水印、logo 或品牌标识。")
    negative = prompt.get("negative_prompt")
    if negative:
        parts.append(f"负面提示：{negative}")
    return "\n".join(parts)


def _transparency_prompt(metadata: dict[str, Any]) -> dict[str, Any]:
    transparency = metadata.get("transparency")
    if isinstance(transparency, dict):
        return {
            "has_alpha": bool(transparency.get("has_alpha")),
            "alpha_min": transparency.get("alpha_min"),
            "alpha_max": transparency.get("alpha_max"),
            "transparent_pixel_ratio": transparency.get("transparent_pixel_ratio", 0.0),
            "near_transparent_pixel_ratio": transparency.get("near_transparent_pixel_ratio", 0.0),
            "transparent_edge_ratio": transparency.get("transparent_edge_ratio", 0.0),
            "requires_transparent_background": bool(transparency.get("requires_transparent_background")),
            "background_instruction": transparency.get("background_instruction") or "keep opaque background",
            "classification": transparency.get("classification") or "opaque",
        }
    return {
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


def _dict_to_phrase(value: dict[str, Any]) -> str:
    phrases = []
    for key, item in value.items():
        if isinstance(item, list):
            rendered = "、".join(str(x) for x in item)
        elif isinstance(item, dict):
            rendered = _dict_to_phrase(item)
        else:
            rendered = str(item)
        phrases.append(f"{key}={rendered}")
    return "；".join(phrases)


def _aspect_ratio_label(metadata: dict[str, Any]) -> str:
    width = metadata.get("width")
    height = metadata.get("height")
    if not width or not height:
        return "参考原图比例"
    ratio = width / height
    if abs(ratio - 16 / 9) < 0.04:
        return "16:9"
    if abs(ratio - 9 / 16) < 0.04:
        return "9:16"
    if abs(ratio - 1) < 0.04:
        return "1:1"
    if abs(ratio - 2 / 3) < 0.04:
        return "2:3"
    if abs(ratio - 3 / 2) < 0.04:
        return "3:2"
    return f"{width}:{height}"


def _openai_compatible_text(config: ProviderConfig, text: str, tolerance: float) -> str:
    def call():
        url = config.base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {_api_key(config)}", "Content-Type": "application/json"}
        instruction = (
            "Rewrite PPT text in Chinese or the source language. Preserve meaning, paragraph count, "
            "line-break intent, numbers, names, and placeholders. Do not copy the original wording. "
            f"Keep length within {int(tolerance * 100)}% of the source when possible. "
            "Return only the rewritten text itself. Do not include labels, explanations, markdown, quotes, or length notes."
        )
        if config.provider == "claude":
            messages = [{"role": "user", "content": f"{instruction}\n\nSource text:\n{text}"}]
        else:
            messages = [
                {"role": "system", "content": instruction},
                {"role": "user", "content": text},
            ]
        payload = {
            "model": config.model,
            "messages": messages,
            "temperature": config.extra_options.get("temperature", 0.6),
        }
        response = requests.post(url, headers=headers, json=payload, timeout=config.timeout)
        _raise_for_status(response)
        return response.json()["choices"][0]["message"]["content"].strip()

    return _with_retries(config, call)


def _local_rewrite(text: str) -> str:
    replacements = [
        ("我们", "咱们"),
        ("可以", "能够"),
        ("需要", "应当"),
        ("提升", "提高"),
        ("完成", "做好"),
        ("重要", "关键"),
        ("方法", "方式"),
        ("内容", "信息"),
    ]
    result = text
    for old, new in replacements:
        result = result.replace(old, new)
    if result == text:
        result = f"{text}"
    return result


def _mime_type(path: Path) -> str:
    kind = image_kind(path)
    if kind == "jpeg":
        return "image/jpeg"
    if kind == "png":
        return "image/png"
    if kind == "gif":
        return "image/gif"
    if kind == "webp":
        return "image/webp"
    return "application/octet-stream"


def _sanitize_secret(value: str) -> str:
    value = re.sub(r"key=([^&\\s)]+)", "key=<redacted>", value)
    value = re.sub(r"AIza[0-9A-Za-z_-]+", "<redacted>", value)
    value = re.sub(r"sk-[0-9A-Za-z_-]+", "<redacted>", value)
    value = re.sub(r"sk_[0-9A-Za-z_-]+", "<redacted>", value)
    return value


def _raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text[:1000]
        raise ProviderError(f"{exc}; response={_sanitize_secret(body)}") from None
