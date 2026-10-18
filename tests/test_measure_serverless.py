"""Unit tests for src.measure_serverless (offline: fake Azure blob clients)."""

import sys
import unittest
from pathlib import Path

from azure.core.exceptions import ResourceNotFoundError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import measure_serverless  # noqa: E402

HEADER = b"Timestamp,Person_Count\r\n"


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class _Properties:
    def __init__(self, etag):
        self.etag = etag


class _Download:
    def __init__(self, data):
        self._data = data

    def readall(self):
        return self._data


class _FakeCsvBlob:
    def __init__(self, store, name="database.csv"):
        self.store = store
        self.name = name

    def get_blob_properties(self):
        if self.name not in self.store:
            raise ResourceNotFoundError(self.name)
        return _Properties(self.store[self.name][1])

    def download_blob(self):
        if self.name not in self.store:
            raise ResourceNotFoundError(self.name)
        return _Download(self.store[self.name][0])


class _FakeRawBlob:
    def __init__(self, raw_store, csv_store, name, process):
        self.raw_store = raw_store
        self.csv_store = csv_store
        self.name = name
        self.process = process

    def upload_blob(self, data, overwrite=False):
        self.raw_store[self.name] = data
        self.process(self.raw_store, self.name, self.csv_store)

    def exists(self):
        return self.name in self.raw_store


class _FakeRawContainer:
    def __init__(self, raw_store, csv_store, process):
        self.raw_store = raw_store
        self.csv_store = csv_store
        self.process = process

    def get_blob_client(self, name):
        return _FakeRawBlob(self.raw_store, self.csv_store, name, self.process)


def _append_ok(raw_store, name, csv_store):
    """Simulate the function: append a CSV row and delete the raw blob."""
    data = csv_store.get("database.csv", (HEADER, "etag-0"))[0] + b"2026-01-01 00:00:00,3\r\n"
    csv_store["database.csv"] = (data, f"etag-{len(data)}")
    raw_store.pop(name, None)


def _append_twice(raw_store, name, csv_store):
    _append_ok(raw_store, name, csv_store)
    data = csv_store["database.csv"][0] + b"2026-01-01 00:00:00,3\r\n"
    csv_store["database.csv"] = (data, f"etag-{len(data)}")


def _noop(raw_store, name, csv_store):
    pass


def _measure(raw, csv_store, timeout=5.0):
    clock = _FakeClock()
    return measure_serverless.measure_frame(
        raw,
        b"jpeg",
        "cam/x.jpg",
        _FakeCsvBlob(csv_store),
        poll=0.1,
        timeout=timeout,
        clock=clock.time,
        sleep=clock.sleep,
    )


class WaitUntilTests(unittest.TestCase):
    def test_returns_elapsed_when_predicate_becomes_true(self):
        clock = _FakeClock()
        calls = {"n": 0}

        def predicate():
            calls["n"] += 1
            return calls["n"] >= 3

        elapsed = measure_serverless.wait_until(
            predicate, timeout=10, poll=0.5, clock=clock.time, sleep=clock.sleep
        )
        self.assertEqual(elapsed, 1.0)

    def test_returns_none_on_timeout(self):
        clock = _FakeClock()
        elapsed = measure_serverless.wait_until(
            lambda: False, timeout=1.0, poll=0.5, clock=clock.time, sleep=clock.sleep
        )
        self.assertIsNone(elapsed)
        self.assertGreaterEqual(clock.t, 1.0)


class CountsTests(unittest.TestCase):
    def test_parses_person_counts(self):
        store = {
            "database.csv": (
                HEADER + b"2026-01-01 00:00:00,2\r\n2026-01-01 00:00:01,5\r\n",
                "e",
            )
        }
        self.assertEqual(measure_serverless._counts(_FakeCsvBlob(store)), [2, 5])

    def test_parses_person_counts_from_multi_camera_schema(self):
        store = {
            "database.csv": (
                b"Timestamp,Camera,Person_Count\r\n"
                b"2026-01-01 00:00:00,measure,6\r\n2026-01-01 00:00:01,measure,4\r\n",
                "e",
            )
        }
        self.assertEqual(measure_serverless._counts(_FakeCsvBlob(store)), [6, 4])

    def test_missing_blob_is_empty(self):
        self.assertEqual(measure_serverless._counts(_FakeCsvBlob({})), [])

    def test_etag_missing_is_none(self):
        self.assertIsNone(measure_serverless._etag(_FakeCsvBlob({})))


class MeasureFrameTests(unittest.TestCase):
    def test_success_reports_latency_rows_and_count(self):
        raw_store, csv_store = {}, {}
        raw = _FakeRawContainer(raw_store, csv_store, _append_ok)
        result = _measure(raw, csv_store)
        self.assertEqual(result["e2e"], 0.0)
        self.assertEqual(result["deleted"], 0.0)
        self.assertEqual(result["appended"], 1)
        self.assertEqual(result["count"], 3)

    def test_timeout_when_nothing_changes(self):
        raw_store, csv_store = {}, {"database.csv": (HEADER, "etag-0")}
        raw = _FakeRawContainer(raw_store, csv_store, _noop)
        result = _measure(raw, csv_store, timeout=1.0)
        self.assertIsNone(result["e2e"])
        self.assertIsNone(result["deleted"])

    def test_duplicate_rows_are_counted(self):
        raw_store, csv_store = {}, {}
        raw = _FakeRawContainer(raw_store, csv_store, _append_twice)
        result = _measure(raw, csv_store)
        self.assertEqual(result["appended"], 2)


if __name__ == "__main__":
    unittest.main()
