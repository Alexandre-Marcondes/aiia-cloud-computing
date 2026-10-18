"""Unit tests for src.paths (offline: no YOLO model, no video files)."""

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from paths import ensure_parent, resolve_path  # noqa: E402


class ResolvePathTests(unittest.TestCase):
    def test_absolute_path_is_returned_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            absolute = Path(tmp) / "out.csv"
            self.assertEqual(resolve_path(absolute), absolute.resolve())

    def test_relative_path_is_anchored_at_repo_root(self):
        self.assertEqual(
            resolve_path("data/x.csv"),
            (REPO_ROOT / "data/x.csv").resolve(),
        )


class EnsureParentTests(unittest.TestCase):
    def test_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "deeper" / "out.csv"
            ensure_parent(target)
            self.assertTrue(target.parent.is_dir())

    def test_existing_parent_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            ensure_parent(Path(tmp) / "out.csv")  # must not raise


if __name__ == "__main__":
    unittest.main()
