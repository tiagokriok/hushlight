"""Behavioral tests for camera device-access status (Task 2)."""

import unittest

from backend import camera
from backend import status as st


class CameraStatusTests(unittest.TestCase):
    def test_unavailable_lookup_is_unknown(self):
        result = camera.camera_status(frozenset(), None, 10.0, False)
        self.assertEqual(result["state"], st.STATE_UNKNOWN)
        self.assertTrue(result["limitations"])

    def test_no_holders_is_unobserved(self):
        result = camera.camera_status(frozenset(), None, 10.0, True)
        self.assertEqual(result["state"], st.STATE_UNOBSERVED)

    def test_holder_stable_becomes_active(self):
        result = camera.camera_status(frozenset({"brave"}), 100.0, 100.75, True)
        self.assertEqual(result["state"], st.STATE_ACTIVE)
        self.assertEqual(result["evidence"], "Camera device accessed")

    def test_short_probe_is_not_active(self):
        result = camera.camera_status(frozenset({"brave"}), 100.0, 100.40, True)
        self.assertEqual(result["state"], st.STATE_UNOBSERVED)

    def test_holder_at_exact_threshold_is_active(self):
        result = camera.camera_status(frozenset({"brave"}), 100.0, 100.75, True)
        self.assertEqual(result["state"], st.STATE_ACTIVE)

    def test_multiple_holders_stable_is_active(self):
        holders = frozenset({"brave", "obs"})
        result = camera.camera_status(holders, 5.0, 6.0, True)
        self.assertEqual(result["state"], st.STATE_ACTIVE)

    def test_active_evidence_does_not_claim_recording(self):
        result = camera.camera_status(frozenset({"brave"}), 0.0, 5.0, True)
        lowered = result["evidence"].lower()
        self.assertNotIn("record", lowered)
        self.assertNotIn("stream", lowered)

    def test_active_reports_limitations(self):
        result = camera.camera_status(frozenset({"brave"}), 0.0, 5.0, True)
        self.assertTrue(result["limitations"])
        for item in result["limitations"]:
            self.assertIsInstance(item, str)

    def test_custom_debounce_is_respected(self):
        before = camera.camera_status(frozenset({"brave"}), 0.0, 1.0, True, debounce=2.0)
        at = camera.camera_status(frozenset({"brave"}), 0.0, 2.0, True, debounce=2.0)
        self.assertEqual(before["state"], st.STATE_UNOBSERVED)
        self.assertEqual(at["state"], st.STATE_ACTIVE)


if __name__ == "__main__":
    unittest.main()
