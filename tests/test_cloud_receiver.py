"""Unit tests for src.cloud_receiver (offline: stub processor, no YOLO)."""

import csv
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from cloud_receiver import (  # noqa: E402
    HEALTH_PATH,
    ProcessingCsvWriter,
    ReceiverServer,
    build_processor,
    make_handler,
)
from transport import FRAME_PATH, post_frame  # noqa: E402


class _RecordingProcessor:
    def __init__(self):
        self.frames = []
        self.cameras = []

    def __call__(self, frame, camera=None):
        self.frames.append(frame)
        self.cameras.append(camera)
        return len(self.frames), 0.0, 0.0


class _FakeDetector:
    """Stand-in for PersonDetector: annotates nothing, returns a fixed count."""

    def __init__(self, count=1):
        self.count = count

    def count_persons(self, frame):
        return self.count, frame


class _DummyStats:
    def __init__(self):
        self.counts = []

    def add(self, count):
        self.counts.append(count)

    def summary(self):
        return {
            "samples": len(self.counts),
            "total": sum(self.counts),
            "mean": 0.0,
            "min": 0,
            "max": 0,
        }


class _DummyPlotter:
    def add(self, timestamp, count):
        pass


class CloudReceiverTests(unittest.TestCase):
    def setUp(self):
        self.processor = _RecordingProcessor()
        self.server = ReceiverServer(("127.0.0.1", 0), make_handler(self.processor, max_bytes=1000))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_post_frame_runs_processor_and_returns_count(self):
        frame = np.full((6, 6, 3), 100, dtype=np.uint8)
        result = post_frame(self.base + FRAME_PATH, frame, camera_id="cam-9", timeout=5.0)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["camera"], "cam-9")
        self.assertIsInstance(result["processing_ms"], (int, float))
        self.assertEqual(len(self.processor.frames), 1)
        self.assertEqual(self.processor.frames[0].shape, (6, 6, 3))

    def test_health_endpoint(self):
        with urllib.request.urlopen(self.base + HEALTH_PATH, timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_unknown_path_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self.base + "/nope", timeout=5)
        self.assertEqual(ctx.exception.code, 404)

    def test_oversized_body_returns_413(self):
        frame = np.random.default_rng(0).integers(0, 256, (400, 400, 3), dtype=np.uint8)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            post_frame(self.base + FRAME_PATH, frame, timeout=5.0)
        self.assertEqual(ctx.exception.code, 413)

    def test_garbage_body_returns_400(self):
        request = urllib.request.Request(
            self.base + FRAME_PATH,
            data=b"not a jpeg",
            method="POST",
            headers={"Content-Type": "image/jpeg"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(self.processor.frames, [])


class CameraAwareReceiverTests(unittest.TestCase):
    """Acceptance for the legacy/multi output split, using a real processor."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.csv_path = os.path.join(self.tmpdir.name, "database.csv")
        self.frame_out = os.path.join(self.tmpdir.name, "processed_frame.jpg")
        self.processing_path = os.path.join(self.tmpdir.name, "processing.csv")
        processor = build_processor(
            _FakeDetector(),
            _DummyStats(),
            self.csv_path,
            self.frame_out,
            _DummyPlotter(),
        )
        writer = ProcessingCsvWriter(self.processing_path)
        self.server = ReceiverServer(
            ("127.0.0.1", 0), make_handler(processor, max_bytes=1000, processing_csv=writer)
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmpdir.cleanup()

    def _post(self, camera_id=None):
        frame = np.full((6, 6, 3), 100, dtype=np.uint8)
        return post_frame(self.base + FRAME_PATH, frame, camera_id=camera_id, timeout=5.0)

    def _rows(self):
        with open(self.csv_path, newline="") as csv_file:
            return list(csv.reader(csv_file))

    def _processing_rows(self):
        with open(self.processing_path, newline="") as csv_file:
            return list(csv.reader(csv_file))

    def test_processing_telemetry_records_each_frame(self):
        self._post()
        self._post(camera_id="cam-2")

        rows = self._processing_rows()
        self.assertEqual(rows[0], ["Timestamp", "Camera", "ProcessingMs", "QueueMs", "ServiceMs"])
        self.assertEqual(len(rows), 3)
        self.assertEqual([row[1] for row in rows[1:]], ["cam", "cam-2"])
        for row in rows[1:]:
            self.assertEqual(len(row), 5)
            processing_ms, queue_ms, service_ms = (
                float(row[2]),
                float(row[3]),
                float(row[4]),
            )
            self.assertGreaterEqual(processing_ms + 1e-9, queue_ms + service_ms)

    def test_camera_post_writes_v2_row_and_per_camera_frame(self):
        result = self._post(camera_id="cam-2")
        self.assertEqual(result["camera"], "cam-2")

        rows = self._rows()
        self.assertEqual(rows[0], ["Timestamp", "Camera", "Person_Count"])
        self.assertEqual(len(rows[1]), 3)
        self.assertEqual(rows[1][1], "cam-2")
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir.name, "frames", "cam-2.jpg")))
        self.assertFalse(os.path.exists(self.frame_out))

    def test_no_camera_post_keeps_legacy_output(self):
        result = self._post()
        self.assertIsNone(result["camera"])

        rows = self._rows()
        self.assertEqual(rows[0], ["Timestamp", "Person_Count"])
        self.assertTrue(all(len(row) == 2 for row in rows))
        self.assertTrue(os.path.exists(self.frame_out))

    def test_reserved_camera_post_keeps_legacy_output(self):
        self._post(camera_id="cam")

        rows = self._rows()
        self.assertEqual(rows[0], ["Timestamp", "Person_Count"])
        self.assertTrue(all(len(row) == 2 for row in rows))
        self.assertTrue(os.path.exists(self.frame_out))
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir.name, "frames", "cam.jpg")))


if __name__ == "__main__":
    unittest.main()
