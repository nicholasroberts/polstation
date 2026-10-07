"""Test hardware-independent camera-linearity calculations."""

import unittest

try:
    import numpy
except ImportError:
    numpy = None

from polstation.calibration.linearity import (
    _circular_roi_mask,
    _frame_statistics,
    _get_complete_frame,
    linear_fit,
    qualified_for_fit,
)


class LinearityTests(unittest.TestCase):
    def test_incomplete_frames_are_retried_and_recorded(self):
        class Frame:
            def __init__(self, status):
                self.status = status

            def get_status(self):
                return self.status

        class Camera:
            def __init__(self):
                self.frames = iter((Frame("incomplete"), Frame("complete")))

            def get_id(self):
                return "camera-1"

            def get_frame(self, timeout_ms):
                self.timeout_ms = timeout_ms
                return next(self.frames)

        rejected = []
        frame, attempt = _get_complete_frame(
            Camera(), 5000, "complete", rejected,
            exposure_us=600000, phase="recorded", repeat=0,
        )
        self.assertEqual(frame.get_status(), "complete")
        self.assertEqual(attempt, 2)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["camera_id"], "camera-1")
        self.assertEqual(rejected[0]["exposure_requested_us"], 600000)
        self.assertEqual(rejected[0]["phase"], "recorded")
        self.assertEqual(rejected[0]["repeat"], 0)

    def test_incomplete_frame_retry_is_bounded(self):
        class Frame:
            def get_status(self):
                return "incomplete"

        class Camera:
            def get_id(self):
                return "camera-1"

            def get_frame(self, timeout_ms):
                return Frame()

        rejected = []
        with self.assertRaisesRegex(RuntimeError, "after 3 attempts"):
            _get_complete_frame(
                Camera(), 5000, "complete", rejected,
                exposure_us=600000, phase="settling",
            )
        self.assertEqual(len(rejected), 3)

    def test_timeout_is_retried_and_recorded(self):
        class RetryableTimeout(Exception):
            pass

        class Frame:
            def get_status(self):
                return "complete"

        class Camera:
            def __init__(self):
                self.calls = 0

            def get_id(self):
                return "camera-1"

            def get_frame(self, timeout_ms):
                self.calls += 1
                if self.calls == 1:
                    raise RetryableTimeout("transient timeout")
                return Frame()

        rejected = []
        frame, attempt = _get_complete_frame(
            Camera(), 5000, "complete", rejected,
            exposure_us=900000, phase="recorded", repeat=2,
            retryable_exceptions=(RetryableTimeout,),
        )
        self.assertEqual(frame.get_status(), "complete")
        self.assertEqual(attempt, 2)
        self.assertEqual(len(rejected), 1)
        self.assertIn("RetryableTimeout", rejected[0]["status"])
        self.assertIn("transient timeout", rejected[0]["status"])

    def test_linear_fit_includes_black_level_intercept(self):
        fit = linear_fit([(1, 12), (2, 19), (4, 33), (8, 61)])
        self.assertAlmostEqual(fit["intercept_dn"], 5)
        self.assertAlmostEqual(fit["slope_dn_per_ms"], 7)
        self.assertAlmostEqual(fit["r_squared"], 1)

    def test_fit_qualification_rejects_bright_or_saturated_points(self):
        acceptable = {"roi_median_dn": 2000, "roi_saturation_fraction": 0.0}
        bright = {"roi_median_dn": 4000, "roi_saturation_fraction": 0.0}
        saturated = {"roi_median_dn": 2000, "roi_saturation_fraction": 0.01}
        self.assertTrue(qualified_for_fit(acceptable))
        self.assertFalse(qualified_for_fit(bright))
        self.assertFalse(qualified_for_fit(saturated))

    def test_linear_fit_requires_distinct_exposures(self):
        with self.assertRaises(ValueError):
            linear_fit([(1, 2)])
        with self.assertRaises(ValueError):
            linear_fit([(1, 2), (1, 3)])

    @unittest.skipIf(numpy is None, "calibration extra is not installed")
    def test_roi_matches_reviewed_legacy_geometry(self):
        mask, definition = _circular_roi_mask(
            2048,
            1088,
            numpy,
            center_x_percent=50,
            center_y_percent=50,
            radius_percent=60,
        )
        self.assertEqual(mask.shape, (1088, 2048))
        self.assertAlmostEqual(definition["radius_px"], 326.4)
        self.assertGreater(definition["pixel_count"], 334000)
        self.assertLess(definition["pixel_count"], 335000)

    @unittest.skipIf(numpy is None, "calibration extra is not installed")
    def test_roi_and_outside_statistics_are_separate(self):
        pixels = numpy.zeros((40, 40), dtype="<u2")
        mask = numpy.zeros((40, 40), dtype=bool)
        mask[10:30, 10:30] = True
        pixels[mask] = 100
        pixels[~mask] = 8
        result = _frame_statistics(pixels.tobytes(), 40, 40, mask, numpy)
        self.assertEqual(result["roi_median_dn"], 100)
        self.assertEqual(result["outside_median_dn"], 8)
        self.assertEqual(result["roi_saturation_fraction"], 0)


if __name__ == "__main__":
    unittest.main()
