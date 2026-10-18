"""Unit tests for src.stats (offline: no YOLO model, no video files)."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from stats import PersonStats  # noqa: E402


class PersonStatsTests(unittest.TestCase):
    def test_empty_stats_default_to_zero(self):
        stats = PersonStats()
        self.assertEqual(stats.samples, 0)
        self.assertEqual(stats.total, 0)
        self.assertEqual(stats.mean, 0.0)
        self.assertEqual(stats.min, 0)
        self.assertEqual(stats.max, 0)

    def test_mean_min_max_over_sequence(self):
        stats = PersonStats()
        for count in (3, 5, 2, 10):
            stats.add(count)
        self.assertEqual(stats.samples, 4)
        self.assertEqual(stats.total, 20)
        self.assertEqual(stats.mean, 5.0)
        self.assertEqual(stats.min, 2)
        self.assertEqual(stats.max, 10)

    def test_summary_matches_properties(self):
        stats = PersonStats()
        stats.add(1)
        stats.add(7)
        self.assertEqual(
            stats.summary(),
            {"samples": 2, "total": 8, "mean": 4.0, "min": 1, "max": 7},
        )


if __name__ == "__main__":
    unittest.main()
