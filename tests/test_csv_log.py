"""Unit tests for src.csv_log (offline: no YOLO model, no video files)."""

import csv
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from csv_log import (  # noqa: E402
    append_row,
    format_processing_row,
    format_row,
    log_sample,
    now_timestamp,
)


class CsvLoggingTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _read_rows(self, path):
        with open(path, newline="") as csv_file:
            return list(csv.reader(csv_file))

    def test_header_written_once_then_rows_appended(self):
        csv_path = os.path.join(self.tmpdir.name, "database.csv")
        log_sample(csv_path, "2026-09-24 19:50:03", 0)
        log_sample(csv_path, "2026-09-24 19:50:08", 3)
        log_sample(csv_path, "2026-09-24 19:50:13", 5)

        rows = self._read_rows(csv_path)
        self.assertEqual(len(rows), 4)  # header + 3 data rows
        self.assertEqual(rows[0], ["Timestamp", "Person_Count"])
        self.assertEqual(
            rows[1:],
            [
                ["2026-09-24 19:50:03", "0"],
                ["2026-09-24 19:50:08", "3"],
                ["2026-09-24 19:50:13", "5"],
            ],
        )

    def test_header_written_when_preexisting_file_is_empty(self):
        csv_path = os.path.join(self.tmpdir.name, "database.csv")
        with open(csv_path, "w"):
            pass  # create an empty file with no header
        log_sample(csv_path, "2026-09-24 19:50:03", 1)
        log_sample(csv_path, "2026-09-24 19:50:08", 2)

        rows = self._read_rows(csv_path)
        self.assertEqual(len(rows), 3)  # header + 2 data rows
        self.assertEqual(rows[0], ["Timestamp", "Person_Count"])

    def test_now_timestamp_uses_shared_format(self):
        stamp = now_timestamp(datetime(2026, 9, 24, 19, 50, 3))
        self.assertEqual(stamp, "2026-09-24 19:50:03")

    def test_format_row_serializes_pair(self):
        self.assertEqual(format_row("2026-09-24 19:50:03", 3), "2026-09-24 19:50:03,3\r\n")

    def test_format_processing_row_serializes_five_columns(self):
        row = format_processing_row("2026-09-24 19:50:03", "cam-2", 412.34, 0.0, 412.34)
        self.assertEqual(row, "2026-09-24 19:50:03,cam-2,412.3,0.0,412.3\r\n")

    def test_append_row_adds_processing_header(self):
        first = append_row(
            b"", format_processing_row("2026-09-24 19:50:03", "cam", 300.06, 0.0, 300.06)
        )
        self.assertEqual(
            first,
            b"Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs\r\n"
            b"2026-09-24 19:50:03,cam,300.1,0.0,300.1\r\n",
        )

    def test_append_row_adds_header_once(self):
        first = append_row(b"", format_row("2026-09-24 19:50:03", 1))
        self.assertEqual(first, b"Timestamp,Person_Count\r\n2026-09-24 19:50:03,1\r\n")

        second = append_row(first, format_row("2026-09-24 19:50:08", 2))
        self.assertEqual(
            second,
            b"Timestamp,Person_Count\r\n2026-09-24 19:50:03,1\r\n2026-09-24 19:50:08,2\r\n",
        )

    def test_format_row_with_camera_serializes_triple(self):
        self.assertEqual(
            format_row("2026-09-24 19:50:03", 3, camera="cam-1"),
            "2026-09-24 19:50:03,cam-1,3\r\n",
        )

    def test_append_row_uses_v2_header_for_camera_row(self):
        first = append_row(b"", format_row("2026-09-24 19:50:03", 1, camera="cam-1"))
        rows = list(csv.reader(io.StringIO(first.decode("utf-8"))))
        self.assertEqual(rows[0], ["Timestamp", "Camera", "Person_Count"])
        self.assertEqual(rows[1], ["2026-09-24 19:50:03", "cam-1", "1"])

    def test_append_row_does_not_repeat_v2_header(self):
        first = append_row(b"", format_row("2026-09-24 19:50:03", 1, camera="cam-1"))
        second = append_row(first, format_row("2026-09-24 19:50:08", 2, camera="cam-1"))
        rows = list(csv.reader(io.StringIO(second.decode("utf-8"))))
        self.assertEqual(
            rows,
            [
                ["Timestamp", "Camera", "Person_Count"],
                ["2026-09-24 19:50:03", "cam-1", "1"],
                ["2026-09-24 19:50:08", "cam-1", "2"],
            ],
        )

    def test_log_sample_writes_v2_header_once(self):
        csv_path = os.path.join(self.tmpdir.name, "database.csv")
        log_sample(csv_path, "2026-09-24 19:50:03", 0, camera="cam-1")
        log_sample(csv_path, "2026-09-24 19:50:08", 3, camera="cam-2")

        rows = self._read_rows(csv_path)
        self.assertEqual(rows[0], ["Timestamp", "Camera", "Person_Count"])
        self.assertEqual(
            [row[1] for row in rows[1:]],
            ["cam-1", "cam-2"],
        )
        self.assertTrue(all(len(row) == 3 for row in rows))

    def test_legacy_and_v2_files_each_stay_single_schema(self):
        legacy_path = os.path.join(self.tmpdir.name, "legacy.csv")
        v2_path = os.path.join(self.tmpdir.name, "v2.csv")
        log_sample(legacy_path, "2026-09-24 19:50:03", 1)
        log_sample(legacy_path, "2026-09-24 19:50:08", 2)
        log_sample(v2_path, "2026-09-24 19:50:03", 1, camera="cam-1")
        log_sample(v2_path, "2026-09-24 19:50:08", 2, camera="cam-2")

        legacy_rows = self._read_rows(legacy_path)
        v2_rows = self._read_rows(v2_path)
        self.assertTrue(all(len(row) == 2 for row in legacy_rows))
        self.assertTrue(all(len(row) == 3 for row in v2_rows))

    def test_log_sample_rotates_on_legacy_to_multi_switch(self):
        csv_path = os.path.join(self.tmpdir.name, "database.csv")
        log_sample(csv_path, "2026-09-24 19:50:03", 1)
        log_sample(csv_path, "2026-09-24 19:50:08", 2)
        log_sample(csv_path, "2026-09-24 19:50:13", 3, camera="cam-1")

        rows = self._read_rows(csv_path)
        self.assertEqual(rows[0], ["Timestamp", "Camera", "Person_Count"])
        self.assertEqual(rows[1:], [["2026-09-24 19:50:13", "cam-1", "3"]])

    def test_log_sample_rotates_on_multi_to_legacy_switch(self):
        csv_path = os.path.join(self.tmpdir.name, "database.csv")
        log_sample(csv_path, "2026-09-24 19:50:03", 1, camera="cam-1")
        log_sample(csv_path, "2026-09-24 19:50:08", 2, camera="cam-2")
        log_sample(csv_path, "2026-09-24 19:50:13", 3)

        rows = self._read_rows(csv_path)
        self.assertEqual(rows[0], ["Timestamp", "Person_Count"])
        self.assertEqual(rows[1:], [["2026-09-24 19:50:13", "3"]])

    def test_log_sample_self_heals_a_mixed_file(self):
        csv_path = os.path.join(self.tmpdir.name, "database.csv")
        # A legacy-header file that already holds stray 3-column rows (pre-fix state).
        with open(csv_path, "w", newline="") as csv_file:
            csv_file.write("Timestamp,Person_Count\r\n")
            csv_file.write("2026-09-24 19:50:03,1\r\n")
            csv_file.write("2026-09-24 19:50:08,cam-1,2\r\n")
        log_sample(csv_path, "2026-09-24 19:50:13", 3, camera="cam-1")

        rows = self._read_rows(csv_path)
        self.assertEqual(rows[0], ["Timestamp", "Camera", "Person_Count"])
        self.assertEqual(rows[1:], [["2026-09-24 19:50:13", "cam-1", "3"]])

    def test_append_row_resets_on_schema_change(self):
        legacy = append_row(b"", format_row("2026-09-24 19:50:03", 1))
        rotated = append_row(legacy, format_row("2026-09-24 19:50:08", 2, camera="cam-1"))

        rows = list(csv.reader(io.StringIO(rotated.decode("utf-8"))))
        self.assertEqual(rows[0], ["Timestamp", "Camera", "Person_Count"])
        self.assertEqual(rows[1:], [["2026-09-24 19:50:08", "cam-1", "2"]])

    def test_append_row_keeps_same_schema(self):
        v2 = append_row(b"", format_row("2026-09-24 19:50:03", 1, camera="cam-1"))
        same = append_row(v2, format_row("2026-09-24 19:50:08", 2, camera="cam-2"))

        rows = list(csv.reader(io.StringIO(same.decode("utf-8"))))
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
