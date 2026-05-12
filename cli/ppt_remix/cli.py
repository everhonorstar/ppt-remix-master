from __future__ import annotations

import argparse
import binascii
import struct
from pathlib import Path

from . import __version__
from .config import load_config, load_dotenv
from .image_utils import image_kind, image_size
from .server import serve
from .workflow import assemble, prepare, preview, remix_images, rewrite_text, run


def main() -> None:
    parser = argparse.ArgumentParser(prog="ppt-remix", description="AI-assisted PPTX image and text remix tool.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--env-file", help="Load API keys and environment variables from a .env file.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prepare = sub.add_parser("prepare")
    p_prepare.add_argument("input_pptx")
    p_prepare.add_argument("--out", required=True, dest="job_dir")
    p_prepare.add_argument("--config")

    p_images = sub.add_parser("remix-images")
    p_images.add_argument("job_dir")
    p_images.add_argument("--concurrency", type=int, default=3)
    p_images.add_argument("--config")

    p_text = sub.add_parser("rewrite-text")
    p_text.add_argument("job_dir")
    p_text.add_argument("--config")

    p_preview = sub.add_parser("preview")
    p_preview.add_argument("job_dir")

    p_assemble = sub.add_parser("assemble")
    p_assemble.add_argument("job_dir")
    p_assemble.add_argument("--approved", action="store_true")

    p_run = sub.add_parser("run")
    p_run.add_argument("input_pptx")
    p_run.add_argument("--out", required=True, dest="output_dir")
    p_run.add_argument("--review", action="store_true", help="Deprecated no-op; run always stops at preview.")
    p_run.add_argument("--concurrency", type=int, default=3)
    p_run.add_argument("--config")

    p_server = sub.add_parser("server")
    p_server.add_argument("--host", default="127.0.0.1")
    p_server.add_argument("--port", type=int, default=8765)
    p_server.add_argument("--root", default=".")
    p_server.add_argument("--config")

    p_test = sub.add_parser("test-provider")
    p_test.add_argument("provider", choices=["vision", "text", "image"])
    p_test.add_argument("--config", required=True)
    p_test.add_argument("--image", default=None)

    args = parser.parse_args()
    load_dotenv(_optional_path(args.env_file))
    if args.command == "prepare":
        prepare(Path(args.input_pptx), Path(args.job_dir), _optional_path(args.config))
        print(f"Prepared job: {args.job_dir}")
    elif args.command == "remix-images":
        remix_images(Path(args.job_dir), args.concurrency, _optional_path(args.config))
        print(f"Remixed images: {args.job_dir}")
    elif args.command == "rewrite-text":
        rewrite_text(Path(args.job_dir), _optional_path(args.config))
        print(f"Rewritten text: {args.job_dir}")
    elif args.command == "preview":
        path = preview(Path(args.job_dir))
        print(f"Preview ready: {path}")
    elif args.command == "assemble":
        path = assemble(Path(args.job_dir), approved=args.approved)
        print(f"Assembled PPTX: {path}")
    elif args.command == "run":
        path = run(Path(args.input_pptx), Path(args.output_dir), _optional_path(args.config), args.concurrency)
        print(f"Result: {path}")
    elif args.command == "server":
        serve(args.host, args.port, Path(args.root), _optional_path(args.config))
    elif args.command == "test-provider":
        _test_provider(args.provider, Path(args.config), _optional_path(args.image))


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _test_provider(provider: str, config_path: Path, image_path: Path | None) -> None:
    import tempfile
    from .providers import ImageProvider, TextProvider, VisionProvider

    config = load_config(config_path)
    cleanup = None
    try:
        if provider == "vision":
            if image_path is None:
                cleanup = tempfile.TemporaryDirectory()
                image_path = Path(cleanup.name) / "test.png"
                image_path.write_bytes(_test_png_bytes())
            result = VisionProvider(config.vision_provider).analyze_image(image_path, {"test": True})
            print({"ok": True, "provider": config.vision_provider.provider, "model": config.vision_provider.model, "keys": sorted(result.keys())})
        elif provider == "text":
            result = TextProvider(config.text_provider).rewrite_text("我们需要提升内容质量", 0.15)
            print({"ok": True, "provider": config.text_provider.provider, "model": config.text_provider.model, "reply": result[:120]})
        elif provider == "image":
            cleanup = tempfile.TemporaryDirectory()
            source = Path(cleanup.name) / "source.png"
            output = Path(cleanup.name) / "output.png"
            source.write_bytes(_test_png_bytes())
            ImageProvider(config.image_provider).generate_image(
                {"remix_prompt": "Create a simple 1:1 clean presentation illustration of a blue circle on a white background."},
                source,
                output,
            )
            image_info = _validate_image_file(output)
            print({"ok": True, "provider": config.image_provider.provider, "model": config.image_provider.model, **image_info})
    except Exception as exc:
        selected = {
            "vision": config.vision_provider,
            "text": config.text_provider,
            "image": config.image_provider,
        }[provider]
        print({"ok": False, "provider": selected.provider, "model": selected.model, "error": str(exc)})
        raise SystemExit(1) from None
    finally:
        if cleanup:
            cleanup.cleanup()


def _test_png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de"
        "0000000c49444154789c63f8ffff3f0005fe02fe0def46b80000000049454e44ae426082"
    )


def _validate_image_file(path: Path) -> dict[str, int | str]:
    kind = image_kind(path)
    if not kind:
        raise ValueError(f"Image provider output is not a recognized image: {path}")
    width, height = image_size(path)
    if width is None or height is None:
        raise ValueError(f"Image provider output has unreadable dimensions: {path}")
    if kind == "png":
        _validate_png(path.read_bytes())
    return {"bytes": path.stat().st_size, "format": kind, "width": width, "height": height}


def _validate_png(data: bytes) -> None:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG output has an invalid signature")
    offset = 8
    saw_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError("PNG output has a truncated chunk header")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_start = offset + 8
        chunk_end = chunk_start + length
        crc_end = chunk_end + 4
        if crc_end > len(data):
            raise ValueError("PNG output has a truncated chunk")
        expected_crc = struct.unpack(">I", data[chunk_end:crc_end])[0]
        actual_crc = binascii.crc32(chunk_type + data[chunk_start:chunk_end]) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            raise ValueError(f"PNG output failed CRC validation for chunk {chunk_type.decode('ascii', 'replace')}")
        offset = crc_end
        if chunk_type == b"IEND":
            saw_iend = True
            break
    if not saw_iend:
        raise ValueError("PNG output is missing IEND")
    if offset != len(data):
        raise ValueError("PNG output has trailing bytes after IEND")
