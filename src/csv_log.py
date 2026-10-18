"""CSV persistence of per-sample person counts.

The row contract — header, timestamp format, and comma layout — lives here so
every pipeline serializes samples identically: the local chart, the VM receiver,
and the serverless function all import from this module.
"""

import csv
import io
from datetime import datetime
from pathlib import Path

# Legacy single-camera schema shared with the web frontend's CSV parser.
CSV_HEADER = ["Timestamp", "Person_Count"]

# Multi-camera schema, one row per camera per sample.
CSV_HEADER_V2 = ["Timestamp", "Camera", "Person_Count"]

# Per-frame processing telemetry: total, lock/queue wait, and service time (ms).
PROCESSING_HEADER = ["Timestamp", "Camera", "ProcessingMs", "QueueMs", "ServiceMs"]

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_timestamp(when=None):
    """Return ``when`` (default now) in the shared ``YYYY-MM-DD HH:mm:ss`` format."""
    return (when or datetime.now()).strftime(TIMESTAMP_FORMAT)


def _csv_line(values):
    """Serialize ``values`` as one CSV line (csv module's line terminator)."""
    buffer = io.StringIO()
    csv.writer(buffer).writerow(values)
    return buffer.getvalue()


HEADER_LINE = _csv_line(CSV_HEADER)
HEADER_LINE_V2 = _csv_line(CSV_HEADER_V2)
HEADER_LINE_PROCESSING = _csv_line(PROCESSING_HEADER)


def _field_count(line):
    """Number of columns parsed from ``line`` (0 for an empty/blank line)."""
    return len(next(csv.reader(io.StringIO(line)), []))


def _header_line_for(row):
    """Pick the header matching ``row``'s field count (legacy 2, v2 3, processing 5)."""
    return {
        len(CSV_HEADER): HEADER_LINE,
        len(CSV_HEADER_V2): HEADER_LINE_V2,
        len(PROCESSING_HEADER): HEADER_LINE_PROCESSING,
    }.get(_field_count(row), HEADER_LINE_V2)


def format_row(timestamp, person_count, camera=None):
    """Serialize one sample row, including its line terminator.

    ``camera is None`` keeps the legacy ``Timestamp,Person_Count`` layout; otherwise
    the row is ``Timestamp,Camera,Person_Count``.
    """
    if camera is None:
        return _csv_line([timestamp, person_count])
    return _csv_line([timestamp, camera, person_count])


def format_processing_row(timestamp, camera, processing_ms, queue_ms, service_ms):
    """Serialize one per-frame telemetry row (5 columns), including its terminator."""
    return _csv_line(
        [timestamp, camera, f"{processing_ms:.1f}", f"{queue_ms:.1f}", f"{service_ms:.1f}"]
    )


def append_row(existing_bytes, row):
    """Append the CSV ``row`` to ``existing_bytes``, adding the header if empty.

    The header is chosen from ``row``'s field count. If the existing file's
    header has a different column count than ``row`` (a switch between the
    legacy single-camera and the multi-camera schema), the content is reset to a
    fresh header plus ``row`` — so changing the camera count never leaves a file
    that mixes two schemas.
    """
    if existing_bytes:
        first_line = existing_bytes.decode("utf-8", "replace").split("\n", 1)[0]
        if _field_count(first_line) == _field_count(row):
            return existing_bytes + row.encode("utf-8")
    return (_header_line_for(row) + row).encode("utf-8")


def _existing_header_fields(path):
    """Column count of ``path``'s header line (0 if the file is missing/empty)."""
    try:
        with open(path, newline="") as csv_file:
            return _field_count(csv_file.readline())
    except FileNotFoundError:
        return 0


def log_sample(csv_path, timestamp, person_count, camera=None):
    """Append one sample row to ``csv_path``.

    The header is (re)written when the file is missing, empty, or has a different
    column count than the new row — i.e. when the run switches between the legacy
    single-camera schema and the multi-camera one. The file is reset in that case,
    so changing the camera count never leaves mixed schemas behind; otherwise the
    row is appended under the existing header.
    """
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = format_row(timestamp, person_count, camera)
    if _field_count(row) != _existing_header_fields(path):
        with open(path, mode="w", newline="") as csv_file:
            csv_file.write(_header_line_for(row))
            csv_file.write(row)
        return
    with open(path, mode="a", newline="") as csv_file:
        csv_file.write(row)
