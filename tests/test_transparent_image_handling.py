from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

from ppt_remix.pptx_ops import _copy_image_preserving_alpha  # noqa: E402
from ppt_remix.image_quality import stabilize_transparent_replacement  # noqa: E402


class TransparentImageHandlingTests(unittest.TestCase):
    def test_generated_alpha_is_not_overwritten_by_source_alpha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            alpha_reference = root / "original.png"
            target = root / "target.png"

            _rgba_with_box(alpha_reference, (100, 100), (10, 10, 40, 40), (255, 0, 0, 255))
            _rgba_with_box(source, (100, 100), (60, 0, 90, 90), (0, 0, 255, 255))
            target.write_bytes(alpha_reference.read_bytes())

            _copy_image_preserving_alpha(source, target, alpha_reference, _transparent_item())

            result = Image.open(target).convert("RGBA")
            self.assertEqual(result.getchannel("A").getbbox(), (60, 0, 90, 90))

    def test_transparent_subject_is_fit_inside_src_rect_crop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            alpha_reference = root / "original.png"
            target = root / "target.png"

            _rgba_with_box(alpha_reference, (100, 100), (0, 0, 100, 100), (255, 0, 0, 255))
            _rgba_with_box(source, (100, 100), (0, 0, 100, 100), (0, 0, 255, 255))
            target.write_bytes(alpha_reference.read_bytes())
            item = _transparent_item(
                references=[
                    {
                        "slide": 1,
                        "relationship_id": "rId1",
                        "target": "../media/image1.png",
                        "src_rect": {"t": 10000, "b": 10000},
                    }
                ]
            )

            _copy_image_preserving_alpha(source, target, alpha_reference, item)

            bbox = Image.open(target).convert("RGBA").getchannel("A").getbbox()
            self.assertIsNotNone(bbox)
            assert bbox is not None
            self.assertGreaterEqual(bbox[1], 12)
            self.assertLessEqual(bbox[3], 88)

    def test_bad_transparent_replacement_falls_back_to_safe_source_remix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "output.png"

            _rgba_with_box(source, (100, 100), (20, 20, 80, 90), (255, 0, 0, 255))
            _rgba_with_box(output, (100, 150), (20, 30, 80, 140), (0, 0, 255, 255))

            result = stabilize_transparent_replacement(source, output, _transparent_item())

            self.assertEqual(result["action"], "fallback")
            self.assertIn("size_mismatch", result["issues"])
            fixed = Image.open(output).convert("RGBA")
            self.assertEqual(fixed.size, (100, 100))
            self.assertEqual(fixed.getchannel("A").getbbox(), (20, 20, 80, 90))

    def test_good_transparent_replacement_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            output = root / "output.png"

            _rgba_with_box(source, (100, 100), (20, 20, 80, 90), (255, 0, 0, 255))
            _rgba_with_box(output, (100, 100), (22, 18, 82, 88), (0, 0, 255, 255))

            result = stabilize_transparent_replacement(source, output, _transparent_item())

            self.assertEqual(result["action"], "accepted")
            fixed = Image.open(output).convert("RGBA")
            self.assertEqual(fixed.getchannel("A").getbbox(), (22, 18, 82, 88))


def _transparent_item(**extra: object) -> dict[str, object]:
    item: dict[str, object] = {
        "transparency": {
            "requires_transparent_background": True,
            "classification": "transparent_cutout",
        },
        "references": [],
    }
    item.update(extra)
    return item


def _rgba_with_box(path: Path, size: tuple[int, int], box: tuple[int, int, int, int], color: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    pixels = image.load()
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            pixels[x, y] = color
    image.save(path)


if __name__ == "__main__":
    unittest.main()
