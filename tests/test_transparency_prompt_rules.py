from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

from ppt_remix.providers import _image_generation_prompt, _vision_prompt_instruction  # noqa: E402
from ppt_remix.workflow import _enforce_transparent_prompt_rules  # noqa: E402


class TransparencyPromptRuleTests(unittest.TestCase):
    def test_vision_instruction_treats_checkerboard_as_non_content(self) -> None:
        instruction = _vision_prompt_instruction({"transparency": _transparent_meta()})

        self.assertIn("不属于图片内容", instruction)
        self.assertIn("checkerboard", instruction)
        self.assertIn("transparent grid", instruction)

    def test_transparent_prompt_rules_are_enforced_before_generation(self) -> None:
        prompt = {
            "prompt": "原创透明素材，一个机器人头像",
            "style": "3D卡通",
            "environment": {
                "location": "灰白棋盘格背景",
                "objects": ["机器人头像", "透明格子"],
            },
            "transparency": _transparent_meta(),
            "negative_prompt": "文字、水印",
        }

        _enforce_transparent_prompt_rules(prompt)

        self.assertIn("真实 PNG alpha", prompt["prompt"])
        self.assertIn("checkerboard", prompt["negative_prompt"])
        self.assertEqual(prompt["environment"]["location"], "背景")
        self.assertEqual(prompt["environment"]["objects"], ["机器人头像"])

    def test_image_generation_prompt_repeats_no_checkerboard_rule(self) -> None:
        rendered = _image_generation_prompt(
            {
                "prompt": "原创透明素材，一个机器人头像",
                "transparency": _transparent_meta(),
            }
        )

        self.assertIn("真实 PNG alpha", rendered)
        self.assertIn("checkerboard", rendered)
        self.assertIn("透明格子", rendered)


def _transparent_meta() -> dict[str, object]:
    return {
        "has_alpha": True,
        "alpha_min": 0,
        "alpha_max": 255,
        "transparent_pixel_ratio": 0.8,
        "near_transparent_pixel_ratio": 0.8,
        "transparent_edge_ratio": 1.0,
        "requires_transparent_background": True,
        "background_instruction": "generate subject/object on transparent background; no white canvas",
        "classification": "transparent_cutout",
    }


if __name__ == "__main__":
    unittest.main()
