"""Unit tests for scripts.slice_csv (offline: temp files only)."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import slice_csv  # noqa: E402

HEADER = "Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs\n"


def _rows(n):
    return "".join(f"2026-10-11 18:00:{i:02d},cam-1,{i},0,{i}\n" for i in range(n))


class SliceTextTests(unittest.TestCase):
    def test_header_always_present_with_no_data_rows(self):
        self.assertEqual(slice_csv.slice_text(HEADER), HEADER)
        self.assertEqual(slice_csv.slice_text(""), "")

    def test_tail_returns_last_rows(self):
        text = HEADER + _rows(5)
        out = slice_csv.slice_text(text, mode="tail", count=2)
        self.assertTrue(out.startswith(HEADER))
        body = out[len(HEADER) :].splitlines()
        self.assertEqual(len(body), 2)
        self.assertIn("18:00:03", body[0])
        self.assertIn("18:00:04", body[1])

    def test_head_returns_first_rows(self):
        text = HEADER + _rows(5)
        out = slice_csv.slice_text(text, mode="head", count=2)
        body = out[len(HEADER) :].splitlines()
        self.assertEqual(len(body), 2)
        self.assertIn("18:00:00", body[0])
        self.assertIn("18:00:01", body[1])

    def test_default_row_count_is_tail_40(self):
        text = HEADER + _rows(50)
        out = slice_csv.slice_text(text)
        body = out[len(HEADER) :].splitlines()
        self.assertEqual(len(body), 40)
        self.assertIn("18:00:10", body[0])
        self.assertIn("18:00:49", body[-1])

    def test_blank_lines_are_skipped(self):
        text = HEADER + "\n" + _rows(2) + "   \n\n" + _rows(1).splitlines()[-1] + "\n"
        out = slice_csv.slice_text(text, mode="head", count=10)
        body = out[len(HEADER) :].splitlines()
        self.assertEqual(len(body), 3)

    def test_count_zero_keeps_only_header(self):
        self.assertEqual(slice_csv.slice_text(HEADER + _rows(3), count=0), HEADER)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write(self, name, content):
        path = Path(self.tmpdir.name) / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_main_prints_slice(self):
        path = self._write("processing.csv", HEADER + _rows(5))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = slice_csv.main([str(path), "--head", "1"])
        self.assertEqual(rc, 0)
        body = buf.getvalue()[len(HEADER) :].splitlines()
        self.assertEqual(len(body), 1)
        self.assertIn("18:00:00", body[0])

    def test_main_missing_file_exits_nonzero(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            rc = slice_csv.main([str(Path(self.tmpdir.name) / "nope.csv")])
        self.assertEqual(rc, 1)
        self.assertIn("cannot read", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
