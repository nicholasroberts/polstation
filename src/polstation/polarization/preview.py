"""Preview-only three-angle Stokes calculation and fixed colour scales."""

from array import array
import binascii
from functools import cache
from importlib.resources import files
import json
import math
import struct
import sys
import zlib


@cache
def _table(name):
    return json.loads(files("polstation.polarization").joinpath("colormaps", name + ".json").read_text())


def sample_mono8(buffer, width, height, *, max_width=640, max_height=400):
    """Nearest-neighbour reduction on the native Mono8 grid."""
    if width <= 0 or height <= 0:
        raise ValueError("frame dimensions must be positive")
    pixels = memoryview(buffer).cast("B")
    if len(pixels) < width * height:
        raise ValueError("frame buffer is smaller than its dimensions")
    step = max(1, (width + max_width - 1) // max_width, (height + max_height - 1) // max_height)
    sampled_width = (width + step - 1) // step
    sampled_height = (height + step - 1) // step
    sampled = bytearray(sampled_width * sampled_height)
    offset = 0
    for y in range(0, height, step):
        row = pixels[y * width:y * width + width:step]
        sampled[offset:offset + sampled_width] = row
        offset += sampled_width
    return sampled_width, sampled_height, bytes(sampled)


def sample_mono12(buffer, width, height, *, max_width=640, max_height=400):
    """Reduce little-endian Mono12-in-16-bit data to a bounded 8-bit preview."""
    if width <= 0 or height <= 0:
        raise ValueError("frame dimensions must be positive")
    expected_bytes = width * height * 2
    if len(buffer) != expected_bytes:
        raise ValueError(
            f"Mono12 buffer length {len(buffer)} does not match {width}x{height}"
        )
    pixels = array("H")
    pixels.frombytes(buffer)
    if sys.byteorder != "little":
        pixels.byteswap()
    step = max(
        1,
        (width + max_width - 1) // max_width,
        (height + max_height - 1) // max_height,
    )
    sampled_width = (width + step - 1) // step
    sampled_height = (height + step - 1) // step
    sampled = bytearray(sampled_width * sampled_height)
    offset = 0
    for y in range(0, height, step):
        row_start = y * width
        for x in range(0, width, step):
            sampled[offset] = (pixels[row_start + x] & 0x0FFF) >> 4
            offset += 1
    return sampled_width, sampled_height, bytes(sampled)


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def encode_png(pixels, width, height, *, channels=1):
    """Encode 8-bit grayscale or RGB pixels without an imaging dependency."""
    if channels not in (1, 3) or len(pixels) != width * height * channels:
        raise ValueError("pixel buffer does not match PNG dimensions")
    stride = width * channels
    rows = b"".join(b"\0" + pixels[start:start + stride] for start in range(0, len(pixels), stride))
    header = struct.pack(">IIBBBBB", width, height, 8, 0 if channels == 1 else 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(rows, 3)) + _chunk(b"IEND", b""))


def central_circular_roi(width, height, *, radius_percent=60.0):
    """Return the reviewed centred fisheye ROI mask and its geometry."""
    if width <= 0 or height <= 0:
        raise ValueError("ROI dimensions must be positive")
    if not 0 < radius_percent <= 100:
        raise ValueError("ROI radius percentage must be between 0 and 100")
    center_x = 0.5 * (width - 1)
    center_y = 0.5 * (height - 1)
    requested_radius = (radius_percent / 100.0) * (min(width, height) / 2.0)
    radius = min(
        requested_radius, center_x, (width - 1) - center_x,
        center_y, (height - 1) - center_y,
    )
    radius_squared = radius * radius
    mask = bytes(
        (x - center_x) ** 2 + (y - center_y) ** 2 <= radius_squared
        for y in range(height) for x in range(width)
    )
    return mask, {
        "center_x_percent": 50.0,
        "center_y_percent": 50.0,
        "radius_percent_of_half_min_dimension": radius_percent,
        "center_x_px": center_x,
        "center_y_px": center_y,
        "radius_px": radius,
        "pixel_count": sum(mask),
        "outside_pixel_count": width * height - sum(mask),
    }


def polarization_values(i0, i45, i90, *, relative_gains=(1.0, 1.0, 1.0)):
    """Return DoLP fractions and sensor-relative AoP degrees.

    Inputs must be corresponding Mono8 preview pixels. Separate-camera spatial
    registration, temporal synchronization, and dark correction are not
    performed here. Optional relative gains are applied to I0, I45, and I90
    respectively before the Stokes calculation.
    """
    if len(i0) != len(i45) or len(i0) != len(i90):
        raise ValueError("polarization inputs must have matching dimensions")
    if (len(relative_gains) != 3
            or any(isinstance(gain, bool) or not isinstance(gain, (int, float))
                   or not math.isfinite(gain) or gain <= 0 for gain in relative_gains)):
        raise ValueError("relative gains must contain three finite positive numbers")
    gain0, gain45, gain90 = relative_gains
    dolp_values, aop_values = [], []
    for raw_zero, raw_forty_five, raw_ninety in zip(i0, i45, i90):
        zero = gain0 * raw_zero
        forty_five = gain45 * raw_forty_five
        ninety = gain90 * raw_ninety
        s0 = zero + ninety
        q = zero - ninety
        u = 2 * forty_five - s0
        dolp = min(1.0, math.hypot(q, u) / s0) if s0 else 0.0
        dolp_values.append(dolp)
        aop_values.append((0.5 * math.degrees(math.atan2(u, q))) % 180.0
                          if s0 and (q or u) else None)
    return dolp_values, aop_values


def polarization_rgb(i0, i45, i90, *, relative_gains=(1.0, 1.0, 1.0), roi_mask=None):
    """Colour fixed-scale DoLP and AoP diagnostic maps."""
    dolp_values, aop_values = polarization_values(
        i0, i45, i90, relative_gains=relative_gains
    )
    return _values_rgb(dolp_values, aop_values, roi_mask=roi_mask)


def _inverse_3x3(matrix):
    """Return the inverse of a finite, nonsingular 3x3 matrix."""
    if (len(matrix) != 3 or any(len(row) != 3 for row in matrix)
            or any(not math.isfinite(value) for row in matrix for value in row)):
        raise ValueError("instrument response matrix must be finite and 3x3")
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) < 1e-12:
        raise ValueError("instrument response matrix must be nonsingular")
    return (
        ((e * i - f * h) / determinant, (c * h - b * i) / determinant,
         (b * f - c * e) / determinant),
        ((f * g - d * i) / determinant, (a * i - c * g) / determinant,
         (c * d - a * f) / determinant),
        ((d * h - e * g) / determinant, (b * g - a * h) / determinant,
         (a * e - b * d) / determinant),
    )


def instrument_matrix_values(channels, response_matrix, *, dark_offsets=(0.0, 0.0, 0.0),
                             aop_offset_deg=0.0):
    """Recover unclipped DoLP and AoP from a provisional three-camera matrix.

    ``response_matrix`` maps relative Stokes ``[S0, Q, U]`` to the ordered
    camera signals. Scalar dark offsets are subtracted before inversion. The
    angle offset rotates the recovered relative Q/U coordinates into the
    sensor-relative convention.
    """
    if len(channels) != 3 or len({len(channel) for channel in channels}) != 1:
        raise ValueError("instrument matrix inputs must contain three matching channels")
    if (len(dark_offsets) != 3
            or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   or not math.isfinite(value) for value in dark_offsets)):
        raise ValueError("dark offsets must contain three finite numbers")
    if (isinstance(aop_offset_deg, bool) or not isinstance(aop_offset_deg, (int, float))
            or not math.isfinite(aop_offset_deg)):
        raise ValueError("AoP offset must be finite")
    inverse = _inverse_3x3(response_matrix)
    rotation = math.radians(2.0 * aop_offset_deg)
    cosine, sine = math.cos(rotation), math.sin(rotation)
    dolp_values, aop_values = [], []
    for raw in zip(*channels):
        signal = tuple(value - offset for value, offset in zip(raw, dark_offsets))
        s0, q_relative, u_relative = (
            sum(row[index] * signal[index] for index in range(3)) for row in inverse
        )
        q = q_relative * cosine - u_relative * sine
        u = q_relative * sine + u_relative * cosine
        if s0 > 0 and (q or u):
            dolp_values.append(math.hypot(q, u) / s0)
            aop_values.append((0.5 * math.degrees(math.atan2(u, q))) % 180.0)
        else:
            dolp_values.append(0.0)
            aop_values.append(None)
    return dolp_values, aop_values


def _values_rgb(dolp_values, aop_values, *, roi_mask=None):
    if roi_mask is not None and len(roi_mask) != len(dolp_values):
        raise ValueError("ROI mask must match polarization dimensions")
    plasma, phase = _table("plasma"), _table("phase")
    dolp_rgb, aop_rgb = bytearray(len(dolp_values) * 3), bytearray(len(dolp_values) * 3)
    for index, (dolp, aop) in enumerate(zip(dolp_values, aop_values)):
        if roi_mask is not None and not roi_mask[index]:
            continue
        dolp_index = min(int(max(0.0, dolp) * 256), 255)
        destination = index * 3
        dolp_rgb[destination:destination + 3] = bytes(
            round(channel * 255) for channel in plasma[dolp_index]
        )
        if aop is not None:
            aop_index = min(int(aop / 180.0 * 256), 255)
            aop_rgb[destination:destination + 3] = bytes(
                round(channel * 255) for channel in phase[aop_index]
            )
    return bytes(dolp_rgb), bytes(aop_rgb)


def instrument_matrix_rgb(channels, response_matrix, *, dark_offsets=(0.0, 0.0, 0.0),
                          aop_offset_deg=0.0, roi_mask=None):
    """Colour fixed-scale maps from the provisional instrument matrix."""
    values = instrument_matrix_values(
        channels, response_matrix, dark_offsets=dark_offsets,
        aop_offset_deg=aop_offset_deg,
    )
    return _values_rgb(*values, roi_mask=roi_mask)


def legend_rgb(kind, width=256, height=12):
    table = _table("plasma" if kind == "dolp" else "phase")
    row = bytearray()
    for x in range(width):
        if kind == "dolp":
            index = min(round(x / (width - 1) * 255), 255)
        elif kind == "aop":
            # Include the cyclic seam: 180 degrees has the same colour as zero.
            index = 0 if x == width - 1 else min(int(x / (width - 1) * 256), 255)
        else:
            raise ValueError("unknown polarization legend")
        row.extend(round(channel * 255) for channel in table[index])
    return bytes(row) * height
