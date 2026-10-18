"""Load generator and latency probe for the cloud receiver (Part 2.5).

Sends synthetic (or supplied) JPEG frames to a ``cloud_receiver.py`` and reports
round-trip and server-side processing times. Run it against the VM's receiver
over a localhost/tunnel URL, with the project venv:

    python src/load_test.py --url http://127.0.0.1:8000 --frames 20

By default it builds a reproducible noise frame of the given size, which encodes
to a realistically large JPEG so upload sizes are representative. Pass
``--image PATH`` to use a real captured frame instead.
"""

import argparse
import statistics
import sys
import time

import numpy as np

from transport import DEFAULT_TIMEOUT, encode_jpeg, normalize_endpoint, post_frame


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="receiver base URL")
    parser.add_argument("--frames", type=int, default=20, help="number of frames to send")
    parser.add_argument(
        "--interval", type=float, default=0.0, help="seconds to wait between sends (default: none)"
    )
    parser.add_argument(
        "--image", default=None, help="real image/frame to send (default: synthetic)"
    )
    parser.add_argument(
        "--size", default="1280x720", help="synthetic frame WxH (default: %(default)s)"
    )
    parser.add_argument("--camera-id", default="load-test", help="X-Camera-Id header to send")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="per-request timeout"
    )
    args = parser.parse_args(argv)
    if args.frames <= 0:
        parser.error("--frames must be positive")
    return args


def make_frame(args):
    """Return the BGR frame to send: the supplied image, or a reproducible noise frame."""
    if args.image:
        import cv2

        frame = cv2.imread(args.image)
        if frame is None:
            raise SystemExit(f"cannot read image: {args.image}")
        return frame
    width, height = (int(part) for part in args.size.lower().split("x"))
    return np.random.default_rng(0).integers(0, 256, (height, width, 3), dtype=np.uint8)


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return ordered[index]


def main(argv=None):
    args = parse_args(argv)
    endpoint = normalize_endpoint(args.url)
    frame = make_frame(args)
    size_kib = len(encode_jpeg(frame)) / 1024.0
    height, width = frame.shape[:2]
    print(
        f"target {endpoint}  frame {width}x{height}  jpeg {size_kib:.0f} KiB  frames {args.frames}"
    )

    round_trips = []
    server_ms = []
    start = time.perf_counter()
    for index in range(args.frames):
        tick = time.perf_counter()
        try:
            response = post_frame(endpoint, frame, camera_id=args.camera_id, timeout=args.timeout)
        except (OSError, ValueError) as exc:
            print(f"  frame {index + 1}: failed ({exc})")
            continue
        elapsed_ms = (time.perf_counter() - tick) * 1000.0
        round_trips.append(elapsed_ms)
        if "processing_ms" in response:
            server_ms.append(float(response["processing_ms"]))
        print(
            f"  frame {index + 1}: round-trip {elapsed_ms:7.1f} ms  count {response.get('count')}"
        )
        if args.interval:
            time.sleep(args.interval)
    wall = time.perf_counter() - start

    if not round_trips:
        print("no frames delivered")
        return 1

    def line(label, values):
        if not values:
            return
        print(
            f"{label}: min {min(values):.0f}  "
            f"mean {statistics.mean(values):.0f}  "
            f"median {statistics.median(values):.0f}  "
            f"p95 {_percentile(values, 0.95):.0f}  "
            f"max {max(values):.0f} ms"
        )

    print(
        f"\nsent {len(round_trips)}/{args.frames} in {wall:.1f} s "
        f"({len(round_trips) / wall:.2f} fps)"
    )
    line("round-trip", round_trips)
    line("server    ", server_ms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
