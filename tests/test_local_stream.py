"""Light unit tests for src.local_stream (offline: no video, YOLO, or uploads)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import local_stream  # noqa: E402


class CameraIdsTests(unittest.TestCase):
    def test_ids_are_one_based_and_ordered(self):
        self.assertEqual(local_stream.camera_ids("cam", 3), ["cam-1", "cam-2", "cam-3"])

    def test_custom_base(self):
        self.assertEqual(local_stream.camera_ids("gate", 2), ["gate-1", "gate-2"])

    def test_zero_cameras_is_empty(self):
        self.assertEqual(local_stream.camera_ids("cam", 0), [])


class CameraValidationTests(unittest.TestCase):
    def test_multi_camera_needs_upload_target(self):
        with self.assertRaises(SystemExit) as ctx:
            local_stream.parse_args(["--cameras", "3"])
        self.assertEqual(ctx.exception.code, 2)

    def test_multi_camera_rejects_fast(self):
        with self.assertRaises(SystemExit) as ctx:
            local_stream.parse_args(["--cameras", "3", "--fast", "--cloud-url", "http://vm:8000"])
        self.assertEqual(ctx.exception.code, 2)

    def test_multi_camera_rejects_live_source(self):
        with self.assertRaises(SystemExit) as ctx:
            local_stream.parse_args(
                ["--cameras", "3", "--source", "live", "--cloud-url", "http://vm:8000"]
            )
        self.assertEqual(ctx.exception.code, 2)

    def test_cameras_below_one_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            local_stream.parse_args(["--cameras", "0"])
        self.assertEqual(ctx.exception.code, 2)

    def test_multi_camera_with_cloud_url_accepted(self):
        args = local_stream.parse_args(["--cameras", "3", "--cloud-url", "http://vm:8000"])
        self.assertEqual(args.cameras, 3)

    def test_seconds_defaults_to_zero(self):
        self.assertEqual(local_stream.parse_args([]).seconds, 0.0)

    def test_phase_offset_defaults_to_zero(self):
        self.assertEqual(local_stream.parse_args([]).phase_offset, 0.0)

    def test_phase_offset_needs_multiple_cameras(self):
        with self.assertRaises(SystemExit) as ctx:
            local_stream.parse_args(["--phase-offset", "5"])
        self.assertEqual(ctx.exception.code, 2)

    def test_negative_phase_offset_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            local_stream.parse_args(
                ["--cameras", "2", "--cloud-url", "http://vm:8000", "--phase-offset", "-1"]
            )
        self.assertEqual(ctx.exception.code, 2)

    def test_phase_offset_accepted_with_multicamera(self):
        args = local_stream.parse_args(
            ["--cameras", "3", "--cloud-url", "http://vm:8000", "--phase-offset", "5"]
        )
        self.assertEqual(args.phase_offset, 5.0)


class MultiCameraMainTests(unittest.TestCase):
    def test_three_specs_with_expected_ids_for_cloud_run(self):
        with (
            mock.patch.object(local_stream, "SharedVideoSource") as source_cls,
            mock.patch.object(local_stream, "make_cloud_sink") as make_sink,
            mock.patch.object(local_stream, "run_cameras", return_value=0) as run,
        ):
            make_sink.side_effect = lambda url, **kwargs: kwargs.get("camera_id")
            code = local_stream.main(["--cameras", "3", "--cloud-url", "http://vm:8000"])

        self.assertEqual(code, 0)
        source, specs = run.call_args.args[0], run.call_args.args[1]
        self.assertIs(source, source_cls.return_value)
        self.assertEqual([cid for cid, _ in specs], ["cam-1", "cam-2", "cam-3"])
        self.assertEqual([sink for _, sink in specs], ["cam-1", "cam-2", "cam-3"])

    def test_custom_base_overrides_ids(self):
        with (
            mock.patch.object(local_stream, "SharedVideoSource"),
            mock.patch.object(local_stream, "make_cloud_sink") as make_sink,
            mock.patch.object(local_stream, "run_cameras", return_value=0) as run,
        ):
            make_sink.side_effect = lambda url, **kwargs: kwargs.get("camera_id")
            local_stream.main(
                ["--cameras", "2", "--camera-id", "gate", "--cloud-url", "http://vm:8000"]
            )

        self.assertEqual([cid for cid, _ in run.call_args.args[1]], ["gate-1", "gate-2"])

    def test_single_camera_uses_run_video(self):
        with (
            mock.patch.object(local_stream, "make_cloud_sink") as make_sink,
            mock.patch.object(local_stream, "run_video", return_value=0) as run_video,
            mock.patch.object(local_stream, "run_cameras") as run_cameras,
        ):
            make_sink.return_value = "sink"
            code = local_stream.main(["--cloud-url", "http://vm:8000"])

        self.assertEqual(code, 0)
        self.assertTrue(run_video.called)
        self.assertFalse(run_cameras.called)

    def test_phase_offset_flows_to_source_and_run_cameras(self):
        with (
            mock.patch.object(local_stream, "SharedVideoSource") as source_cls,
            mock.patch.object(local_stream, "make_cloud_sink"),
            mock.patch.object(local_stream, "run_cameras", return_value=0) as run,
        ):
            local_stream.main(
                ["--cameras", "3", "--cloud-url", "http://vm:8000", "--phase-offset", "5"]
            )

        self.assertEqual(source_cls.call_args.kwargs.get("keep_seconds"), 10.0)
        self.assertEqual(run.call_args.kwargs.get("phase"), 5.0)


if __name__ == "__main__":
    unittest.main()
