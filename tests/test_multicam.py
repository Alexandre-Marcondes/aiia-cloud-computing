"""Unit tests for src.multicam (offline: fake source, no video/YOLO/Azure)."""

import math
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import multicam  # noqa: E402
from multicam import (  # noqa: E402
    CameraWorker,
    compose_grid,
    frame_offset,
    nearest_by_time,
    phase_offset,
    run_cameras,
)


class FakeSource:
    """Minimal stand-in for SharedVideoSource: a constant frame + close flag."""

    def __init__(self, frame=None):
        self._frame = frame if frame is not None else np.zeros((4, 4, 3), dtype=np.uint8)
        self.closed = False
        self.ago_calls = []

    def latest_frame(self, timeout=None):
        return self._frame

    def frame_ago(self, seconds, timeout=None):
        self.ago_calls.append(seconds)
        return self._frame

    def close(self):
        self.closed = True


class PhaseOffsetTests(unittest.TestCase):
    def test_first_camera_has_no_delay(self):
        self.assertEqual(phase_offset(0, 4, 0.4), 0.0)

    def test_offsets_spread_across_interval(self):
        self.assertTrue(math.isclose(phase_offset(2, 4, 0.4), 0.2))
        self.assertTrue(math.isclose(phase_offset(3, 8, 0.8), 0.3))

    def test_single_camera_starts_immediately(self):
        self.assertEqual(phase_offset(0, 1, 0.5), 0.0)


class FrameOffsetTests(unittest.TestCase):
    def test_first_camera_reads_the_live_edge(self):
        self.assertEqual(frame_offset(0, 5.0), 0.0)

    def test_each_camera_is_one_step_further_behind(self):
        self.assertEqual(frame_offset(3, 5.0), 15.0)


class NearestByTimeTests(unittest.TestCase):
    def test_picks_the_closest_timestamp(self):
        buffer = [(10.0, b"a"), (11.0, b"b"), (12.0, b"c")]
        self.assertEqual(nearest_by_time(buffer, 10.9), (11.0, b"b"))
        self.assertEqual(nearest_by_time(buffer, 11.6), (12.0, b"c"))
        self.assertEqual(nearest_by_time(buffer, 100.0), (12.0, b"c"))


class CameraWorkerTests(unittest.TestCase):
    def test_stop_event_ends_worker_cleanly(self):
        source = FakeSource()
        stop_event = threading.Event()
        worker = CameraWorker(
            "cam-1",
            lambda frame: None,
            source,
            index=0,
            n=1,
            interval=0.01,
            stop_event=stop_event,
        )
        worker.start()
        time.sleep(0.05)
        stop_event.set()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive())
        self.assertGreaterEqual(worker.samples, 1)
        self.assertEqual(worker.camera_id, "cam-1")

    def test_no_lag_reads_the_latest_frame(self):
        source = FakeSource()
        stop_event = threading.Event()
        worker = CameraWorker(
            "cam-1",
            lambda frame: None,
            source,
            index=0,
            n=1,
            interval=0.01,
            stop_event=stop_event,
        )
        worker.start()
        time.sleep(0.05)
        stop_event.set()
        worker.join(timeout=5.0)
        self.assertEqual(source.ago_calls, [])

    def test_frame_lag_reads_the_time_shifted_frame(self):
        source = FakeSource()
        stop_event = threading.Event()
        worker = CameraWorker(
            "cam-2",
            lambda frame: None,
            source,
            index=1,
            n=2,
            interval=0.01,
            frame_lag=5.0,
            stop_event=stop_event,
        )
        worker.start()
        time.sleep(0.05)
        stop_event.set()
        worker.join(timeout=5.0)
        self.assertTrue(source.ago_calls)
        self.assertTrue(all(offset == 5.0 for offset in source.ago_calls))


class ComposeGridTests(unittest.TestCase):
    def test_empty_returns_empty_array(self):
        self.assertEqual(compose_grid([], []).shape, (0, 0, 3))

    def test_tiles_frames_into_common_cell_grid(self):
        frames = [
            np.zeros((10, 20, 3), dtype=np.uint8),
            np.zeros((30, 40, 3), dtype=np.uint8),
            np.zeros((10, 20, 3), dtype=np.uint8),
        ]
        grid = compose_grid(frames, ["a", "b", "c"])
        # 3 frames -> 2 columns x 2 rows; cell is the largest frame (30x40).
        self.assertEqual(grid.shape, (60, 80, 3))
        self.assertEqual(grid.dtype, np.uint8)


class RunCamerasTests(unittest.TestCase):
    def test_max_samples_enforced_per_camera(self):
        source = FakeSource()
        counts = {"a": 0, "b": 0, "c": 0}

        def make_sink(camera_id):
            def sink(frame):
                counts[camera_id] += 1

            return sink

        specs = [(camera_id, make_sink(camera_id)) for camera_id in ("a", "b", "c")]
        result = run_cameras(source, specs, interval=0.01, max_samples=4)
        self.assertEqual(result, 0)
        self.assertEqual(counts, {"a": 4, "b": 4, "c": 4})
        self.assertTrue(source.closed)

    def test_first_ticks_are_phase_staggered(self):
        source = FakeSource()
        stamps = {"a": [], "b": [], "c": []}

        def display(camera_id, frame):
            stamps[camera_id].append(time.monotonic())

        specs = [(camera_id, lambda frame: None) for camera_id in ("a", "b", "c")]
        run_cameras(source, specs, interval=0.06, max_samples=2, display=display)
        first = [stamps[camera_id][0] for camera_id in ("a", "b", "c")]
        self.assertLess(first[0], first[1])
        self.assertLess(first[1], first[2])
        self.assertLess(first[1] - first[0], 0.06)
        self.assertLess(first[2] - first[1], 0.06)

    def test_seconds_bounds_wall_clock_run(self):
        source = FakeSource()
        hits = []
        run_cameras(source, [("a", lambda frame: hits.append(1))], interval=0.01, seconds=0.05)
        self.assertGreaterEqual(len(hits), 1)
        self.assertTrue(source.closed)

    def test_stop_event_set_before_start_sends_nothing(self):
        source = FakeSource()
        stop_event = threading.Event()
        stop_event.set()
        sent = []
        run_cameras(
            source,
            [("a", lambda frame: sent.append(1))],
            interval=0.01,
            stop_event=stop_event,
        )
        self.assertEqual(sent, [])
        self.assertTrue(source.closed)

    def test_keyboard_interrupt_stops_cleanly(self):
        source = FakeSource()
        state = {"calls": 0}

        def fake_sleep(_):
            state["calls"] += 1
            if state["calls"] >= 2:
                raise KeyboardInterrupt

        with mock.patch.object(multicam.time, "sleep", fake_sleep):
            result = run_cameras(source, [("a", lambda frame: None)], interval=0.01)
        self.assertEqual(result, 0)
        self.assertTrue(source.closed)


if __name__ == "__main__":
    unittest.main()
