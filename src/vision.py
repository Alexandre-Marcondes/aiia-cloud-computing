"""Azure AI Vision detector (Image Analysis 4.0 ``people`` feature).

The serverless counterpart of :mod:`detection`: instead of running YOLO locally,
it posts a JPEG to the Azure AI Vision REST API and reads the per-person
bounding boxes. The two detectors are kept separate because their inputs
(JPEG bytes vs. a BGR frame), outputs (boxes vs. an annotated image), and
dependencies differ; only the sample *record* contract is shared.

Task 3.4 names the Computer-Vision image-*tagging* service, but Task 3.5 needs a
``bounding_box`` per person; tagging returns labels, not boxes, so the ``people``
feature is the only fitting choice. The brief is internally inconsistent and the
deviation is deliberate.
"""

import requests

API_VERSION = "2024-02-01"
PEOPLE_FEATURE = "people"
ANALYZE_PATH = "/computervision/imageanalysis:analyze"
DEFAULT_TIMEOUT = 30.0
# The ``people`` feature returns many very-low-confidence boxes (a crowded frame
# came back with 100 boxes down to confidence 0.001), so count only the ones
# above a threshold — mirroring the YOLO path's ``conf`` filter (0.30).
DEFAULT_MIN_CONFIDENCE = 0.30


def analyze_people(
    image_bytes, endpoint, key, timeout=DEFAULT_TIMEOUT, min_confidence=DEFAULT_MIN_CONFIDENCE
):
    """Return the ``peopleResult.values`` at or above ``min_confidence``.

    Each item is ``{"boundingBox": {"x", "y", "w", "h"}, "confidence": float}``.
    Low-confidence boxes are dropped so a busy scene does not report a flood of
    false positives; pass ``min_confidence=0.0`` for the raw list. Raises
    ``requests.HTTPError`` on a non-2xx response (bad key, quota, ...).
    """
    url = endpoint.rstrip("/") + ANALYZE_PATH
    response = requests.post(
        url,
        params={"api-version": API_VERSION, "features": PEOPLE_FEATURE},
        headers={
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/octet-stream",
        },
        data=image_bytes,
        timeout=timeout,
    )
    response.raise_for_status()
    values = response.json().get("peopleResult", {}).get("values", [])
    return [p for p in values if float(p.get("confidence", 0.0)) >= min_confidence]
