"""HTTP frame-upload protocol shared by the local sender and the cloud receiver.

The local machine POSTs each captured frame as a raw JPEG body to the VM
receiver, which decodes it and runs YOLO. Keeping both ends on this module means
the route and encoding can't drift.

Only the standard library is used on the client side (``urllib``), so sending
frames needs no extra dependency.
"""

import json
import sys
import urllib.request

import cv2
import numpy as np

# Route the receiver serves; a bare ``host:port`` URL is normalized to this.
FRAME_PATH = "/frame"
JPEG_CONTENT_TYPE = "image/jpeg"
# Generous by default: the first request may also pay the receiver's one-time
# model load, and CPU inference on a small VM is slow.
DEFAULT_TIMEOUT = 60.0


def normalize_endpoint(url):
    """Return ``url`` with :data:`FRAME_PATH` appended if it has no path."""
    base = url.rstrip("/")
    if base.endswith(FRAME_PATH):
        return base
    return base + FRAME_PATH


def encode_jpeg(frame, quality=90):
    """Encode a BGR frame to JPEG bytes."""
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
    if not ok:
        raise ValueError("failed to encode frame as JPEG")
    return buffer.tobytes()


def decode_jpeg(data):
    """Decode JPEG bytes to a BGR frame; raise ``ValueError`` if not an image."""
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("failed to decode JPEG frame")
    return frame


def post_frame(url, frame, camera_id=None, timeout=DEFAULT_TIMEOUT):
    """POST ``frame`` as a JPEG to ``url``; return the parsed JSON response."""
    data = encode_jpeg(frame)
    headers = {"Content-Type": JPEG_CONTENT_TYPE}
    if camera_id is not None:
        headers["X-Camera-Id"] = str(camera_id)
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8") or "{}"
    return json.loads(body)


def make_cloud_sink(url, camera_id=None, timeout=DEFAULT_TIMEOUT):
    """Build an ``on_frame`` callback that uploads each frame to the receiver.

    Returns the original frame (there is no local annotation), and never raises
    on a network error: the loop keeps running and the failure is reported.
    """
    endpoint = normalize_endpoint(url)

    def sink(frame):
        try:
            post_frame(endpoint, frame, camera_id=camera_id, timeout=timeout)
        except (OSError, ValueError) as exc:
            print(f"Warning: failed to send frame to {endpoint}: {exc}", file=sys.stderr)
        return frame

    return sink
