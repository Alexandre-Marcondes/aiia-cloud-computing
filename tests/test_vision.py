"""Unit tests for src.vision (offline: requests.post is stubbed)."""

import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import vision  # noqa: E402


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class VisionTests(unittest.TestCase):
    def test_builds_request_and_parses_values(self):
        people = [{"boundingBox": {"x": 1, "y": 2, "w": 3, "h": 4}, "confidence": 0.9}]
        response = _FakeResponse({"peopleResult": {"values": people}})

        with mock.patch.object(vision.requests, "post", return_value=response) as post:
            result = vision.analyze_people(b"jpegbytes", "https://example.com/", "secret")

        self.assertEqual(result, people)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://example.com" + vision.ANALYZE_PATH)
        self.assertEqual(
            kwargs["params"], {"api-version": vision.API_VERSION, "features": vision.PEOPLE_FEATURE}
        )
        self.assertEqual(kwargs["headers"]["Ocp-Apim-Subscription-Key"], "secret")
        self.assertEqual(kwargs["data"], b"jpegbytes")

    def test_returns_empty_when_no_people_result(self):
        with mock.patch.object(vision.requests, "post", return_value=_FakeResponse({})):
            self.assertEqual(vision.analyze_people(b"x", "https://example.com", "k"), [])

    def test_filters_boxes_below_min_confidence(self):
        people = [
            {"boundingBox": {"x": 1, "y": 2, "w": 3, "h": 4}, "confidence": 0.9},
            {"boundingBox": {"x": 5, "y": 6, "w": 7, "h": 8}, "confidence": 0.05},
        ]
        response = _FakeResponse({"peopleResult": {"values": people}})
        with mock.patch.object(vision.requests, "post", return_value=response):
            result = vision.analyze_people(b"x", "https://example.com", "k")
        self.assertEqual(result, [people[0]])

    def test_zero_threshold_keeps_every_box(self):
        people = [{"boundingBox": {"x": 1, "y": 2, "w": 3, "h": 4}, "confidence": 0.01}]
        response = _FakeResponse({"peopleResult": {"values": people}})
        with mock.patch.object(vision.requests, "post", return_value=response):
            result = vision.analyze_people(b"x", "https://example.com", "k", min_confidence=0.0)
        self.assertEqual(result, people)

    def test_propagates_http_errors(self):
        response = _FakeResponse({}, status=429)
        with mock.patch.object(vision.requests, "post", return_value=response):
            with self.assertRaises(requests.HTTPError):
                vision.analyze_people(b"x", "https://example.com", "k")


if __name__ == "__main__":
    unittest.main()
