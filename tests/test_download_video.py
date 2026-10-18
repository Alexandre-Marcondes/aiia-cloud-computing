import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from download_video import DEFAULT_DIR, ensure_mp4, resolve_output, slugify  # noqa: E402


class SlugifyTests(unittest.TestCase):
    def test_lowercases_and_slugs_runs_of_non_alphanumerics(self):
        self.assertEqual(slugify("People Walking (4K)"), "people_walking_4k")
        self.assertEqual(slugify("My Video!!-- title"), "my_video_title")

    def test_strips_leading_and_trailing_separators(self):
        self.assertEqual(slugify("  --Title--  "), "title")

    def test_empty_title_falls_back_to_video(self):
        self.assertEqual(slugify("!!!"), "video")


class OutputResolutionTests(unittest.TestCase):
    def test_explicit_output_wins_and_forces_mp4(self):
        self.assertEqual(resolve_output(output="data/clip.mov"), Path("data/clip.mp4"))

    def test_name_goes_to_default_data_dir(self):
        self.assertEqual(
            resolve_output(name="People Walking (4K)"),
            DEFAULT_DIR / "people_walking_4k.mp4",
        )

    def test_nothing_given_returns_none(self):
        self.assertIsNone(resolve_output())


class EnsureMp4Tests(unittest.TestCase):
    def test_replaces_suffix(self):
        self.assertEqual(ensure_mp4("clip.mkv"), Path("clip.mp4"))

    def test_appends_when_no_suffix(self):
        self.assertEqual(ensure_mp4("clip"), Path("clip.mp4"))


if __name__ == "__main__":
    unittest.main()
