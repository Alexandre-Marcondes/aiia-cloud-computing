"""SLS cloud receiver: count people in frames uploaded from the local machine.

Runs as a long-lived service on the Azure VM (Part 2, Task 2.3). The local
client POSTs a raw JPEG to ``/frame`` with each captured frame; the receiver
decodes it, counts people with the shared :class:`detection.PersonDetector`,
appends the count to a CSV, and overwrites an annotated frame. By default both
outputs go to the Apache document root (``/var/www/html``), where the static
``web/`` page polls ``database.csv`` and ``processed_frame.jpg`` every second.

The HTTP layer is stdlib-only; detection reuses the same modules as the local
pipeline. Requests are serialized with a lock because the detector and the
matplotlib plotter are not thread-safe.
"""

import argparse
import csv
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

import csv_log
from detection import PersonDetector
from paths import ensure_parent, resolve_path
from pipeline import process_sample
from plotting import PlotDisplay
from stats import PersonStats
from transport import FRAME_PATH, decode_jpeg

HEALTH_PATH = "/health"
MAX_FRAME_BYTES = 5_000_000
# Reserved camera id: a frame tagged with it is treated as the legacy single camera.
RESERVED_CAMERA_ID = "cam"
# Per-frame telemetry schema served to the frontend alongside database.csv.
# ProcessingMs is the total (decode + queue + service); QueueMs is the wait to
# acquire the processing lock and ServiceMs is the time holding it.
PROCESSING_CSV_HEADER = ["Timestamp", "Camera", "ProcessingMs", "QueueMs", "ServiceMs"]


class ProcessingCsvWriter:
    """Append per-frame processing times to a CSV, one row per processed frame.

    Writes are serialized with a lock so concurrent request threads cannot
    interleave lines; the header is written exactly once, when the file is
    missing or empty.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, camera, processing_ms, queue_ms, service_ms):
        """Append one ``Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs`` row."""
        ensure_parent(self.path)
        row = [
            csv_log.now_timestamp(),
            camera,
            f"{processing_ms:.1f}",
            f"{queue_ms:.1f}",
            f"{service_ms:.1f}",
        ]
        with self._lock:
            needs_header = not self.path.exists() or self.path.stat().st_size == 0
            with open(self.path, mode="a", newline="") as csv_file:
                writer = csv.writer(csv_file)
                if needs_header:
                    writer.writerow(PROCESSING_CSV_HEADER)
                writer.writerow(row)


def normalize_camera(camera_id):
    """Map an absent/empty/reserved camera id to the legacy ``None``."""
    if not camera_id or camera_id == RESERVED_CAMERA_ID:
        return None
    return camera_id


def build_processor(detector, stats, csv_path, frame_out, plotter):
    """Return a thread-safe ``(frame, camera=None) -> (count, queue_ms, service_ms)``.

    Legacy frames (``camera=None``) overwrite the configured ``frame_out``; a
    multi-camera frame is written to ``frames/<camera>.jpg`` beside it.

    The returned timings split the in-receiver cost: ``queue_ms`` is the wait to
    acquire the processing lock and ``service_ms`` is the time holding it.
    """
    lock = threading.Lock()

    def process(frame, camera=None):
        if camera is None:
            target = frame_out
        else:
            target = os.path.join(os.path.dirname(frame_out), "frames", f"{camera}.jpg")
            ensure_parent(target)
        wait_start = time.perf_counter()
        with lock:
            service_start = time.perf_counter()
            count, _ = process_sample(
                frame, detector, stats, csv_path, target, plotter, camera=camera
            )
            service_end = time.perf_counter()
        queue_ms = (service_start - wait_start) * 1000.0
        service_ms = (service_end - service_start) * 1000.0
        return count, queue_ms, service_ms

    return process


def warm_up(detector, shape=(480, 640, 3)):
    """Load the model and run one inference so the first request isn't slow."""
    start = time.perf_counter()
    detector.count_persons(np.zeros(shape, dtype=np.uint8))
    print(f"Model warmed up in {time.perf_counter() - start:.1f}s")


def make_handler(processor, max_bytes=MAX_FRAME_BYTES, processing_csv=None):
    """Build the request handler class serving ``/frame`` (POST) and ``/health``.

    When ``processing_csv`` is given, each processed frame appends one telemetry
    row there (see :class:`ProcessingCsvWriter`).
    """

    class FrameHandler(BaseHTTPRequestHandler):
        server_version = "SLSCloudReceiver/0.1"

        def do_GET(self):
            if self.path == HEALTH_PATH:
                self._send_json(200, {"status": "ok"})
            else:
                self.send_error(404, "not found")

        def do_POST(self):
            if self.path != FRAME_PATH:
                self.send_error(404, "not found")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length <= 0:
                self.send_error(400, "missing frame body")
                return
            if length > max_bytes:
                self.send_error(413, "frame too large")
                return
            data = self.rfile.read(length)
            start = time.perf_counter()
            try:
                frame = decode_jpeg(data)
            except ValueError as exc:
                self.send_error(400, str(exc))
                return
            camera = normalize_camera(self.headers.get("X-Camera-Id"))
            count, queue_ms, service_ms = processor(frame, camera)
            processing_ms = (time.perf_counter() - start) * 1000.0
            if processing_csv is not None:
                processing_csv.append(camera or "cam", processing_ms, queue_ms, service_ms)
            print(
                f"[receiver] frame {len(data)} B -> count={count} "
                f"processing={processing_ms:.0f} ms",
                flush=True,
            )
            self._send_json(
                200,
                {"count": count, "camera": camera, "processing_ms": round(processing_ms, 1)},
            )

        def _send_json(self, status, payload):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            sys.stderr.write(f"[receiver] {self.address_string()} - {fmt % args}\n")

    return FrameHandler


class ReceiverServer(ThreadingHTTPServer):
    """Threaded server that releases the port promptly on shutdown."""

    daemon_threads = True
    allow_reuse_address = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default="0.0.0.0", help="interface to bind (default: %(default)s)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="port to listen on (default: %(default)s)"
    )
    parser.add_argument(
        "--csv",
        default="data/database.csv",
        help="CSV output path, schema Timestamp,Person_Count (default: %(default)s)",
    )
    parser.add_argument(
        "--frame-out",
        default="data/processed_frame.jpg",
        help="annotated frame output path (default: %(default)s)",
    )
    parser.add_argument(
        "--plot-out",
        default="data/plot.png",
        help="chart image output path (default: %(default)s)",
    )
    parser.add_argument(
        "--processing-csv",
        default="data/processing.csv",
        help="per-frame processing-time CSV path, schema "
        "Timestamp,Camera,ProcessingMs,QueueMs,ServiceMs (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if not 0 < args.port < 65536:
        parser.error("--port must be between 1 and 65535")
    return args


def main(argv=None):
    """Entry point; serves until interrupted."""
    args = parse_args(argv)
    csv_path = resolve_path(args.csv)
    frame_out = resolve_path(args.frame_out)
    plot_out = resolve_path(args.plot_out)
    processing_csv_path = resolve_path(args.processing_csv)
    for path in (csv_path, frame_out, plot_out, processing_csv_path):
        ensure_parent(path)
    plotter = PlotDisplay(plot_out, no_display=True)
    detector = PersonDetector()
    warm_up(detector)
    processor = build_processor(detector, PersonStats(), csv_path, frame_out, plotter)
    processing_csv = ProcessingCsvWriter(processing_csv_path)
    server = ReceiverServer(
        (args.host, args.port), make_handler(processor, processing_csv=processing_csv)
    )
    print(f"SLS cloud receiver listening on http://{args.host}:{args.port}{FRAME_PATH}")
    print(f"  writing {csv_path} and {frame_out}")
    print(f"  writing processing telemetry to {processing_csv_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nInterrupted; shutting down.")
    finally:
        server.server_close()
        plotter.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
