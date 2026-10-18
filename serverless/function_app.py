"""Azure Function that processes uploaded frames for Part 3 (serverless).

A blob trigger fires for every JPEG uploaded to the private ``raw`` container.
The function calls Azure AI Vision (Image Analysis 4.0, ``people`` feature) to
count people and get their bounding boxes, draws the boxes, then publishes the
annotated frame and appends a row to ``database.csv`` in the ``$web`` static
site container. The input blob is deleted once processed.

The camera is taken from the blob name's first path segment: the reserved id
``cam`` (or no segment) keeps the legacy single-camera output
(``processed_frame.jpg`` + ``Timestamp,Person_Count``); any other segment is a
multi-camera upload (``frames/<camera>.jpg`` + ``Timestamp,Camera,Person_Count``).

The trigger is scoped to ``raw/{name}`` and every output goes to a *different*
container (``$web``), so the function can never trigger itself.

Flex Consumption only supports the **event-based** blob trigger, so the binding
uses ``source="EventGrid"``. That requires an Event Grid subscription on the
storage account delivering ``BlobCreated`` events for the ``raw`` container to
this function's blob-extension webhook (see ``docs/architecture.md``).

Settings (Function App configuration):

* ``DATA_STORAGE`` — connection string of the account holding ``raw`` and ``$web``;
* ``VISION_ENDPOINT`` / ``VISION_KEY`` — the Azure AI Vision resource;
* ``VISION_MIN_CONFIDENCE`` — optional; minimum box confidence to count (default 0.30).

The reusable units (``blob_transport``, ``csv_log``, ``render``, ``vision``) are
assembled next to this file when the deployment bundle is built.
"""

import logging
import os
import time

import azure.functions as func
import requests
from azure.storage.blob import BlobServiceClient

import blob_transport
import csv_log
import render
import vision

app = func.FunctionApp()

RAW_CONTAINER = os.environ.get("RAW_CONTAINER", blob_transport.DEFAULT_CONTAINER)
WEB_CONTAINER = os.environ.get("WEB_CONTAINER", "$web")
# Minimum Vision confidence to count a box; the ``people`` feature emits many
# low-confidence false positives. Overridable via the VISION_MIN_CONFIDENCE app
# setting (e.g. 0.5 for a stricter count) without a code change.
MIN_CONFIDENCE = float(os.environ.get("VISION_MIN_CONFIDENCE", vision.DEFAULT_MIN_CONFIDENCE))

# Transient Vision failures worth retrying: throttling and server-side errors.
RETRY_ATTEMPTS = 3
RETRY_BACKOFF = 0.5
RETRY_STATUSES = {429, 500, 502, 503, 504}


def analyze_people_with_retry(image_bytes, endpoint, key, min_confidence=MIN_CONFIDENCE):
    """Count people, retrying transient throttling / server errors.

    Retries only HTTP 429 / 5xx with a short exponential backoff so a throttling
    burst at high camera counts does not become a failed invocation; every other
    error (bad key, client error, network) propagates immediately.
    """
    for attempt in range(RETRY_ATTEMPTS):
        try:
            return vision.analyze_people(image_bytes, endpoint, key, min_confidence=min_confidence)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status not in RETRY_STATUSES or attempt == RETRY_ATTEMPTS - 1:
                raise
            delay = RETRY_BACKOFF * (2**attempt)
            logging.warning(
                "Vision returned %s; retry %d/%d in %.1fs",
                status,
                attempt + 1,
                RETRY_ATTEMPTS - 1,
                delay,
            )
            time.sleep(delay)


@app.blob_trigger(
    arg_name="blob",
    source="EventGrid",
    path=f"{RAW_CONTAINER}/{{name}}",
    connection="DATA_STORAGE",
)
def process_frame(blob: func.InputStream) -> None:
    """Count people in an uploaded frame and publish the annotated result."""
    started = time.perf_counter()
    service = BlobServiceClient.from_connection_string(os.environ["DATA_STORAGE"])
    image_bytes = blob.read()
    camera = blob_transport.camera_from_name(blob.name, RAW_CONTAINER)
    people = analyze_people_with_retry(
        image_bytes, os.environ["VISION_ENDPOINT"], os.environ["VISION_KEY"], MIN_CONFIDENCE
    )
    annotated = render.draw_boxes(image_bytes, people)

    web = service.get_container_client(WEB_CONTAINER)
    frame_name = blob_transport.camera_frame_name(camera) if camera else blob_transport.FRAME_BLOB
    blob_transport.upload_jpeg(web, frame_name, annotated)
    blob_transport.append_csv(
        web,
        blob_transport.CSV_BLOB,
        csv_log.format_row(csv_log.now_timestamp(), len(people), camera=camera),
    )
    # Per-frame telemetry for the served page's processing-time chart. There is no
    # queue server-side, so QueueMs = 0 and ServiceMs = the whole invocation.
    service_ms = (time.perf_counter() - started) * 1000.0
    blob_transport.append_csv(
        web,
        blob_transport.PROCESSING_BLOB,
        csv_log.format_processing_row(
            csv_log.now_timestamp(), camera or "cam", service_ms, 0.0, service_ms
        ),
    )
    raw_name = blob_transport.blob_name_in_container(blob.name, RAW_CONTAINER)
    service.get_blob_client(RAW_CONTAINER, raw_name).delete_blob()
    logging.info(
        "processed %s: %d person(s) at conf >= %.2f", blob.name, len(people), MIN_CONFIDENCE
    )
