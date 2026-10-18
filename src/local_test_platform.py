"""SLS local test platform (video only).

Emulate the live webcam with a local video file: play the clip in real time
(looping at the end) and, every ``--interval`` seconds (default 5.0, a float),
detect and count people with YOLOv8n. Each sample is logged to CSV, saved as an
annotated frame, and charted; the annotated frame is also shown in a window
while the clip keeps playing. Pass ``--fast`` to seek straight to each sample
instead of waiting, for quick checks.

This is the deterministic, video-only Part 1 demo. For the live webcam (or the
same local video) use ``local_stream.py``; both share the loops in
:mod:`runner`.

Importing this module is side-effect free: the main loop, YOLO model loading,
and video access only happen inside :func:`main`.
"""

import argparse
import sys

import cv2

from detection import PersonDetector
from paths import ensure_parent, resolve_path
from plotting import PlotDisplay, has_display
from runner import make_local_sink, run_video
from stats import PersonStats

WINDOW = "SLS local test platform"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--video",
        default="data/people_walking.mp4",
        help="local video file to sample from (default: %(default)s)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds of real time (or video time with --fast) between samples "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="do not wait in real time: seek straight to each sample (quick checks)",
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
        help="stop after this many samples, 0 = unlimited (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be a positive number of seconds")
    if args.max_samples < 0:
        parser.error("--max-samples must be >= 0")
    return args


def main(argv=None):
    """Entry point; returns a process exit code."""
    args = parse_args(argv)
    csv_path = resolve_path(args.csv)
    frame_out = resolve_path(args.frame_out)
    plot_out = resolve_path(args.plot_out)
    for path in (csv_path, frame_out, plot_out):
        ensure_parent(path)
    window = WINDOW if not args.no_display and has_display() else None
    plotter = PlotDisplay(plot_out, no_display=args.no_display)
    detector = PersonDetector()
    stats = PersonStats()
    sink = make_local_sink(detector, stats, csv_path, frame_out, plotter)
    try:
        return run_video(
            args.video,
            sink,
            interval=args.interval,
            max_samples=args.max_samples,
            fast=args.fast,
            window=window,
        )
    finally:
        plotter.close()
        if window is not None:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    sys.exit(main())
