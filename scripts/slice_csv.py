#!/usr/bin/env python3
"""Print a small capture of a CSV: the header plus a few data rows.

Used to produce the compact, committed evidence snippets for the Part 4
consolidation (the full per-N ``data/sweeps/*-processing.csv`` files are large).
Dependency-free and import-safe; reads one file and writes to stdout.

    python scripts/slice_csv.py data/sweeps/serverless-8-processing.csv
    python scripts/slice_csv.py data/sweeps/vm-8-processing.csv --head 20
"""

import argparse
import sys
from pathlib import Path

DEFAULT_ROWS = 40


def slice_text(text, mode="tail", count=DEFAULT_ROWS):
    """Return the header plus up to ``count`` data rows from ``text``.

    Blank/whitespace-only lines are skipped. ``mode`` is ``"tail"`` (last rows)
    or ``"head"`` (first rows). The header is always included when present.
    """
    lines = [line for line in text.splitlines(keepends=True) if line.strip()]
    if not lines:
        return ""
    header, body = lines[0], lines[1:]
    if count <= 0:
        selected = []
    elif mode == "head":
        selected = body[:count]
    else:
        selected = body[-count:]
    return "".join([header, *selected])


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Print a CSV's header plus the first or last N data rows."
    )
    parser.add_argument("path", help="CSV file to slice")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--tail",
        type=int,
        metavar="N",
        help=f"print the last N data rows (default: {DEFAULT_ROWS})",
    )
    group.add_argument("--head", type=int, metavar="N", help="print the first N data rows")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    path = Path(args.path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error: cannot read {path}: {exc}", file=sys.stderr)
        return 1
    if args.head is not None:
        mode, count = "head", args.head
    else:
        mode, count = "tail", DEFAULT_ROWS if args.tail is None else args.tail
    sys.stdout.write(slice_text(text, mode=mode, count=count))
    return 0


if __name__ == "__main__":
    sys.exit(main())
