"""End-to-end latency probe for the Part 3 serverless pipeline.

Uploads frames one at a time to the private ``raw`` container and measures the
**upload-to-visible** latency: the wall time until each frame's result shows up
in ``$web/database.csv``. That closes the gap between the function's server-side
``DurationMs`` (Application Insights) and what a viewer actually experiences,
covering the parts the invocation timing cannot see: Event Grid delivery, the
trigger, the ``$web`` write, and the client's own poll.

The pipeline is asynchronous (the function writes to a *different* container, so
no response comes back), therefore each frame is sent alone and the probe waits
for the CSV to change before the next send. That attributes every update to its
own upload and also flags duplicate rows (at-least-once delivery). It reports the
same statistics as the Part 2 probe (:mod:`load_test`).

Run against the real storage account with the project venv::

    export DATA_STORAGE="$(az storage account show-connection-string \
        -n <storage-account> -g <resource-group> --query connectionString -o tsv)"
    venv/bin/python src/measure_serverless.py --frames 10 --interval 0.5 \
        --image data/processed_frame.jpg

By default it sends a reproducible noise frame; pass ``--image`` to use a real
captured frame instead (representative for the detector and the JPEG size).
"""

import argparse
import os
import statistics
import sys
import time

from azure.core.exceptions import ResourceNotFoundError

import blob_transport

DEFAULT_POLL = 0.1
DEFAULT_TIMEOUT = 30.0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--blob-connection-string",
        default=None,
        help="storage connection string (default: $DATA_STORAGE)",
    )
    parser.add_argument(
        "--raw-container",
        default=blob_transport.DEFAULT_CONTAINER,
        help="upload/trigger container (default: %(default)s)",
    )
    parser.add_argument(
        "--web-container",
        default="$web",
        help="container the function writes results to (default: %(default)s)",
    )
    parser.add_argument(
        "--csv-blob",
        default=blob_transport.CSV_BLOB,
        help="CSV blob name to watch (default: %(default)s)",
    )
    parser.add_argument("--frames", type=int, default=20, help="number of frames to send")
    parser.add_argument(
        "--interval", type=float, default=0.5, help="seconds between frames (default: %(default)s)"
    )
    parser.add_argument(
        "--image", default=None, help="real JPEG frame to send (default: synthetic)"
    )
    parser.add_argument(
        "--size", default="1280x720", help="synthetic frame WxH (default: %(default)s)"
    )
    parser.add_argument("--camera-id", default="measure", help="blob prefix for uploads")
    parser.add_argument(
        "--poll",
        type=float,
        default=DEFAULT_POLL,
        help="seconds between checks (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="per-frame timeout (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if args.frames <= 0:
        parser.error("--frames must be positive")
    if args.poll <= 0:
        parser.error("--poll must be positive")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def wait_until(predicate, timeout, poll, clock=time.monotonic, sleep=time.sleep):
    """Return seconds until ``predicate()`` is true, or ``None`` if it times out."""
    start = clock()
    while True:
        if predicate():
            return clock() - start
        if clock() - start >= timeout:
            return None
        sleep(poll)


def _etag(blob):
    """Current ETag of ``blob``, or ``None`` if it does not exist yet."""
    try:
        return blob.get_blob_properties().etag
    except ResourceNotFoundError:
        return None


def _counts(blob):
    """Person counts parsed from the CSV blob's data rows (oldest first).

    The schema is header-driven: the count lives in the ``Person_Count`` column —
    index 1 in the legacy ``Timestamp,Person_Count`` schema, index 2 in the
    multi-camera ``Timestamp,Camera,Person_Count`` schema.
    """
    try:
        data = blob.download_blob().readall()
    except ResourceNotFoundError:
        return []
    counts = []
    count_col = 1
    for line in data.decode("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if line.startswith("Timestamp"):
            if "Person_Count" in parts:
                count_col = parts.index("Person_Count")
            continue
        if len(parts) > count_col and parts[count_col].strip().isdigit():
            counts.append(int(parts[count_col]))
    return counts


def measure_frame(
    raw, image_bytes, name, csv_blob, poll, timeout, clock=time.monotonic, sleep=time.sleep
):
    """Upload one frame; return its upload-to-visible and cleanup latencies.

    ``raw`` is the container client, ``name`` the blob to write, and ``csv_blob``
    the result blob to watch. The CSV is watched by ETag so the latency does not
    depend on the CSV's second-resolution timestamps.
    """
    etag_before = _etag(csv_blob)
    counts_before = len(_counts(csv_blob))

    raw.get_blob_client(name).upload_blob(image_bytes, overwrite=True)

    e2e = wait_until(lambda: _etag(csv_blob) != etag_before, timeout, poll, clock, sleep)
    deleted = wait_until(
        lambda: not raw.get_blob_client(name).exists(), timeout, poll, clock, sleep
    )
    counts = _counts(csv_blob)
    return {
        "e2e": e2e,
        "deleted": deleted,
        "appended": len(counts) - counts_before,
        "count": counts[-1] if counts else None,
    }


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def _build_frame(args):
    """Return the JPEG bytes to send: a real file, or a reproducible noise frame."""
    if args.image:
        with open(args.image, "rb") as handle:
            return handle.read()
    import numpy as np

    from transport import encode_jpeg

    width, height = (int(part) for part in args.size.lower().split("x"))
    frame = np.random.default_rng(0).integers(0, 256, (height, width, 3), dtype=np.uint8)
    return encode_jpeg(frame)


def main(argv=None):
    args = parse_args(argv)
    connection_string = args.blob_connection_string or os.environ.get("DATA_STORAGE")
    if not connection_string:
        print("Error: pass --blob-connection-string or set $DATA_STORAGE.", file=sys.stderr)
        return 2

    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient.from_connection_string(connection_string)
    raw = service.get_container_client(args.raw_container)
    web = service.get_container_client(args.web_container)
    csv_blob = web.get_blob_client(args.csv_blob)
    image_bytes = _build_frame(args)
    print(
        f"raw '{args.raw_container}' -> web '{args.web_container}/{args.csv_blob}'  "
        f"frame {len(image_bytes) / 1024.0:.0f} KiB  frames {args.frames}"
    )

    e2e_ms, cleanup_ms, counts = [], [], []
    appended_total = 0
    start = time.perf_counter()
    for index in range(args.frames):
        name = blob_transport.blob_name(camera_id=args.camera_id)
        try:
            result = measure_frame(raw, image_bytes, name, csv_blob, args.poll, args.timeout)
        except Exception as exc:  # keep probing after a transient failure
            print(f"  frame {index + 1}: failed ({exc})")
            continue
        appended_total += max(result["appended"], 0)
        if result["count"] is not None:
            counts.append(result["count"])
        if result["e2e"] is None:
            print(f"  frame {index + 1}: no result within {args.timeout:.0f} s")
        else:
            e2e_ms.append(result["e2e"] * 1000.0)
            if result["deleted"] is not None:
                cleanup_ms.append(result["deleted"] * 1000.0)
            print(
                f"  frame {index + 1}: upload->visible {result['e2e'] * 1000:7.1f} ms  "
                f"raw cleared {_ms(result['deleted'])}  count {result['count']}"
            )
        if args.interval:
            time.sleep(args.interval)
    wall = time.perf_counter() - start

    if not e2e_ms:
        print("no frames completed")
        return 1

    def line(label, values):
        if not values:
            return
        print(
            f"{label}: min {min(values):.0f}  mean {statistics.mean(values):.0f}  "
            f"median {statistics.median(values):.0f}  p95 {_percentile(values, 0.95):.0f}  "
            f"max {max(values):.0f} ms"
        )

    print(f"\nsent {len(e2e_ms)}/{args.frames} in {wall:.1f} s")
    line("upload->visible", e2e_ms)
    line("raw cleared   ", cleanup_ms)
    if counts:
        print(f"detected people : mean {statistics.mean(counts):.1f}  max {max(counts)}")
    expected = len(e2e_ms)
    note = "" if appended_total == expected else "  <-- check duplicates/losses"
    print(f"csv rows added  : {appended_total} (expected {expected}){note}")
    return 0


def _ms(value):
    return "n/a" if value is None else f"{value * 1000:.1f} ms"


if __name__ == "__main__":
    sys.exit(main())
