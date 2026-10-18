"""Reusable sampling loops shared by the local demo scripts.

Both local scripts deliver each sampled frame to an ``on_frame`` callback; only
the frame source and its pacing differ. This module keeps those loops in one
place:

- :func:`run_video` plays a local file, either in real time (emulating a live
  feed, looping at the end) or, with ``fast=True``, by seeking straight to each
  sample.
- :func:`run_live` pulls the latest frame from a threaded HLS reader
  (:class:`sources.FrameGrabber`), which is already paced by the stream.

The callback returns the image to display: the annotated frame when processing
locally (:func:`make_local_sink`) or the original frame when uploading it to the
cloud (:func:`transport.make_cloud_sink`). Each loop returns a process exit code
(0 on success).
"""

import sys
import time

import cv2

from paths import resolve_path
from pipeline import process_sample
from sources import FrameGrabber, VideoError, VideoPlayer, VideoSampler


def show_frame(window, frame):
    """Show ``frame`` in ``window``; return True if the user pressed 'q'."""
    cv2.imshow(window, frame)
    return (cv2.waitKey(1) & 0xFF) == ord("q")


def make_local_sink(detector, stats, csv_path, frame_out, plotter):
    """Build an ``on_frame`` callback that runs the local pipeline on each frame."""

    def sink(frame):
        _, annotated = process_sample(frame, detector, stats, csv_path, frame_out, plotter)
        return annotated

    return sink


def _run_fast(video_path, on_frame, interval, max_samples, window):
    """Seek straight to each sample timestamp; no real-time waiting."""
    try:
        sampler = VideoSampler(video_path)
    except VideoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    samples = 0
    try:
        while not max_samples or samples < max_samples:
            frame, _ = sampler.next_frame(interval)
            display = on_frame(frame)
            samples += 1
            if window is not None and show_frame(window, display):
                break
    except VideoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; shutting down.")
    finally:
        sampler.close()
    return 0


def _run_emulated(video_path, on_frame, interval, max_samples, window):
    """Play the clip in real time, sampling one frame every ``interval`` seconds.

    Frames are read sequentially and paced to the clip's fps. Reads between
    ticks are discarded and the window keeps showing the last processed frame.
    There are no long blocking sleeps, so the loop stays responsive — press 'q'
    in the window to stop early.
    """
    try:
        player = VideoPlayer(video_path)
    except VideoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    frame_period = 1.0 / player.fps
    last_shown = None
    last_tick = time.monotonic()
    next_frame_at = last_tick
    samples = 0
    try:
        while not max_samples or samples < max_samples:
            now = time.monotonic()
            if now >= next_frame_at:
                frame = player.read()
                next_frame_at += frame_period
                if next_frame_at < now:
                    next_frame_at = now + frame_period  # skip frames missed while busy
                if now - last_tick >= interval:
                    last_shown = on_frame(frame)
                    last_tick = now
                    samples += 1
                elif last_shown is None:
                    last_shown = frame
            if window is not None:
                if show_frame(window, last_shown):
                    break
            else:
                time.sleep(0.001)  # yield when headless instead of spinning
    except VideoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted; shutting down.")
    finally:
        player.close()
    return 0


def run_video(video, on_frame, *, interval, max_samples, fast, window=None):
    """Run the sampling loop over a local video file (real time, or ``fast``)."""
    video_path = resolve_path(video)
    runner = _run_fast if fast else _run_emulated
    return runner(video_path, on_frame, interval, max_samples, window)


def run_live(page_url, on_frame, *, interval, max_samples):
    """Sample the latest live frame at the configured interval."""
    grabber = FrameGrabber(page_url).start()
    last_seq = 0
    samples = 0
    try:
        while not max_samples or samples < max_samples:
            new_seq, frame = grabber.read(last_seq=last_seq, timeout=interval)
            if frame is None:
                print("Waiting for the stream to deliver a frame...")
                continue
            if new_seq == last_seq:
                print("No new frame; the stream may be stalled.")
                continue
            last_seq = new_seq
            on_frame(frame)
            samples += 1
    except KeyboardInterrupt:
        print("\nInterrupted; shutting down.")
    finally:
        grabber.stop()
    return 0
