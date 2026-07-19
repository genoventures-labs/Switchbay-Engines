import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import image_scout


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "image_scout.py"


class ImageScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_dirs = (
            image_scout.DATA_DIR,
            image_scout.DOWNLOAD_DIR,
            image_scout.ARTIFACT_DIR,
            image_scout.PAYLOAD_DIR,
        )
        image_scout.DATA_DIR = self.root / "state"
        image_scout.DOWNLOAD_DIR = image_scout.DATA_DIR / "downloads"
        image_scout.ARTIFACT_DIR = image_scout.DATA_DIR / "artifacts"
        image_scout.PAYLOAD_DIR = image_scout.DATA_DIR / "payloads"
        self.source = self.root / "source.png"
        Image.new("RGBA", (3200, 1800), (30, 60, 90, 180)).save(self.source)

    def tearDown(self):
        (
            image_scout.DATA_DIR,
            image_scout.DOWNLOAD_DIR,
            image_scout.ARTIFACT_DIR,
            image_scout.PAYLOAD_DIR,
        ) = self.old_dirs
        self.temp.cleanup()

    def test_inspect_recommends_tiles_for_large_image(self):
        result = image_scout.inspect_image(str(self.source))
        self.assertEqual(result["format"], "PNG")
        self.assertEqual(result["advice"]["suggested_strategy"], "overview_then_tiles")

    def test_bundle_writes_manifest_and_ordered_tiles(self):
        output = self.root / "bundle"
        result = image_scout.build_vision_bundle(str(self.source), task="ui", output_dir=str(output))
        self.assertTrue(Path(result["manifest_path"]).exists())
        self.assertGreater(len(result["tiles"]), 1)
        self.assertEqual(result["reading_order"][0], result["overview"]["path"])

    def test_provider_payload_is_written_not_printed(self):
        payload = self.root / "payload.json"
        result = image_scout.encode_for_provider(str(self.source), provider="anthropic", max_edge=512, output_path=str(payload))
        block = json.loads(payload.read_text("utf-8"))
        self.assertEqual(block["type"], "image")
        self.assertEqual(block["source"]["media_type"], "image/jpeg")
        self.assertNotIn("data", result)

    def test_switchbay_none_values_fall_back_cleanly(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "vision_prompt", "--task", "None", "--question", "None"],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(proc.stdout)
        self.assertEqual(result["task"], "general")
        self.assertIn("Analyze the image", result["prompt"])

    def test_private_url_is_blocked(self):
        with self.assertRaises(ValueError):
            image_scout._resolve_source("http://127.0.0.1/image.png")


if __name__ == "__main__":
    unittest.main()
