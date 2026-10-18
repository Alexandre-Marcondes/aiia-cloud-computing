"""Smoke tests for src.pipeline.process_sample (offline: no YOLO, no video, no network)."""

import csv
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

from pipeline import process_sample  # noqa: E402
from stats import PersonStats  # noqa: E402

FIXED_COUNT = 3
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class _FakeDetector:
    """Stands in for a YOLO detector: returns a fixed count and a JPEG-writable array."""

    def __init__(self):
        self.annotated = np.zeros((32, 32, 3), dtype=np.uint8)

    def count_persons(self, frame):
        return FIXED_COUNT, self.annotated


class _FakePlotter:
    """Records each ``add(timestamp, count)`` call; does not implement the old ``refresh``."""

    def __init__(self):
        self.calls = []

    def add(self, timestamp, count):
        self.calls.append((timestamp, count))


class ProcessSampleTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.csv_path = self.root / "database.csv"
        self.frame_out = self.root / "annotated.jpg"

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run(self, camera=None):
        detector = _FakeDetector()
        plotter = _FakePlotter()
        stats = PersonStats()
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        result = process_sample(
            frame, detector, stats, self.csv_path, self.frame_out, plotter, camera=camera
        )
        return detector, plotter, stats, result

    def test_single_sample_contract(self):
        detector, plotter, stats, (count, annotated) = self._run()

        # Returns the fake detector's output.
        self.assertEqual(count, FIXED_COUNT)
        self.assertIs(annotated, detector.annotated)

        # CSV: legacy header plus exactly one data row.
        lines = self.csv_path.read_text().splitlines()
        self.assertEqual(lines[0], "Timestamp,Person_Count")
        self.assertEqual(len(lines), 2)
        row = next(csv.reader([lines[1]]))
        self.assertEqual(len(row), 2)
        parsed = datetime.strptime(row[0], TIMESTAMP_FORMAT)
        self.assertEqual(row[0], parsed.strftime(TIMESTAMP_FORMAT))
        self.assertEqual(int(row[1]), FIXED_COUNT)

        # Stats updated.
        self.assertEqual(stats.samples, 1)
        self.assertEqual(stats.total, FIXED_COUNT)

        # Plotter received exactly one add(), consistent with the CSV row.
        self.assertEqual(len(plotter.calls), 1)
        ts, cnt = plotter.calls[0]
        self.assertEqual(ts, row[0])
        self.assertEqual(cnt, FIXED_COUNT)

        # Annotated frame written to disk.
        self.assertTrue(self.frame_out.exists())
        self.assertGreater(self.frame_out.stat().st_size, 0)

    def test_camera_arg_tags_csv_row(self):
        detector, plotter, stats, result = self._run(camera="cam-1")
        count = result[0]

        lines = self.csv_path.read_text().splitlines()
        self.assertEqual(lines[0], "Timestamp,Camera,Person_Count")
        self.assertEqual(len(lines), 2)
        row = next(csv.reader([lines[1]]))
        self.assertEqual(len(row), 3)
        self.assertEqual(row[1], "cam-1")
        self.assertEqual(int(row[2]), count)
        self.assertEqual(int(row[2]), FIXED_COUNT)

        # Stats reflect the same single sample.
        self.assertEqual(stats.samples, 1)
        self.assertEqual(stats.total, FIXED_COUNT)

        # Plotter still sees the same count.
        self.assertEqual(len(plotter.calls), 1)
        self.assertEqual(plotter.calls[0][1], FIXED_COUNT)


if __name__ == "__main__":
    unittest.main()
