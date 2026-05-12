from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

from ppt_remix.pptx_ops import _copy_image_preserving_alpha  # noqa: E402


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
