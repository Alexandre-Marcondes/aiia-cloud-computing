#!/usr/bin/env python3
"""Download any yt-dlp-supported video as a reliable H.264/MP4 clip.

The SLS pipeline needs clips that OpenCV's FFmpeg build can decode, so this
script prefers an H.264 (``avc1``) video stream with ``m4a`` audio merged into an
MP4 container. It uses the ``yt_dlp`` Python API when available and otherwise
falls back to the ``yt-dlp`` executable.
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = REPO_ROOT / "data"

# H.264 video + m4a audio merged into mp4; fall back to any mp4, then anything.
FORMAT_SELECTOR = "bv*[vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"


def slugify(name):
    """Turn a title into a filesystem-safe slug (lowercase, `_`-separated)."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "video"


def ensure_mp4(path):
    """Force the ``.mp4`` extension on an output path."""
    return Path(path).with_suffix(".mp4")


def resolve_output(output=None, name=None):
    """Pick the destination file: ``-o`` wins, then ``--name``.

    Returns ``None`` when neither is given (the title-derived default is
    resolved at download time).
    """
    if output:
        return ensure_mp4(output)
    if name:
        return DEFAULT_DIR / f"{slugify(name)}.mp4"
    return None


def pick_backend():
    """Return ``"api"``, ``"cli"`` or ``None`` for the available downloader."""
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        pass
    else:
        return "api"
    if shutil.which("yt-dlp"):
        return "cli"
    return None


def video_title(backend, url):
    """Fetch the video title using the chosen backend."""
    if backend == "api":
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("title") or "video"
    result = subprocess.run(
        ["yt-dlp", "--no-warnings", "--print", "title", url],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() or "video"


def download(backend, url, out_path):
    """Download ``url`` to ``out_path`` (H.264 video, m4a audio, mp4 container)."""
    if backend == "api":
        import yt_dlp

        opts = {
            "format": FORMAT_SELECTOR,
            "merge_output_format": "mp4",
            "remux_video": "mp4",
            "outtmpl": str(out_path),
            "overwrites": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        return
    subprocess.run(
        [
            "yt-dlp",
            "--format",
            FORMAT_SELECTOR,
            "--merge-output-format",
            "mp4",
            "--remux-video",
            "mp4",
            "--force-overwrites",
            "--no-warnings",
            "-o",
            str(out_path),
            url,
        ],
        check=True,
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Download a YouTube (or any yt-dlp-supported) video as an H.264 .mp4 clip."
    )
    parser.add_argument("url", help="video URL to download")
    parser.add_argument("-o", "--output", help="explicit output file path (wins over --name)")
    parser.add_argument(
        "--name",
        help="base filename without extension; defaults to the slugified video title",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    backend = pick_backend()
    if backend is None:
        print(
            "Error: no downloader available; install the `yt_dlp` Python module "
            "(pip install yt-dlp) or put the `yt-dlp` executable on PATH.",
            file=sys.stderr,
        )
        return 1
    out_path = resolve_output(args.output, args.name)
    if out_path is None:
        out_path = DEFAULT_DIR / f"{slugify(video_title(backend, args.url))}.mp4"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    download(backend, args.url, out_path)
    print(out_path.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
