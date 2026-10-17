import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline
import prompt_generator


class SlugTests(unittest.TestCase):
    def test_slug_is_filename_safe(self):
        slug = prompt_generator.channel_slug("Fish & Chips!! / it's a trend")
        self.assertEqual(slug, "FISH_AND_CHIPS_IT_S_A_TREND")
        self.assertRegex(slug, r"^[A-Z0-9_]+$")

    def test_blank_trend_has_a_fallback(self):
        self.assertEqual(prompt_generator.channel_slug("!!!"), "CHANNEL")


class GenerateTests(unittest.TestCase):
    def test_batch_is_unique_and_complete(self):
        prompts = prompt_generator.generate_prompts(
            ["Fish & Chips", "AI TAKEOVER"], count=4
        )
        self.assertEqual(len(prompts), 4)
        channels = [p["channel"] for p in prompts]
        self.assertEqual(len(channels), len(set(channels)))
        for prompt in prompts:
            self.assertRegex(prompt["channel"], r"^[A-Z0-9_]+$")
            self.assertIn("9:16", prompt["prompt"])
            self.assertTrue(prompt["bumper"])

    def test_pipeline_writes_matching_caption_keys(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        with mock.patch.dict(os.environ, {"VIDROT_BASE": str(base)}):
            with mock.patch.object(pipeline, "get_trends", return_value=["AI TAKEOVER", "QUIET QUITTING"]):
                with mock.patch.object(pipeline.sys, "argv", ["pipeline.py", "--count", "3"]):
                    self.assertEqual(pipeline.main(), 0)

        batches = list((base / "prompts").glob("batch_*.json"))
        captions = list((base / "output").glob("captions_*.json"))
        instructions = (base / "output" / "generate_instructions.txt").read_text()
        self.assertEqual(len(batches), 1)
        saved = json.loads(batches[0].read_text())
        caption_map = json.loads(captions[0].read_text())
        self.assertEqual(len(saved), 3)
        for index, prompt in enumerate(saved):
            stem = pipeline.clip_stem(index, prompt["channel"])
            self.assertIn(stem, caption_map)
            self.assertIn(f"output/{stem}.mp4", instructions)
            self.assertIn(prompt["bumper"], caption_map[stem])

    def test_dry_run_writes_nothing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        with mock.patch.dict(os.environ, {"VIDROT_BASE": str(base)}):
            with mock.patch.object(pipeline, "get_trends", return_value=["AI TAKEOVER"]):
                with mock.patch.object(pipeline.sys, "argv", ["pipeline.py", "--dry-run", "--count", "2"]):
                    self.assertEqual(pipeline.main(), 0)
        self.assertFalse((base / "prompts").exists())
        self.assertFalse((base / "output").exists())


if __name__ == "__main__":
    unittest.main()
