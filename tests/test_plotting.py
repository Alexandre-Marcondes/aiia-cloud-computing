"""Unit tests for src.plotting (headless: Agg backend, writes to a temp dir)."""

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np  # noqa: E402

from plotting import PlotDisplay  # noqa: E402


class PlotDisplayTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.plot_out = Path(self.tmpdir.name) / "plot.png"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_add_plots_counts_over_time(self):
        p = PlotDisplay(self.plot_out, no_display=True)
        p.add("2025-01-01 10:00:00", 2)
        p.add("2025-01-01 10:00:05", 3)
        p.add("2025-01-01 10:00:10", 1)

        # The figure is saved to disk as a non-empty PNG.
        self.assertTrue(self.plot_out.exists())
        self.assertGreater(self.plot_out.stat().st_size, 0)

        # x-axis carries real timestamps (datetimes), not a 0..N sample index.
        x = list(np.asarray(p.axis.lines[0].get_xdata()))
        y = list(np.asarray(p.axis.lines[0].get_ydata()))
        self.assertEqual(len(x), 3)
        for value in x:
            self.assertIsInstance(value, datetime)
        self.assertEqual(
            x,
            [
                datetime(2025, 1, 1, 10, 0, 0),
                datetime(2025, 1, 1, 10, 0, 5),
                datetime(2025, 1, 1, 10, 0, 10),
            ],
        )
        # ...and they are in ascending order.
        self.assertEqual(x, sorted(x))
        # y-axis is exactly the appended counts.
        self.assertEqual(y, [2, 3, 1])

        p.close()


if __name__ == "__main__":
    unittest.main()
