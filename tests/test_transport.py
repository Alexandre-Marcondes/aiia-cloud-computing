"""Unit tests for src.transport (offline: local HTTP stub, no YOLO)."""

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from transport import (  # noqa: E402
    FRAME_PATH,
    decode_jpeg,
    encode_jpeg,
    normalize_endpoint,
    post_frame,
)


class _StubHandler(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).received.append((self.path, self.headers.get("X-Camera-Id"), body))
        payload = json.dumps({"count": 7}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class TransportTests(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        frame = np.zeros((8, 12, 3), dtype=np.uint8)
        frame[:, :, 1] = 128
        self.assertEqual(decode_jpeg(encode_jpeg(frame)).shape, frame.shape)

    def test_decode_rejects_garbage(self):
        with self.assertRaises(ValueError):
            decode_jpeg(b"not an image")

    def test_normalize_endpoint_appends_frame_path(self):
        self.assertEqual(normalize_endpoint("http://10.0.0.1:8000"), "http://10.0.0.1:8000/frame")
        self.assertEqual(normalize_endpoint("http://10.0.0.1:8000/"), "http://10.0.0.1:8000/frame")
        self.assertEqual(
            normalize_endpoint("http://10.0.0.1:8000/frame"), "http://10.0.0.1:8000/frame"
        )

    def test_post_frame_sends_jpeg_and_reads_json(self):
        _StubHandler.received = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}{FRAME_PATH}"
            frame = np.full((4, 4, 3), 200, dtype=np.uint8)
            result = post_frame(url, frame, camera_id="cam-1", timeout=5.0)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(result, {"count": 7})
        path, camera_id, body = _StubHandler.received[0]
        self.assertEqual(path, FRAME_PATH)
        self.assertEqual(camera_id, "cam-1")
        self.assertEqual(decode_jpeg(body).shape, (4, 4, 3))


if __name__ == "__main__":
    unittest.main()
