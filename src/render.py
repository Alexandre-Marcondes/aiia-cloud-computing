"""Draw detected-person bounding boxes onto a frame.

A small, dependency-light (Pillow) rendering unit used by the serverless
function: YOLO's own ``result.plot()`` annotates the local/VM paths, while the
Vision path gets its boxes drawn here.
"""

import io

from PIL import Image, ImageDraw

DEFAULT_COLOR = (0, 200, 0)
DEFAULT_WIDTH = 3


def draw_boxes(image_bytes, people, color=DEFAULT_COLOR, width=DEFAULT_WIDTH, quality=90):
    """Return JPEG bytes of ``image_bytes`` with a box around each detected person.

    ``people`` is the Image Analysis ``peopleResult.values`` list; each item's
    ``boundingBox`` gives ``x``, ``y``, ``w``, ``h`` in pixels.
    """
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)
    for person in people:
        box = person["boundingBox"]
        x, y, w, h = box["x"], box["y"], box["w"], box["h"]
        draw.rectangle([x, y, x + w, y + h], outline=color, width=width)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=quality)
    return out.getvalue()
