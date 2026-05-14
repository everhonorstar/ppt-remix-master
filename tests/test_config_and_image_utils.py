from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

from ppt_remix.config import find_default_env  # noqa: E402
from ppt_remix.image_utils import image_kind, image_size  # noqa: E402
from ppt_remix.pptx_ops import _remixed_filename  # noqa: E402


class ConfigAndImageUtilsTests(unittest.TestCase):
    def test_default_env_lookup_is_portable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text("TEXT_API_KEY=test\n", encoding="utf-8")
            original_cwd = Path.cwd()
            try:
                import os

                os.chdir(root)
                self.assertEqual(find_default_env().resolve(), env_path.resolve())
            finally:
                os.chdir(original_cwd)

    def test_image_kind_and_size_without_imghdr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            png = root / "sample.png"
            jpg = root / "sample.jpg"
            Image.new("RGB", (12, 8), (10, 20, 30)).save(png)
            Image.new("RGB", (9, 7), (10, 20, 30)).save(jpg)

            self.assertEqual(image_kind(png), "png")
            self.assertEqual(image_size(png), (12, 8))
            self.assertEqual(image_kind(jpg), "jpeg")
            self.assertEqual(image_size(jpg), (9, 7))

    def test_remixed_filename_uses_source_filename_stem(self) -> None:
        job_dir = Path("/tmp/jobs/我是班级值日生3")

        self.assertEqual(
            _remixed_filename(job_dir, {"source_filename": "我是班级值日生3.pptx"}),
            "我是班级值日生3_remixed.pptx",
        )

    def test_remixed_filename_falls_back_to_job_name(self) -> None:
        job_dir = Path("/tmp/jobs/demo")

        self.assertEqual(_remixed_filename(job_dir, {}), "demo_remixed.pptx")


if __name__ == "__main__":
    unittest.main()
