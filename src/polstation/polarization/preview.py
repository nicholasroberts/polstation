"""Preview-only three-angle Stokes calculation and fixed colour scales."""

import binascii
from functools import cache
from importlib.resources import files
import json
import math
import struct
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


def polarization_rgb(i0, i45, i90, *, relative_gains=(1.0, 1.0, 1.0)):
    """Colour fixed-scale DoLP and AoP diagnostic maps."""
    plasma, phase = _table("plasma"), _table("phase")
    dolp_values, aop_values = polarization_values(
        i0, i45, i90, relative_gains=relative_gains
    )
    dolp_rgb, aop_rgb = bytearray(len(i0) * 3), bytearray(len(i0) * 3)
    for index, (dolp, aop) in enumerate(zip(dolp_values, aop_values)):
        dolp_index = min(int(dolp * 256), 255)
        d = index * 3
        dolp_rgb[d:d + 3] = bytes(round(channel * 255) for channel in plasma[dolp_index])
        if aop is not None:
            aop_index = min(int(aop / 180.0 * 256), 255)
            aop_rgb[d:d + 3] = bytes(round(channel * 255) for channel in phase[aop_index])
        # Undefined AoP remains black. No arbitrary low-DoLP threshold is used.
    return bytes(dolp_rgb), bytes(aop_rgb)


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
