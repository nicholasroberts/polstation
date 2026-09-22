"""Versioned observation metadata contracts; timestamps do not imply synchronization."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FrameMetadata:
    camera_id: str
    relative_path: str
    captured_at_utc: str
    timestamp_source: str
    sha256: str
    pixel_format: str
    exposure_us: float
    gain: float
    device_timestamp: int | None = None


@dataclass(frozen=True)
class SensorSample:
    sensor_id: str
    sampled_at_utc: str
    values: dict[str, float]
    units: dict[str, str]
    status: str


@dataclass(frozen=True)
class Observation:
    observation_id: str
    started_at_utc: str
    software_version: str
    git_commit: str | None
    release_tag: str | None
    calibration_id: str | None
    config_sha256: str
    frames: list[FrameMetadata] = field(default_factory=list)
    sensors: list[SensorSample] = field(default_factory=list)
    synchronization: str = "unverified"
    schema_version: int = 1
