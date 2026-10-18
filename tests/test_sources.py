"""Smoke tests for src.sources.resolve_source (offline: no network, no video)."""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from sources import DEFAULT_PAGE_URL, LIVE_ALIASES, resolve_source  # noqa: E402


class ResolveSourceTests(unittest.TestCase):
    def test_each_live_alias_resolves_to_default_page(self):
        for alias in LIVE_ALIASES:
            self.assertEqual(resolve_source(alias), ("live", DEFAULT_PAGE_URL))

    def test_expected_aliases_present(self):
        for alias in ("live", "salò", "salo", "skyline"):
            self.assertIn(alias, LIVE_ALIASES)

    def test_alias_matching_is_case_insensitive(self):
        self.assertEqual(resolve_source("LIVE"), ("live", DEFAULT_PAGE_URL))
        self.assertEqual(resolve_source("Skyline"), ("live", DEFAULT_PAGE_URL))

    def test_http_urls_resolve_to_live(self):
        self.assertEqual(
            resolve_source("http://example.com/stream"), ("live", "http://example.com/stream")
        )
        self.assertEqual(
            resolve_source("https://example.com/stream"), ("live", "https://example.com/stream")
        )

    def test_local_video_path_resolves_to_video(self):
        self.assertEqual(
            resolve_source("data/people_walking.mp4"), ("video", "data/people_walking.mp4")
        )

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(resolve_source("  live  "), ("live", DEFAULT_PAGE_URL))
        self.assertEqual(
            resolve_source("  data/people_walking.mp4  "), ("video", "data/people_walking.mp4")
        )


if __name__ == "__main__":
    unittest.main()
