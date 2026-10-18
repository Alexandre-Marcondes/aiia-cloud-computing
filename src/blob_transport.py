"""Azure Blob Storage transport shared by the Part 3 sender and function.

Mirrors :mod:`transport` (the Part 2 HTTP protocol): the local sender uploads
each captured frame into the private ``raw`` container, and the triggered
function writes its results into the public ``$web`` container via the same
module.

``azure-storage-blob`` is an optional dependency and is imported lazily, so
importing this module never requires it — the function bundle can import the
receiver helpers without pulling the sender-side JPEG codec (cv2).
"""

import sys
import time
import uuid

import csv_log

DEFAULT_CONTAINER = "raw"
FRAME_BLOB = "processed_frame.jpg"
CSV_BLOB = "database.csv"
PROCESSING_BLOB = "processing.csv"

# Camera segment reserved for the legacy single-camera layout.
RESERVED_CAMERA = "cam"
FRAMES_PREFIX = "frames"


def blob_name(camera_id=None, when=None):
    """Build a unique ``<camera>/<utc-stamp>-<random>.jpg`` blob name."""
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(when if when is not None else time.time()))
    return f"{camera_id or 'cam'}/{stamp}-{uuid.uuid4().hex[:8]}.jpg"


def blob_name_in_container(name, container):
    """Return ``name`` without a leading ``container/`` segment.

    The Event Grid-based blob trigger can report ``InputStream.name`` with the
    container prefix included (e.g. ``raw/cam/x.jpg``), so normalise before using
    the name against a container client.
    """
    prefix = f"{container}/"
    return name[len(prefix) :] if name.startswith(prefix) else name


def camera_from_name(name, container):
    """Return the camera id encoded as the first path segment of blob ``name``.

    Returns ``None`` for the legacy single-camera layout: when the segment is
    absent or equals the reserved id :data:`RESERVED_CAMERA`, the name is not a
    multi-camera upload. The container prefix is stripped first, so ``name`` may
    or may not carry it.
    """
    path = blob_name_in_container(name, container)
    segment = path.split("/", 1)[0]
    if not segment or segment == RESERVED_CAMERA:
        return None
    return segment


def camera_frame_name(camera):
    """Return the ``$web`` blob name for ``camera``'s annotated frame."""
    return f"{FRAMES_PREFIX}/{camera}.jpg"


def make_blob_sink(service_client, container=DEFAULT_CONTAINER, camera_id=None):
    """Build an ``on_frame`` callback that uploads each frame as a JPEG blob.

    Returns the original frame and never raises on an upload error, so the
    sampling loop keeps running.
    """
    from transport import encode_jpeg  # lazy: keeps cv2 out of the function bundle

    client = service_client.get_container_client(container)

    def sink(frame):
        try:
            client.upload_blob(name=blob_name(camera_id), data=encode_jpeg(frame), overwrite=True)
        except Exception as exc:  # keep the sampling loop alive
            print(f"Warning: failed to upload frame to {container}: {exc}", file=sys.stderr)
        return frame

    return sink


def make_blob_sink_from_connection_string(
    connection_string, container=DEFAULT_CONTAINER, camera_id=None
):
    """Build a blob sink from an Azure Storage connection string."""
    from azure.storage.blob import BlobServiceClient  # lazy: optional dependency

    service = BlobServiceClient.from_connection_string(connection_string)
    return make_blob_sink(service, container=container, camera_id=camera_id)


def upload_jpeg(container_client, name, data):
    """Upload (overwrite) ``data`` as the blob ``name``."""
    container_client.get_blob_client(name).upload_blob(data, overwrite=True)


def append_csv(container_client, name, row, retries=5):
    """Append the CSV ``row`` text to blob ``name``, retrying on write races.

    Concurrent function instances can finish together, so the read-modify-write
    is guarded by the blob ETag; a lost race retries against the fresh content.
    ``row`` should come from :func:`csv_log.format_row`.
    """
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError

    blob = container_client.get_blob_client(name)
    for _ in range(retries):
        try:
            try:
                download = blob.download_blob()
                existing = download.readall()
                etag = download.properties.etag
            except ResourceNotFoundError:
                existing, etag = b"", None
            payload = csv_log.append_row(existing, row)
            if etag is None:
                blob.upload_blob(payload, overwrite=False)
            else:
                blob.upload_blob(
                    payload,
                    overwrite=True,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
            return
        except ResourceModifiedError:
            continue
    raise RuntimeError(f"could not append to {name} after {retries} attempts")
