"""Unit tests for src.render (offline: Pillow only)."""

import io
import sys
import unittest
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from render import draw_boxes  # noqa: E402


def _jpeg(size=(40, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 10, 10)).save(buffer, format="JPEG")
    return buffer.getvalue()


class RenderTests(unittest.TestCase):
    def test_draw_boxes_returns_jpeg_of_same_size(self):
        people = [{"boundingBox": {"x": 2, "y": 2, "w": 10, "h": 8}}]
        out = draw_boxes(_jpeg((40, 30)), people)
        with Image.open(io.BytesIO(out)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (40, 30))

    def test_draw_boxes_with_no_people_still_valid(self):
        out = draw_boxes(_jpeg(), [])
        with Image.open(io.BytesIO(out)) as image:
            self.assertEqual(image.format, "JPEG")


if __name__ == "__main__":
    unittest.main()
