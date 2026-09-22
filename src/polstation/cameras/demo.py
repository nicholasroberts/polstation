"""In-memory preview simulator. Never opens hardware or writes observations."""
from datetime import datetime, timezone
from html import escape
import math
import time
from typing import Protocol


class PreviewSource(Protocol):
    """Read-only preview boundary; a future adapter can read worker snapshots."""

    def snapshot(self, scenario: str = "live") -> dict: ...


class DemoPreviewSource:
    """Generate repeatable one-Hz previews on request, without a capture worker."""

    def __init__(self, cameras, *, clock=time.monotonic, wall_clock=time.time):
        self.cameras = cameras
        self.clock = clock
        self.started = clock()
        self.epoch = wall_clock()

    def snapshot(self, scenario="live"):
        if scenario not in ("live", "faults"):
            raise ValueError("unknown demo scenario")
        elapsed = max(0, self.clock() - self.started)
        tick = int(elapsed)
        cameras = []
        for index, camera in enumerate(self.cameras):
            state = ("live", "stale", "disconnected")[index] if scenario == "faults" else "live"
            frame_tick = 0 if state == "stale" else tick
            # Fault mode starts with a deliberately old, frozen frame.
            frame_time = self.epoch - 30 if state == "stale" else self.epoch + frame_tick
            connected = state != "disconnected"
            cameras.append({
                "id": camera["id"], "model": camera["model"], "state": state,
                "simulated": True, "frame_number": frame_tick + 1 if connected else None,
                "captured_at_utc": datetime.fromtimestamp(frame_time, timezone.utc).isoformat() if connected else None,
                "age_seconds": round(self.epoch + elapsed - frame_time, 1) if connected else None,
                "exposure_us": [8000, 10000, 12000][index], "gain_db": 0.0,
                "preview_svg": self._frame(index, frame_tick, camera["id"]) if connected else None,
            })
        return {"mode": "demo", "hardware_ready": False, "recording": False,
                "synchronization": "not implemented", "scenario": scenario, "cameras": cameras}

    @staticmethod
    def _frame(index, tick, camera_id):
        x = 310 + 65 * math.sin(tick / 15 + index / 3)
        bands = "".join(f'<path d="M0 {y} H640" stroke="#fff" opacity=".035"/>' for y in range(0, 400, 8))
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="640" height="400" viewBox="0 0 640 400">
<defs><radialGradient id="sky"><stop stop-color="#b4c1c9"/><stop offset="1" stop-color="#303c48"/></radialGradient>
<radialGradient id="sun"><stop stop-color="#eef2f3" stop-opacity=".7"/><stop offset="1" stop-color="#eef2f3" stop-opacity="0"/></radialGradient></defs>
<rect width="640" height="400" fill="url(#sky)"/>
<circle cx="{x:.1f}" cy="130" r="150" fill="url(#sun)"/>
<path d="M-40 250 Q120 180 240 244 T680 205" fill="none" stroke="#d4dbdf" stroke-width="42" opacity=".13"/>
<path d="M-30 305 Q180 235 360 285 T680 275" fill="none" stroke="#d4dbdf" stroke-width="25" opacity=".1"/>
{bands}<g stroke="#c6d8df" opacity=".35" fill="none"><circle cx="320" cy="200" r="100"/>
<path d="M300 200 H340 M320 180 V220 M24 24 H60 M24 24 V60 M616 376 H580 M616 376 V340"/></g>
<rect y="365" width="640" height="35" fill="#101820" opacity=".7"/>
<text x="20" y="388" font-family="monospace" font-size="13" fill="#dde7eb">SIMULATED / {escape(camera_id)} / FRAME {tick + 1:06d}</text></svg>'''
