"""Unit tests for src.blob_transport (offline: fake Azure blob clients)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import blob_transport  # noqa: E402
import csv_log  # noqa: E402

JPEG_SOI = b"\xff\xd8"


class _Download:
    def __init__(self, data, etag):
        self._data = data
        self.properties = type("Properties", (), {"etag": etag})()

    def readall(self):
        return self._data


class _FakeBlob:
    def __init__(self, store, name):
        self.store = store
        self.name = name

    def download_blob(self):
        if self.name not in self.store:
            raise ResourceNotFoundError(self.name)
        data, etag = self.store[self.name]
        return _Download(data, etag)

    def upload_blob(self, data, overwrite=False, etag=None, match_condition=None):
        self.store[self.name] = (data, f"etag-{len(data)}")


class _RacyBlob(_FakeBlob):
    """Raises one ETag conflict before succeeding, to exercise the retry."""

    def __init__(self, store, name):
        super().__init__(store, name)
        self.uploads = 0

    def upload_blob(self, data, overwrite=False, etag=None, match_condition=None):
        self.uploads += 1
        if self.uploads == 1:
            raise ResourceModifiedError("simulated concurrent writer")
        super().upload_blob(data, overwrite=overwrite, etag=etag, match_condition=match_condition)


class _FakeContainer:
    def __init__(self, store, blob_cls=_FakeBlob):
        self.store = store
        self.blob_cls = blob_cls

    def get_blob_client(self, name):
        return self.blob_cls(self.store, name)

    def upload_blob(self, name, data, overwrite=False):
        self.store[name] = (data, f"etag-{len(data)}")


class _FakeService:
    def __init__(self, container):
        self._container = container

    def get_container_client(self, name):
        return self._container


class BlobTransportTests(unittest.TestCase):
    def test_blob_name_includes_camera_and_extension(self):
        name = blob_transport.blob_name(camera_id="cam-1", when=0)
        self.assertTrue(name.startswith("cam-1/"))
        self.assertTrue(name.endswith(".jpg"))
        self.assertEqual(name.count("/"), 1)

    def test_blob_name_defaults_camera(self):
        self.assertTrue(blob_transport.blob_name(when=0).startswith("cam/"))

    def test_blob_name_in_container_strips_container_prefix(self):
        self.assertEqual(blob_transport.blob_name_in_container("raw/cam/x.jpg", "raw"), "cam/x.jpg")

    def test_blob_name_in_container_leaves_plain_name(self):
        self.assertEqual(blob_transport.blob_name_in_container("cam/x.jpg", "raw"), "cam/x.jpg")

    def test_camera_from_name_none_for_reserved_legacy(self):
        self.assertIsNone(blob_transport.camera_from_name("raw/cam/x.jpg", "raw"))

    def test_camera_from_name_returns_multi_camera(self):
        self.assertEqual(blob_transport.camera_from_name("raw/cam-3/x.jpg", "raw"), "cam-3")

    def test_camera_from_name_without_container_prefix(self):
        self.assertEqual(blob_transport.camera_from_name("cam-3/x.jpg", "raw"), "cam-3")

    def test_camera_frame_name(self):
        self.assertEqual(blob_transport.camera_frame_name("cam-3"), "frames/cam-3.jpg")

    def test_make_blob_sink_uploads_encoded_jpeg(self):
        store = {}
        sink = blob_transport.make_blob_sink(_FakeService(_FakeContainer(store)), container="raw")
        frame = np.full((4, 6, 3), 200, dtype=np.uint8)
        self.assertIs(sink(frame), frame)

        self.assertEqual(len(store), 1)
        name = next(iter(store))
        data = store[name][0]
        self.assertTrue(name.startswith("cam/"))
        self.assertTrue(data.startswith(JPEG_SOI))

    def test_make_blob_sink_swallows_upload_errors(self):
        class _Boom:
            def upload_blob(self, *args, **kwargs):
                raise OSError("network down")

        sink = blob_transport.make_blob_sink(_FakeService(_Boom()), container="raw")
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        self.assertIs(sink(frame), frame)  # must not raise

    def test_make_blob_sink_from_connection_string_builds_sink(self):
        store = {}
        service = _FakeService(_FakeContainer(store))
        with mock.patch(
            "azure.storage.blob.BlobServiceClient.from_connection_string", return_value=service
        ):
            sink = blob_transport.make_blob_sink_from_connection_string(
                "UseDevelopmentStorage=true", container="raw", camera_id="cam-9"
            )
        sink(np.zeros((2, 2, 3), dtype=np.uint8))
        self.assertTrue(next(iter(store)).startswith("cam-9/"))

    def test_upload_jpeg_writes_named_blob(self):
        store = {}
        blob_transport.upload_jpeg(_FakeContainer(store), blob_transport.FRAME_BLOB, b"data")
        self.assertEqual(store[blob_transport.FRAME_BLOB][0], b"data")

    def test_append_csv_adds_header_on_first_write(self):
        store = {}
        row = csv_log.format_row("2026-01-01 00:00:00", 2)
        blob_transport.append_csv(_FakeContainer(store), blob_transport.CSV_BLOB, row)
        self.assertEqual(
            store[blob_transport.CSV_BLOB][0],
            b"Timestamp,Person_Count\r\n2026-01-01 00:00:00,2\r\n",
        )

    def test_append_csv_appends_to_existing_without_second_header(self):
        store = {
            blob_transport.CSV_BLOB: (
                b"Timestamp,Person_Count\r\n2026-01-01 00:00:00,2\r\n",
                "etag-x",
            )
        }
        row = csv_log.format_row("2026-01-01 00:00:05", 1)
        blob_transport.append_csv(_FakeContainer(store), blob_transport.CSV_BLOB, row)

        data = store[blob_transport.CSV_BLOB][0]
        self.assertTrue(data.endswith(b"2026-01-01 00:00:05,1\r\n"))
        self.assertEqual(data.count(b"Timestamp,Person_Count"), 1)

    def test_append_csv_retries_after_etag_conflict(self):
        store = {}
        container = _FakeContainer(store, blob_cls=_RacyBlob)
        row = csv_log.format_row("2026-01-01 00:00:00", 2)
        blob_transport.append_csv(container, blob_transport.CSV_BLOB, row)

        self.assertEqual(
            store[blob_transport.CSV_BLOB][0],
            b"Timestamp,Person_Count\r\n2026-01-01 00:00:00,2\r\n",
        )


if __name__ == "__main__":
    unittest.main()
