"""Frame sources: local video files and the live SkylineWebcams HLS stream."""

import re
import threading
import time
import urllib.request
from pathlib import Path

import cv2

# SkylineWebcams page hosting the fixed Salò, Lake Garda camera (used by local_stream).
DEFAULT_PAGE_URL = (
    "https://www.skylinewebcams.com/en/webcam/italia/lombardia/brescia/salo-lago-di-garda.html"
)

# `--source` values that mean "use the default live camera".
LIVE_ALIASES = frozenset({"live", "salò", "salo", "skyline"})

_OPEN_ERROR = (
    "Cannot open video '{path}'. If the file uses a codec this OpenCV build cannot "
    "decode (e.g. AV1), re-encode it to H.264: "
    "ffmpeg -i <input> -c:v libx264 -pix_fmt yuv420p <output>.mp4"
)
_METADATA_ERROR = (
    "Cannot determine fps/frame count for '{path}' (timing metadata unavailable). "
    "Re-encode the clip to H.264 and try again."
)
_DECODE_ERROR = (
    "Failed to decode a frame from '{path}'. If the file uses a codec this OpenCV "
    "build cannot decode (e.g. AV1), re-encode it to H.264: "
    "ffmpeg -i <input> -c:v libx264 -pix_fmt yuv420p <output>.mp4"
)


class VideoError(Exception):
    """Raised when the input video cannot be opened, decoded, or sampled."""


class _VideoFile:
    """Shared open/validate/release for local video files."""

    def __init__(self, video_path):
        self.video_path = str(Path(video_path))
        self._cap = cv2.VideoCapture(self.video_path)
        if not self._cap.isOpened():
            raise VideoError(_OPEN_ERROR.format(path=self.video_path))
        self.fps = self._cap.get(cv2.CAP_PROP_FPS)
        self.frame_count = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if self.fps <= 0 or self.frame_count <= 0:
            raise VideoError(_METADATA_ERROR.format(path=self.video_path))
        self.duration = self.frame_count / self.fps

    def close(self):
        """Release the underlying video capture."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class VideoSampler(_VideoFile):
    """Samples one frame every ``sample_interval`` seconds from a video file.

    The clip is treated as a loop: sampling wraps back to the start when the
    end of the file is reached. Frames are fetched by seeking to the target
    timestamp (``CAP_PROP_POS_MSEC``), not by reading and discarding every
    frame between samples.
    """

    def __init__(self, video_path):
        super().__init__(video_path)
        self._elapsed = 0.0

    def next_frame(self, sample_interval):
        """Seek to the next sample timestamp and return ``(frame, elapsed)``.

        ``elapsed`` is the loop-wrapped video time (seconds) of the frame.
        """
        if sample_interval <= 0:
            raise ValueError(f"sample interval must be positive, got {sample_interval}")
        self._elapsed += sample_interval
        target_ms = int((self._elapsed % self.duration) * 1000.0)
        if not self._cap.set(cv2.CAP_PROP_POS_MSEC, target_ms):
            raise VideoError(f"Failed to seek in video '{self.video_path}'.")
        ret, frame = self._cap.read()
        if not ret:
            # Past the final frame: loop back to the start of the clip.
            self._cap.set(cv2.CAP_PROP_POS_MSEC, 0)
            ret, frame = self._cap.read()
            if not ret:
                raise VideoError(_DECODE_ERROR.format(path=self.video_path))
        return frame, self._elapsed


class VideoPlayer(_VideoFile):
    """Sequential playback of a local video file, looping at the end.

    Unlike :class:`VideoSampler` (which seeks), this reads every frame in order,
    so callers can pace playback to the clip's ``fps`` and emulate a live feed.
    """

    def read(self):
        """Return the next frame, looping back to the start at the end."""
        ret, frame = self._cap.read()
        if not ret:
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._cap.read()
            if not ret:
                raise VideoError(_DECODE_ERROR.format(path=self.video_path))
        return frame


def resolve_source(source):
    """Classify a ``--source`` value as a live stream or a local video file.

    Returns ``("live", page_url)`` for a SkylineWebcams page URL or one of the
    :data:`LIVE_ALIASES` (e.g. ``"live"`` → the Salò camera), and
    ``("video", path)`` for anything else (a local file path).
    """
    text = str(source).strip()
    if text.lower() in LIVE_ALIASES:
        return "live", DEFAULT_PAGE_URL
    if text.startswith(("http://", "https://")):
        return "live", text
    return "video", text


def get_stream_url(page_url):
    """Scrape the tokenized HLS playlist URL from a SkylineWebcams page."""
    req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    match = re.search(r"source:'(live[a-z0-9]*\.m3u8\?a=[a-z0-9]+)'", html)
    if not match:
        raise RuntimeError("Could not find HLS source in page")
    # The page ships the `livee.m3u8` placeholder (a "copyright_violation"
    # banner stream). Clappr rewrites "livee." -> "live." for the real stream.
    path = match.group(1).replace("livee.m3u8", "live.m3u8")
    return "https://hd-auth.skylinewebcams.com/" + path


class FrameGrabber:
    """Read an HLS stream on a background thread.

    OpenCV's ``VideoCapture.read()`` blocks for the whole duration of an HLS
    segment (~4s here) because FFmpeg buffers a full segment before returning
    frames, and it can block indefinitely if the stream stalls. This class keeps
    the blocking read off the main thread and exposes only the latest frame.
    """

    def __init__(self, page_url):
        self.page_url = page_url
        self._cond = threading.Condition()
        self._frame = None
        self._seq = 0
        self._stop = threading.Event()
        self._cap = None
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _open(self):
        if self._cap is not None:
            self._cap.release()
        url = get_stream_url(self.page_url)
        print(f"URL is: {url}")
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def _run(self):
        self._cap = self._open()
        if self._cap is None:
            print("Error: Could not open the stream.")
        else:
            print("Stream is opened.")

        while not self._stop.is_set():
            if self._cap is None:
                time.sleep(1.0)
                self._cap = self._open()
                continue

            ret, frame = self._cap.read()
            if not ret:
                print("Stream ended; reconnecting...")
                self._cap = self._open()
                continue

            with self._cond:
                self._frame = frame
                self._seq += 1
                self._cond.notify_all()

    def read(self, last_seq=0, timeout=None):
        """Return ``(seq, frame)`` once a frame newer than ``last_seq`` exists.

        Returns the currently held frame (same ``seq``) if ``timeout`` elapses
        first, so callers can detect a stalled stream without blocking forever.
        """
        with self._cond:
            deadline = None if timeout is None else time.time() + timeout
            while self._seq == last_seq and not self._stop.is_set():
                if deadline is None:
                    self._cond.wait()
                    continue
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._cond.wait(remaining)
            return self._seq, self._frame

    def stop(self):
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
