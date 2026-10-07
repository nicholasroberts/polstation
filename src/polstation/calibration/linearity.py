"""Capture a provenance-rich Mono12 exposure sweep and plot camera linearity."""

import argparse
import csv
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import math
import os
from pathlib import Path
import statistics

from polstation.config import load_config
from polstation.storage.manifests import config_digest, write_json


DEFAULT_EXPOSURES_MS = (1, 2, 5, 10, 15, 25, 40, 60, 100)
DEFAULT_ROI_CENTER_X_PERCENT = 50.0
DEFAULT_ROI_CENTER_Y_PERCENT = 50.0
DEFAULT_ROI_RADIUS_PERCENT = 60.0
MIN_ROI_PIXELS = 1000
MAX_FIT_MEAN_DN = 0.90 * 4095
MAX_FIT_SATURATION_FRACTION = 0.001
MAX_FRAME_ATTEMPTS = 3


def linear_fit(points):
    """Return intercept, slope and R-squared for (x, y) points."""
    if len(points) < 2:
        raise ValueError("at least two points are required for a linear fit")
    mean_x = sum(x for x, _ in points) / len(points)
    mean_y = sum(y for _, y in points) / len(points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        raise ValueError("fit exposures must not all be equal")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    intercept = mean_y - slope * mean_x
    residual_sum = sum((y - (intercept + slope * x)) ** 2 for x, y in points)
    total_sum = sum((y - mean_y) ** 2 for _, y in points)
    r_squared = 1.0 - residual_sum / total_sum if total_sum else 1.0
    return {"intercept_dn": intercept, "slope_dn_per_ms": slope, "r_squared": r_squared}


def qualified_for_fit(row):
    return (
        row["roi_median_dn"] <= MAX_FIT_MEAN_DN
        and row["roi_saturation_fraction"] <= MAX_FIT_SATURATION_FRACTION
    )


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_raw(path, payload):
    with Path(path).open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(payload).hexdigest()


def _feature(camera, name):
    return camera.get_feature_by_name(name)


def _read_feature(camera, name):
    try:
        return _feature(camera, name).get()
    except Exception:
        return None


def _set_and_remember(camera, name, value, restorations):
    feature = _feature(camera, name)
    restorations.append((camera.get_id(), name, feature, feature.get()))
    feature.set(value)


def _get_complete_frame(camera, timeout_ms, complete_status, rejected_frames, *,
                        exposure_us, phase, repeat=None,
                        max_attempts=MAX_FRAME_ATTEMPTS,
                        retryable_exceptions=()):
    """Return a complete frame, recording bounded retries of incomplete frames."""
    camera_id = camera.get_id()
    last_status = None
    for attempt in range(1, max_attempts + 1):
        try:
            frame = camera.get_frame(timeout_ms=timeout_ms)
        except retryable_exceptions as error:
            last_status = f"{type(error).__name__}: {error}"
            rejected_frames.append({
                "camera_id": camera_id,
                "exposure_requested_us": exposure_us,
                "phase": phase,
                "repeat": repeat,
                "attempt": attempt,
                "status": last_status,
                "rejected_at_utc": datetime.now(timezone.utc).isoformat(),
            })
            print(
                f"Retrying {camera_id} at {exposure_us:.0f} us after "
                f"{last_status} (attempt {attempt}/{max_attempts})",
                flush=True,
            )
            continue
        last_status = frame.get_status()
        if last_status == complete_status:
            return frame, attempt
        rejected_frames.append({
            "camera_id": camera_id,
            "exposure_requested_us": exposure_us,
            "phase": phase,
            "repeat": repeat,
            "attempt": attempt,
            "status": str(last_status),
            "rejected_at_utc": datetime.now(timezone.utc).isoformat(),
        })
        print(
            f"Retrying {camera_id} at {exposure_us:.0f} us after "
            f"{last_status} (attempt {attempt}/{max_attempts})",
            flush=True,
        )
    raise RuntimeError(
        f"{camera_id}: no complete frame after {max_attempts} attempts; "
        f"last status {last_status}"
    )


def _circular_roi_mask(width, height, numpy, *, center_x_percent,
                       center_y_percent, radius_percent):
    center_x = (center_x_percent / 100.0) * (width - 1)
    center_y = (center_y_percent / 100.0) * (height - 1)
    requested_radius = (radius_percent / 100.0) * (min(height, width) / 2.0)
    maximum_radius = min(
        center_x, (width - 1) - center_x,
        center_y, (height - 1) - center_y,
    )
    radius = min(requested_radius, maximum_radius)
    yy, xx = numpy.ogrid[:height, :width]
    mask = ((xx - center_x) ** 2 + (yy - center_y) ** 2) <= radius ** 2
    pixel_count = int(numpy.count_nonzero(mask))
    if pixel_count < MIN_ROI_PIXELS:
        raise ValueError(f"circular ROI contains only {pixel_count} pixels")
    return mask, {
        "center_x_percent": center_x_percent,
        "center_y_percent": center_y_percent,
        "radius_percent_of_half_min_dimension": radius_percent,
        "center_x_px": center_x,
        "center_y_px": center_y,
        "radius_px": radius,
        "pixel_count": pixel_count,
        "outside_pixel_count": width * height - pixel_count,
    }


def _frame_statistics(raw, width, height, roi_mask, numpy):
    expected = width * height * 2
    if len(raw) != expected:
        raise RuntimeError(
            f"unexpected Mono12 buffer size {len(raw)}; expected {expected}"
        )
    pixels = numpy.frombuffer(raw, dtype="<u2").reshape((height, width))
    roi = pixels[roi_mask]
    outside = pixels[~roi_mask]
    return {
        "full_mean_dn": float(pixels.mean(dtype=numpy.float64)),
        "roi_mean_dn": float(roi.mean(dtype=numpy.float64)),
        "roi_median_dn": float(numpy.median(roi)),
        "outside_mean_dn": float(outside.mean(dtype=numpy.float64)),
        "outside_median_dn": float(numpy.median(outside)),
        "minimum_dn": int(pixels.min()),
        "maximum_dn": int(pixels.max()),
        "roi_saturation_fraction": float(numpy.count_nonzero(roi >= 4095) / roi.size),
    }


def _write_summary(path, rows):
    fields = (
        "camera_id", "analyser_angle_deg", "exposure_ms", "frame_count",
        "roi_median_dn", "roi_frame_median_std_dn", "roi_mean_dn",
        "roi_q05_dn", "roi_q25_dn", "roi_q75_dn", "roi_q95_dn",
        "outside_median_dn", "outside_mean_dn", "roi_minus_outside_median_dn",
        "full_mean_dn", "minimum_dn", "maximum_dn",
        "roi_saturation_fraction", "qualified_for_fit",
    )
    with Path(path).open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({name: row[name] for name in fields} for row in rows)


def _plot(output, rows, fits):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as pyplot

    colours = ("#1f77b4", "#ff7f0e", "#2ca02c")
    camera_ids = sorted({row["camera_id"] for row in rows})

    figure, axis = pyplot.subplots(figsize=(9, 6))
    for colour, camera_id in zip(colours, camera_ids):
        camera_rows = [row for row in rows if row["camera_id"] == camera_id]
        accepted = [row for row in camera_rows if row["qualified_for_fit"]]
        rejected = [row for row in camera_rows if not row["qualified_for_fit"]]
        label = f"{camera_id} ({camera_rows[0]['analyser_angle_deg']}°)"
        axis.errorbar(
            [row["exposure_ms"] for row in accepted],
            [row["roi_median_dn"] for row in accepted],
            yerr=[row["roi_frame_median_std_dn"] for row in accepted],
            marker="o", linestyle="none", capsize=3, color=colour, label=label,
        )
        if rejected:
            axis.scatter(
                [row["exposure_ms"] for row in rejected],
                [row["roi_median_dn"] for row in rejected],
                marker="x", color=colour,
            )
        axis.plot(
            [row["exposure_ms"] for row in camera_rows],
            [row["outside_median_dn"] for row in camera_rows],
            color=colour, linestyle=":", alpha=0.65,
        )
        fit = fits[camera_id]
        x_values = [min(row["exposure_ms"] for row in camera_rows),
                    max(row["exposure_ms"] for row in camera_rows)]
        axis.plot(
            x_values,
            [fit["intercept_dn"] + fit["slope_dn_per_ms"] * x for x in x_values],
            color=colour, alpha=0.75,
        )
    axis.axhline(4095, color="black", linewidth=0.8, linestyle=":", label="12-bit maximum")
    axis.set(title="Central circular-ROI response versus exposure", xlabel="Exposure (ms)", ylabel="Raw ROI median (DN)")
    axis.text(
        0.01, 0.99, "Points: ROI median; dotted: outside-ROI median; no dark subtraction",
        transform=axis.transAxes, va="top", fontsize="small",
    )
    axis.grid(True, alpha=0.25)
    axis.legend(fontsize="small")
    figure.tight_layout()
    figure.savefig(output / "linearity-response.png", dpi=180)
    pyplot.close(figure)

    figure, axis = pyplot.subplots(figsize=(9, 5))
    for colour, camera_id in zip(colours, camera_ids):
        camera_rows = [row for row in rows if row["camera_id"] == camera_id and row["qualified_for_fit"]]
        fit = fits[camera_id]
        residuals = []
        for row in camera_rows:
            predicted = fit["intercept_dn"] + fit["slope_dn_per_ms"] * row["exposure_ms"]
            signal = max(predicted - fit["intercept_dn"], 1.0)
            residuals.append(100.0 * (row["roi_median_dn"] - predicted) / signal)
        axis.plot(
            [row["exposure_ms"] for row in camera_rows], residuals,
            marker="o", color=colour,
            label=f"{camera_id} ({camera_rows[0]['analyser_angle_deg']}°)",
        )
    axis.axhline(0, color="black", linewidth=0.8)
    axis.set(title="Residual from fitted linear response", xlabel="Exposure (ms)", ylabel="Residual (% of fitted signal)")
    axis.grid(True, alpha=0.25)
    axis.legend(fontsize="small")
    figure.tight_layout()
    figure.savefig(output / "linearity-residuals.png", dpi=180)
    pyplot.close(figure)

    figure, axis = pyplot.subplots(figsize=(11, 6))
    exposures = sorted({row["exposure_ms"] for row in rows})
    positions = {exposure: index + 1 for index, exposure in enumerate(exposures)}
    offsets = (-0.24, 0.0, 0.24)
    for colour, offset, camera_id in zip(colours, offsets, camera_ids):
        camera_rows = sorted(
            (row for row in rows if row["camera_id"] == camera_id),
            key=lambda row: row["exposure_ms"],
        )
        box_statistics = [{
            "med": row["roi_median_dn"],
            "q1": row["roi_q25_dn"],
            "q3": row["roi_q75_dn"],
            "whislo": row["roi_q05_dn"],
            "whishi": row["roi_q95_dn"],
            "fliers": [],
        } for row in camera_rows]
        artists = axis.bxp(
            box_statistics,
            positions=[positions[row["exposure_ms"]] + offset for row in camera_rows],
            widths=0.20,
            patch_artist=True,
            showfliers=False,
            manage_ticks=False,
        )
        for box in artists["boxes"]:
            box.set(facecolor=colour, edgecolor=colour, alpha=0.35)
        for part in ("whiskers", "caps", "medians"):
            for artist in artists[part]:
                artist.set(color=colour)
        axis.plot([], [], color=colour, linewidth=8, alpha=0.35,
                  label=f"{camera_id} ({camera_rows[0]['analyser_angle_deg']}°)")
    axis.set_xticks(range(1, len(exposures) + 1), [f"{value:g}" for value in exposures])
    axis.set(
        title="Central circular-ROI pixel brightness distributions",
        xlabel="Exposure (ms)", ylabel="Mean-image ROI brightness (DN)",
    )
    axis.text(
        0.01, 0.99, "Boxes: 25th–75th; median line; whiskers: 5th–95th percentiles",
        transform=axis.transAxes, va="top", fontsize="small",
    )
    axis.grid(True, axis="y", alpha=0.25)
    axis.legend(fontsize="small")
    figure.tight_layout()
    figure.savefig(output / "linearity-roi-boxplots.png", dpi=180)
    pyplot.close(figure)


def capture(config, output, exposures_ms, frames_per_point, source_note, *,
            roi_center_x_percent=DEFAULT_ROI_CENTER_X_PERCENT,
            roi_center_y_percent=DEFAULT_ROI_CENTER_Y_PERCENT,
            roi_radius_percent=DEFAULT_ROI_RADIUS_PERCENT):
    try:
        import numpy
        from vmbpy import FrameStatus, PixelFormat, VmbSystem, VmbTimeout
    except ImportError as error:
        raise RuntimeError(
            "Install the calibration extra and VmbPy before capture"
        ) from error

    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    raw_directory = output / "raw"
    raw_directory.mkdir()
    started = datetime.now(timezone.utc)
    frame_records = []
    rejected_frames = []
    summaries = []
    settings = {}
    roi_masks = {}
    roi_definitions = {}
    configured = {camera["id"]: camera for camera in config["cameras"]}

    try:
        with VmbSystem.get_instance() as vmb:
            discovered = {camera.get_id(): camera for camera in vmb.get_all_cameras()}
            missing = sorted(set(configured) - set(discovered))
            if missing:
                raise RuntimeError(f"configured cameras not discovered: {', '.join(missing)}")
            if len(discovered) != 3:
                raise RuntimeError(f"expected exactly three cameras, found {len(discovered)}")

            with ExitStack() as stack:
                cameras = [stack.enter_context(discovered[camera_id]) for camera_id in configured]
                restorations = []
                original_pixel_formats = []
                try:
                    for camera in cameras:
                        camera_id = camera.get_id()
                        original_pixel_formats.append((camera, camera.get_pixel_format()))
                        camera.set_pixel_format(PixelFormat.Mono12)
                        _set_and_remember(camera, "GevSCPSPacketSize", 1500, restorations)
                        _set_and_remember(camera, "TriggerMode", "Off", restorations)
                        _set_and_remember(camera, "ExposureAuto", "Off", restorations)
                        _set_and_remember(camera, "GainAuto", "Off", restorations)
                        _set_and_remember(camera, "Gain", 0.0, restorations)
                        _set_and_remember(camera, "Gamma", 1.0, restorations)
                        settings[camera_id] = {
                            "model": camera.get_model(),
                            "serial": camera.get_serial(),
                            "analyser_angle_deg": configured[camera_id]["polarizer_angle_deg"],
                            "pixel_format": "Mono12",
                            "gain_db": _read_feature(camera, "Gain"),
                            "gamma": _read_feature(camera, "Gamma"),
                            "black_level": _read_feature(camera, "BlackLevel"),
                            "packet_size": _read_feature(camera, "GevSCPSPacketSize"),
                        }

                    for exposure_ms in exposures_ms:
                        exposure_us = exposure_ms * 1000.0
                        for camera in cameras:
                            _feature(camera, "ExposureTimeAbs").set(exposure_us)
                        # Discard one frame after every exposure change.
                        for camera in cameras:
                            timeout_ms = max(5000, int(exposure_ms * 4 + 2000))
                            _get_complete_frame(
                                camera, timeout_ms, FrameStatus.Complete,
                                rejected_frames, exposure_us=exposure_us,
                                phase="settling",
                                retryable_exceptions=(VmbTimeout,),
                            )

                        values = {camera.get_id(): [] for camera in cameras}
                        image_sums = {}
                        for repeat in range(frames_per_point):
                            order = cameras if repeat % 2 == 0 else list(reversed(cameras))
                            for camera in order:
                                camera_id = camera.get_id()
                                timeout_ms = max(5000, int(exposure_ms * 4 + 2000))
                                frame, capture_attempt = _get_complete_frame(
                                    camera, timeout_ms, FrameStatus.Complete,
                                    rejected_frames, exposure_us=exposure_us,
                                    phase="recorded", repeat=repeat,
                                    retryable_exceptions=(VmbTimeout,),
                                )
                                captured_at = datetime.now(timezone.utc).isoformat()
                                raw = bytes(frame.get_buffer())
                                width, height = frame.get_width(), frame.get_height()
                                if camera_id not in roi_masks:
                                    roi_masks[camera_id], roi_definitions[camera_id] = _circular_roi_mask(
                                        width, height, numpy,
                                        center_x_percent=roi_center_x_percent,
                                        center_y_percent=roi_center_y_percent,
                                        radius_percent=roi_radius_percent,
                                    )
                                measured = _frame_statistics(
                                    raw, width, height, roi_masks[camera_id], numpy
                                )
                                if camera_id not in image_sums:
                                    image_sums[camera_id] = numpy.zeros(
                                        (height, width), dtype=numpy.float64
                                    )
                                image_sums[camera_id] += numpy.frombuffer(
                                    raw, dtype="<u2"
                                ).reshape((height, width))
                                values[camera_id].append(measured)
                                filename = f"{camera_id}_exp-{exposure_us:.0f}us_frame-{repeat:03d}.raw"
                                raw_path = raw_directory / filename
                                frame_records.append({
                                    "camera_id": camera_id,
                                    "analyser_angle_deg": configured[camera_id]["polarizer_angle_deg"],
                                    "exposure_requested_us": exposure_us,
                                    "exposure_readback_us": _read_feature(camera, "ExposureTimeAbs"),
                                    "captured_at_utc": captured_at,
                                    "device_timestamp": frame.get_timestamp(),
                                    "frame_id": frame.get_id(),
                                    "capture_attempt": capture_attempt,
                                    "device_temperature_c": _read_feature(camera, "DeviceTemperature"),
                                    "width": width,
                                    "height": height,
                                    "pixel_format": "Mono12",
                                    "byte_order": "little-endian",
                                    "packing": "12-bit values in 16-bit words",
                                    "path": str(raw_path.relative_to(output)),
                                    "sha256": _write_raw(raw_path, raw),
                                    **measured,
                                })

                        for camera in cameras:
                            camera_id = camera.get_id()
                            camera_values = values[camera_id]
                            frame_roi_medians = [item["roi_median_dn"] for item in camera_values]
                            mean_image = image_sums[camera_id] / len(camera_values)
                            roi_values = mean_image[roi_masks[camera_id]]
                            outside_values = mean_image[~roi_masks[camera_id]]
                            percentiles = numpy.percentile(roi_values, (5, 25, 50, 75, 95))
                            roi_median = float(percentiles[2])
                            outside_median = float(numpy.median(outside_values))
                            row = {
                                "camera_id": camera_id,
                                "analyser_angle_deg": configured[camera_id]["polarizer_angle_deg"],
                                "exposure_ms": exposure_ms,
                                "frame_count": len(camera_values),
                                "roi_median_dn": roi_median,
                                "roi_frame_median_std_dn": statistics.stdev(frame_roi_medians) if len(frame_roi_medians) > 1 else 0.0,
                                "roi_mean_dn": float(roi_values.mean(dtype=numpy.float64)),
                                "roi_q05_dn": float(percentiles[0]),
                                "roi_q25_dn": float(percentiles[1]),
                                "roi_q75_dn": float(percentiles[3]),
                                "roi_q95_dn": float(percentiles[4]),
                                "outside_median_dn": outside_median,
                                "outside_mean_dn": float(outside_values.mean(dtype=numpy.float64)),
                                "roi_minus_outside_median_dn": roi_median - outside_median,
                                "full_mean_dn": float(mean_image.mean(dtype=numpy.float64)),
                                "minimum_dn": min(item["minimum_dn"] for item in camera_values),
                                "maximum_dn": max(item["maximum_dn"] for item in camera_values),
                                "roi_saturation_fraction": max(item["roi_saturation_fraction"] for item in camera_values),
                            }
                            row["qualified_for_fit"] = qualified_for_fit(row)
                            summaries.append(row)
                finally:
                    for _, _, feature, original in reversed(restorations):
                        try:
                            feature.set(original)
                        except Exception:
                            pass
                    for camera, original in reversed(original_pixel_formats):
                        try:
                            camera.set_pixel_format(original)
                        except Exception:
                            pass

        fits = {}
        for camera_id in configured:
            points = [
                (row["exposure_ms"], row["roi_median_dn"])
                for row in summaries
                if row["camera_id"] == camera_id and row["qualified_for_fit"]
            ]
            fits[camera_id] = linear_fit(points)

        summary_path = output / "linearity-summary.csv"
        _write_summary(summary_path, summaries)
        _plot(output, summaries, fits)
        manifest = {
            "schema_version": 1,
            "kind": "camera-linearity-scout",
            "complete": True,
            "started_at_utc": started.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "software": {"package": "polstation", "version": version("polstation")},
            "provenance": config["provenance"],
            "config_sha256": config_digest(config),
            "source_note": source_note,
            "source_polarization_assumption": "residual DoP consistent with zero for the verified five-diffuser setup",
            "synchronization": "sequential; alternating camera order between repeats",
            "fit": {
                "model": "raw_roi_median_dn = intercept_dn + slope_dn_per_ms * exposure_ms",
                "dark_subtracted": False,
                "maximum_roi_median_dn": MAX_FIT_MEAN_DN,
                "maximum_saturation_fraction": MAX_FIT_SATURATION_FRACTION,
                "results": fits,
            },
            "exposures_ms": list(exposures_ms),
            "frames_per_point": frames_per_point,
            "camera_settings": settings,
            "frames": frame_records,
            "rejected_frames": rejected_frames,
            "products": {},
        }
        manifest["roi"] = {
            "role": "primary scientific analysis region",
            "geometry": "central circle",
            "definitions_by_camera": roi_definitions,
            "outside_role": "recorded dynamic-baseline diagnostic; not automatically subtracted",
        }
        for filename in (
            "linearity-summary.csv", "linearity-response.png",
            "linearity-residuals.png", "linearity-roi-boxplots.png",
        ):
            manifest["products"][filename] = {"sha256": _sha256(output / filename)}
        write_json(output / "manifest.json", manifest)
        return output
    except Exception:
        # An absent manifest deliberately marks a partial capture for investigation.
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True, help="new directory; must not already exist")
    parser.add_argument("--exposures-ms", nargs="+", type=float, default=DEFAULT_EXPOSURES_MS)
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--source-note", required=True)
    parser.add_argument("--roi-center-x-percent", type=float, default=DEFAULT_ROI_CENTER_X_PERCENT)
    parser.add_argument("--roi-center-y-percent", type=float, default=DEFAULT_ROI_CENTER_Y_PERCENT)
    parser.add_argument("--roi-radius-percent", type=float, default=DEFAULT_ROI_RADIUS_PERCENT)
    args = parser.parse_args()
    if args.frames < 2:
        parser.error("--frames must be at least 2")
    if len(args.exposures_ms) < 3 or any(not math.isfinite(value) or value <= 0 for value in args.exposures_ms):
        parser.error("provide at least three finite positive exposures")
    if len(set(args.exposures_ms)) != len(args.exposures_ms):
        parser.error("exposures must be unique")
    if not 0 <= args.roi_center_x_percent <= 100 or not 0 <= args.roi_center_y_percent <= 100:
        parser.error("ROI centre percentages must be between 0 and 100")
    if not 1 <= args.roi_radius_percent <= 100:
        parser.error("ROI radius percentage must be between 1 and 100")
    config = load_config(args.config)
    destination = capture(
        config, args.output, tuple(args.exposures_ms), args.frames, args.source_note,
        roi_center_x_percent=args.roi_center_x_percent,
        roi_center_y_percent=args.roi_center_y_percent,
        roi_radius_percent=args.roi_radius_percent,
    )
    print(f"Complete calibration scout: {destination}")
    print(f"Response graph: {destination / 'linearity-response.png'}")
    print(f"Residual graph: {destination / 'linearity-residuals.png'}")
    print(f"ROI boxplots: {destination / 'linearity-roi-boxplots.png'}")


if __name__ == "__main__":
    main()
