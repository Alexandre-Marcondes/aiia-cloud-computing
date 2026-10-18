"""Per-sample processing shared by the local (and later cloud) pipelines."""

import cv2

from csv_log import log_sample, now_timestamp


def process_sample(frame, detector, stats, csv_path, frame_out, plotter, camera=None):
    """Detect persons in ``frame`` and record the sample.

    Updates ``stats``, appends a row to ``csv_path``, saves the annotated frame
    to ``frame_out``, records the sample in ``plotter``, and prints the running
    statistics. ``camera=None`` keeps the legacy single-camera CSV schema;
    otherwise the row is tagged with the camera. Returns ``(count,
    annotated_frame)`` for this sample.
    """
    count, annotated = detector.count_persons(frame)
    stats.add(count)
    timestamp = now_timestamp()
    log_sample(csv_path, timestamp, count, camera=camera)
    cv2.imwrite(frame_out, annotated)
    plotter.add(timestamp, count)
    summary = stats.summary()
    print(
        f"[{timestamp}] sample {summary['samples']}: {count} person(s) "
        f"(total {summary['total']}, mean {summary['mean']:.2f}, "
        f"min {summary['min']}, max {summary['max']})"
    )
    return count, annotated
