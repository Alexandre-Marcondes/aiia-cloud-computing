"""Multi-camera scheduler for Part 4.

A single process plays one local clip and drives N pseudo-cameras from it. One
:class:`SharedVideoSource` decodes the clip in real time on a daemon thread;
:class:`CameraWorker` threads each sample the shared frame on a staggered
schedule (startup phase ``i * interval / n``) and hand it to a per-camera sink.
This keeps local decode cost to a single decoder, so a throughput sweep measures
the server rather than the sender.

With a non-zero phase offset the cameras also read the clip at different points
in time: :class:`SharedVideoSource` keeps a short ring buffer of recent frames
(encoded JPEG, to bound memory) and a worker with ``frame_lag = i * phase`` is
handed the frame from that many seconds ago, so the cameras show genuinely
different content instead of the same instant.

:func:`compose_grid` is a display-only helper for the optional ``--show-streams``
mosaic.
"""

import math
import threading
import time
from collections import deque

import cv2
import numpy as np

from sources import VideoError, VideoPlayer
from transport import decode_jpeg, encode_jpeg

# Time-shift buffer: keep at most this many frames per second (the offsets are
# seconds-scale, so sub-second resolution is plenty) and at most this much memory
# (JPEG bytes) — bounds the buffer regardless of the clip's resolution.
BUFFER_FPS = 4
MAX_BUFFER_BYTES = 96 << 20  # 96 MiB


def phase_offset(i, n, interval):
    """Return the startup delay (seconds) for camera ``i`` of ``n``.

    Cameras are evenly staggered across one ``interval`` so their ticks spread
    out instead of firing together.
    """
    return i * interval / n


def frame_offset(i, phase):
    """Return the clip-position lag (seconds) for camera ``i``.

    Camera ``i`` shows the clip ``i * phase`` seconds behind the live edge, so
    successive cameras show distinct points in time.
    """
    return i * phase


def nearest_by_time(buffer, target):
    """Return the ``(timestamp, jpeg)`` entry in ``buffer`` closest to ``target``."""
    return min(buffer, key=lambda item: abs(item[0] - target))


class SharedVideoSource:
    """Play one local clip in real time on a daemon thread.

    All cameras read the same newest frame via :meth:`latest_frame`; only this
    thread decodes (:class:`sources.VideoPlayer`), looping at the end of the
    clip. :meth:`close` stops the thread and releases the decoder.
    """

    def __init__(self, video_path, keep_seconds=0.0):
        self.video_path = str(video_path)
        self._player = VideoPlayer(self.video_path)
        self._cond = threading.Condition()
        self._frame = None
        self._done = False
        self._stop = threading.Event()
        # Optional time-shift buffer: the last ``keep_seconds`` of frames as
        # (monotonic timestamp, JPEG bytes), so a camera can be handed the frame
        # from ``keep`` seconds ago. JPEG plus a capped frame rate keeps the
        # buffer small; it is only enabled when a phase offset asks for it.
        self._keep_seconds = keep_seconds
        self._buffer_period = 1.0 / BUFFER_FPS
        self._buffer = None
        self._buffer_bytes = 0
        self._last_buffer_at = 0.0
        if keep_seconds > 0:
            self._buffer = deque()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        period = 1.0 / self._player.fps
        next_frame_at = time.monotonic()
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now < next_frame_at:
                    time.sleep(min(next_frame_at - now, 0.05))
                    continue
                try:
                    frame = self._player.read()
                except VideoError:
                    break
                jpeg = None
                if self._buffer is not None and now - self._last_buffer_at >= self._buffer_period:
                    jpeg = encode_jpeg(frame)
                with self._cond:
                    self._frame = frame
                    if jpeg is not None:
                        self._last_buffer_at = now
                        self._buffer.append((now, jpeg))
                        self._buffer_bytes += len(jpeg)
                        self._trim_buffer(now)
                    self._cond.notify_all()
                next_frame_at += period
                if next_frame_at < now:
                    next_frame_at = now + period
        finally:
            self._player.close()
            with self._cond:
                self._done = True
                self._cond.notify_all()

    def _trim_buffer(self, now):
        """Drop frames older than the keep window or beyond the memory cap."""
        cutoff = now - self._keep_seconds - 0.5
        while len(self._buffer) > 1 and (
            self._buffer[0][0] < cutoff or self._buffer_bytes > MAX_BUFFER_BYTES
        ):
            _, old = self._buffer.popleft()
            self._buffer_bytes -= len(old)

    def latest_frame(self, timeout=None):
        """Return the newest decoded frame, waiting until one exists.

        Returns immediately with the current frame if one has been decoded. If
        none exists yet, blocks until one arrives, the decoder finishes, or
        ``timeout`` elapses (returning ``None`` in the latter two cases).
        """
        with self._cond:
            if self._frame is None and not self._done:
                deadline = None if timeout is None else time.monotonic() + timeout
                while self._frame is None and not self._done:
                    if deadline is None:
                        self._cond.wait()
                        continue
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._cond.wait(remaining)
            return self._frame

    def frame_ago(self, seconds, timeout=None):
        """Return the frame captured closest to ``seconds`` ago (a time shift).

        Uses the ring buffer when one is kept; with no buffer (or before it
        fills) this falls back to the newest frame. Blocks for the first frame
        like :meth:`latest_frame` so a cold start does not return ``None``.
        """
        if self._buffer is None:
            return self.latest_frame(timeout=timeout)
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while not self._buffer and not self._done:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    break
                self._cond.wait(remaining)
            if not self._buffer:
                return self._frame
            target = time.monotonic() - max(0.0, seconds)
            _, jpeg = nearest_by_time(self._buffer, target)
        return decode_jpeg(jpeg)

    def close(self):
        """Stop the decode thread and release the decoder."""
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._thread.join(timeout=2.0)


class CameraWorker(threading.Thread):
    """One pseudo-camera: pace ticks and hand the shared frame to its sink."""

    def __init__(
        self,
        camera_id,
        on_frame,
        source,
        *,
        index,
        n,
        interval,
        frame_lag=0.0,
        max_samples=0,
        stop_event=None,
        on_tick=None,
    ):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self._on_frame = on_frame
        self._source = source
        self._index = index
        self._n = n
        self._interval = interval
        self._frame_lag = frame_lag
        self._max_samples = max_samples
        self._stop_event = stop_event if stop_event is not None else threading.Event()
        self._on_tick = on_tick
        self.samples = 0

    def run(self):
        if self._stop_event.wait(phase_offset(self._index, self._n, self._interval)):
            return
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            if self._max_samples and self.samples >= self._max_samples:
                break
            if self._frame_lag > 0:
                frame = self._source.frame_ago(self._frame_lag)
            else:
                frame = self._source.latest_frame()
            if frame is None:
                break
            self._on_frame(frame)
            self.samples += 1
            if self._on_tick is not None:
                self._on_tick(self.camera_id, frame)
            next_tick += self._interval
            remaining = next_tick - time.monotonic()
            if remaining > 0:
                if self._stop_event.wait(remaining):
                    break
            else:
                next_tick = time.monotonic()


def run_cameras(
    source, specs, *, interval, phase=0.0, max_samples=0, seconds=0, stop_event=None, display=None
):
    """Drive one :class:`CameraWorker` per ``(camera_id, sink)`` spec.

    ``phase`` is the per-camera clip-position lag in seconds (camera ``i`` reads
    the clip ``i * phase`` seconds behind the live edge); ``0`` shows every camera
    the same newest frame. Waits until every worker reaches ``max_samples``,
    ``seconds`` elapse, the ``stop_event`` is set, or the user interrupts, then
    stops cleanly and prints a per-camera ``sent`` summary. Closes ``source`` and
    returns 0.
    """
    if stop_event is None:
        stop_event = threading.Event()
    n = len(specs)
    workers = [
        CameraWorker(
            camera_id,
            sink,
            source,
            index=index,
            n=n,
            interval=interval,
            frame_lag=frame_offset(index, phase),
            max_samples=max_samples,
            stop_event=stop_event,
            on_tick=display,
        )
        for index, (camera_id, sink) in enumerate(specs)
    ]
    for worker in workers:
        worker.start()
    deadline = None if seconds <= 0 else time.monotonic() + seconds
    try:
        while True:
            if stop_event.is_set():
                break
            if max_samples and all(worker.samples >= max_samples for worker in workers):
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            if not any(worker.is_alive() for worker in workers):
                break
            time.sleep(0.005)
    except KeyboardInterrupt:
        print("\nInterrupted; shutting down.")
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=5.0)
        source.close()
    for worker in workers:
        print(f"camera {worker.camera_id}: sent {worker.samples}")
    return 0


def compose_grid(frames, labels):
    """Tile BGR ``frames`` into a labelled mosaic (display only).

    Frames of different sizes are resized to a common cell (the largest width
    and height). Returns a ``numpy`` array tiling ``len(frames)`` cells.
    """
    if not frames:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    count = len(frames)
    cols = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / cols))
    cell_h = max(frame.shape[0] for frame in frames)
    cell_w = max(frame.shape[1] for frame in frames)
    grid = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)
    for index, frame in enumerate(frames):
        row, col = divmod(index, cols)
        cell = cv2.resize(frame, (cell_w, cell_h))
        if index < len(labels) and labels[index]:
            cv2.putText(
                cell,
                str(labels[index]),
                (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
        grid[row * cell_h : (row + 1) * cell_h, col * cell_w : (col + 1) * cell_w] = cell
    return grid
