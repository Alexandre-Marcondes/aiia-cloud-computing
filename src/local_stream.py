"""SLS local stream pipeline: the live webcam, or a local video as a stand-in.

Pick the frame source with ``--source``:

- a **local video** (the default, ``data/people_walking.mp4``) is played in real
  time — emulating the live feed, looping at the end — and sampled every
  ``--interval`` seconds (``--fast`` seeks straight to each sample instead);
- **``live``** (or a SkylineWebcams page URL) uses the fixed Salò webcam, where
  ``FrameGrabber`` reads the HLS stream on a background thread and the latest
  frame is sampled every ``--interval`` seconds.

By default each sample is counted locally with YOLOv8n person-only detection and
logged to CSV plus a running-statistics line, an annotated frame, and a
matplotlib chart. Pass ``--cloud-url`` to instead upload each frame to a
``cloud_receiver.py`` on the Azure VM (Part 2), or ``--blob-connection-string``
to upload it to a storage account's ``raw`` container for the serverless
function (Part 3); in both upload modes detection happens in the cloud and no
local CSV/frame/chart is written. This is the unified counterpart of the
video-only ``local_test_platform.py``; both share the loops in :mod:`runner`.

Importing this module is side-effect free: the main loop, YOLO model loading,
and source access only happen inside :func:`main`.
"""

import argparse
import sys
import threading
import time

import cv2

from blob_transport import DEFAULT_CONTAINER, make_blob_sink_from_connection_string
from detection import PersonDetector
from multicam import SharedVideoSource, compose_grid, run_cameras
from paths import ensure_parent, resolve_path
from plotting import PlotDisplay, has_display
from runner import make_local_sink, run_live, run_video
from sources import VideoError, resolve_source
from stats import PersonStats
from transport import DEFAULT_TIMEOUT, make_cloud_sink

WINDOW = "SLS local stream"


def camera_ids(base, n):
    """Return the ordered ids ``<base>-1`` .. ``<base>-n`` for ``n`` cameras."""
    return [f"{base}-{i}" for i in range(1, n + 1)]


def _bound_sink(sink, seconds):
    """Wrap a single-camera ``sink`` to end the run after ``seconds`` (0 = never)."""
    if seconds <= 0:
        return sink
    deadline = time.monotonic() + seconds

    def bounded(frame):
        if time.monotonic() >= deadline:
            raise KeyboardInterrupt
        return sink(frame)

    return bounded


def _mosaic_display(ids):
    """Return an ``on_tick`` callback showing a labelled mosaic of the cameras."""
    latest = {}
    lock = threading.Lock()

    def on_tick(camera_id, frame):
        with lock:
            latest[camera_id] = frame
            if len(latest) < len(ids):
                return
            grid = compose_grid([latest[cid] for cid in ids], ids)
            cv2.imshow(WINDOW, grid)
            cv2.waitKey(1)

    return on_tick


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default="data/people_walking.mp4",
        help="local video file, SkylineWebcams page URL, or the alias 'live' "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between samples (default: %(default)s)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="local video only: seek straight to each sample instead of playing in real time",
    )
    upload = parser.add_mutually_exclusive_group()
    upload.add_argument(
        "--cloud-url",
        default=None,
        help="upload each sampled frame to this receiver (e.g. http://VM_IP:8000) "
        "instead of processing locally",
    )
    upload.add_argument(
        "--blob-connection-string",
        default=None,
        help="upload each sampled frame to a storage account's raw container "
        "(Part 3 serverless) instead of processing locally",
    )
    parser.add_argument(
        "--raw-container",
        default=DEFAULT_CONTAINER,
        help="container for --blob-connection-string uploads (default: %(default)s)",
    )
    parser.add_argument(
        "--camera-id",
        default=None,
        help="identifier sent with uploaded frames (multi-camera runs; default: none)",
    )
    parser.add_argument(
        "--cloud-timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="upload timeout in seconds (default: %(default)s)",
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
        "--no-display",
        action="store_true",
        help="disable the GUI windows (chart + frame preview)",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=0,
        help="stop after this many samples, 0 = unlimited; per camera in a "
        "multi-camera run (default: %(default)s)",
    )
    parser.add_argument(
        "--cameras",
        type=int,
        default=1,
        help="drive this many pseudo-cameras from one local source; needs an "
        "upload target and a local video (default: %(default)s)",
    )
    parser.add_argument(
        "--phase-offset",
        type=float,
        default=0.0,
        help="multi-camera only: seconds each successive pseudo-camera is behind "
        "the previous in the clip, so they show different points in time "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--seconds",
        type=float,
        default=0,
        help="stop after this many seconds, 0 = unlimited (default: %(default)s)",
    )
    parser.add_argument(
        "--show-streams",
        action="store_true",
        help="multi-camera only: show a labelled mosaic of the latest frame from each camera",
    )
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be a positive number of seconds")
    if args.max_samples < 0:
        parser.error("--max-samples must be >= 0")
    if args.seconds < 0:
        parser.error("--seconds must be >= 0")
    if args.cameras < 1:
        parser.error("--cameras must be >= 1")
    if args.phase_offset < 0:
        parser.error("--phase-offset must be >= 0")
    if args.phase_offset > 0 and args.cameras <= 1:
        parser.error("--phase-offset needs --cameras > 1")
    if args.cameras > 1:
        if args.fast:
            parser.error(
                "--fast only applies to a single camera; multi-camera uses a shared source"
            )
        if resolve_source(args.source)[0] == "live":
            parser.error("--cameras > 1 needs a local video source, not a live stream")
        if not args.cloud_url and not args.blob_connection_string:
            parser.error(
                "--cameras > 1 needs an upload target (--cloud-url or --blob-connection-string)"
            )
    return args


def _run_multi(args):
    """Drive ``--cameras`` pseudo-cameras from one shared local video source."""
    base = args.camera_id or "cam"
    ids = camera_ids(base, args.cameras)
    if args.cloud_url:
        specs = [
            (cid, make_cloud_sink(args.cloud_url, camera_id=cid, timeout=args.cloud_timeout))
            for cid in ids
        ]
        print(f"Uploading {len(ids)} cameras {ids} to {args.cloud_url} (no local processing)")
    else:
        specs = [
            (
                cid,
                make_blob_sink_from_connection_string(
                    args.blob_connection_string,
                    container=args.raw_container,
                    camera_id=cid,
                ),
            )
            for cid in ids
        ]
        print(
            f"Uploading {len(ids)} cameras {ids} to blob container "
            f"'{args.raw_container}' (no local processing)"
        )
    display = _mosaic_display(ids) if args.show_streams and has_display() else None
    if args.phase_offset > 0:
        span = (args.cameras - 1) * args.phase_offset
        print(
            f"Phase offset {args.phase_offset}s/camera: cameras span {span:.1f}s "
            "of the clip (kept in a bounded frame buffer)."
        )
    try:
        source = SharedVideoSource(
            resolve_path(args.source), keep_seconds=(args.cameras - 1) * args.phase_offset
        )
    except VideoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    try:
        return run_cameras(
            source,
            specs,
            interval=args.interval,
            phase=args.phase_offset,
            max_samples=args.max_samples,
            seconds=args.seconds,
            display=display,
        )
    finally:
        if display is not None:
            cv2.destroyAllWindows()


def main(argv=None):
    """Entry point; returns a process exit code."""
    args = parse_args(argv)
    if args.cameras > 1:
        return _run_multi(args)
    mode, target = resolve_source(args.source)
    if args.fast and mode != "video":
        print("Error: --fast only applies to a local video source.", file=sys.stderr)
        return 2
    window = WINDOW if mode == "video" and not args.no_display and has_display() else None
    plotter = None
    if args.cloud_url:
        sink = make_cloud_sink(args.cloud_url, camera_id=args.camera_id, timeout=args.cloud_timeout)
        print(f"Uploading sampled frames to {args.cloud_url} (no local processing)")
    elif args.blob_connection_string:
        sink = make_blob_sink_from_connection_string(
            args.blob_connection_string, container=args.raw_container, camera_id=args.camera_id
        )
        print(
            f"Uploading sampled frames to blob container '{args.raw_container}' "
            "(no local processing)"
        )
    else:
        csv_path = resolve_path(args.csv)
        frame_out = resolve_path(args.frame_out)
        plot_out = resolve_path(args.plot_out)
        for path in (csv_path, frame_out, plot_out):
            ensure_parent(path)
        plotter = PlotDisplay(plot_out, no_display=args.no_display)
        sink = make_local_sink(PersonDetector(), PersonStats(), csv_path, frame_out, plotter)
    sink = _bound_sink(sink, args.seconds)
    try:
        if mode == "live":
            return run_live(target, sink, interval=args.interval, max_samples=args.max_samples)
        return run_video(
            target,
            sink,
            interval=args.interval,
            max_samples=args.max_samples,
            fast=args.fast,
            window=window,
        )
    finally:
        if plotter is not None:
            plotter.close()
        if window is not None:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
