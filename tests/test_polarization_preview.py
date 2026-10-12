"""Verify the diagnostic three-analyser Stokes convention and fixed scales."""

import math
import unittest

from polstation.polarization.preview import (
    central_circular_roi,
    instrument_matrix_values,
    legend_rgb,
    polarization_rgb,
    polarization_values,
)


class PolarizationPreviewTests(unittest.TestCase):
    def test_sensor_relative_aop_uses_half_angle(self):
        dolp, aop = polarization_values(
            bytes([100, 60, 20, 60]),
            bytes([60, 100, 60, 20]),
            bytes([20, 60, 100, 60]),
        )
        for actual, expected in zip(aop, (0.0, 45.0, 90.0, 135.0)):
            self.assertAlmostEqual(actual, expected)
        for value in dolp:
            self.assertTrue(math.isclose(value, 2 / 3))

    def test_dolp_is_clamped_and_undefined_aop_is_black(self):
        dolp, aop = polarization_values(bytes([0, 10]), bytes([0, 255]), bytes([0, 10]))
        self.assertEqual(dolp, [0.0, 1.0])
        self.assertEqual(aop, [None, 45.0])
        _, aop_rgb = polarization_rgb(bytes([0]), bytes([0]), bytes([0]))
        self.assertEqual(aop_rgb, b"\0\0\0")

    def test_fixed_legends_include_required_endpoints(self):
        dolp = legend_rgb("dolp", width=256, height=1)
        aop = legend_rgb("aop", width=256, height=1)
        self.assertEqual(dolp[:3], bytes((13, 8, 135)))
        self.assertEqual(dolp[-3:], bytes((240, 249, 33)))
        self.assertEqual(aop[:3], aop[-3:])

    def test_input_lengths_must_match(self):
        with self.assertRaisesRegex(ValueError, "matching dimensions"):
            polarization_values(b"\0", b"\0\0", b"\0")

    def test_relative_gains_are_applied_before_stokes(self):
        dolp, aop = polarization_values(
            bytes([50]), bytes([100]), bytes([100]),
            relative_gains=(2.0, 1.0, 1.0),
        )
        self.assertEqual(dolp, [0.0])
        self.assertEqual(aop, [None])

        with self.assertRaisesRegex(ValueError, "three finite positive"):
            polarization_values(b"\1", b"\1", b"\1", relative_gains=(1, 0, 1))

    def test_instrument_matrix_subtracts_dark_and_rotates_aop_reference(self):
        dolp, aop = instrument_matrix_values(
            (bytes([110]), bytes([10]), bytes([110])),
            [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            dark_offsets=(10, 10, 10),
            aop_offset_deg=90,
        )
        self.assertAlmostEqual(dolp[0], 1.0)
        self.assertAlmostEqual(aop[0], 135.0)

    def test_instrument_matrix_rejects_singular_response(self):
        with self.assertRaisesRegex(ValueError, "nonsingular"):
            instrument_matrix_values(
                (b"\1", b"\1", b"\1"),
                [[1, 0, 0], [1, 0, 0], [0, 0, 1]],
            )

    def test_derived_maps_are_black_outside_reviewed_circular_roi(self):
        mask, geometry = central_circular_roi(5, 5)
        self.assertEqual(geometry["center_x_px"], 2.0)
        self.assertFalse(mask[0])
        self.assertTrue(mask[12])
        dolp_rgb, aop_rgb = polarization_rgb(
            bytes([100] * 25), bytes([50] * 25), bytes([0] * 25),
            roi_mask=mask,
        )
        self.assertEqual(dolp_rgb[:3], b"\0\0\0")
        self.assertEqual(aop_rgb[:3], b"\0\0\0")
        self.assertNotEqual(dolp_rgb[36:39], b"\0\0\0")
        self.assertNotEqual(aop_rgb[36:39], b"\0\0\0")


if __name__ == "__main__":
    unittest.main()
