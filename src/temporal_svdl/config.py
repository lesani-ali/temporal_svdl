from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

load_dotenv(override=False)

_SIZE_RE = re.compile(r"^\d{2,4}x\d{2,4}$")


class Defaults(BaseModel):
    """Default camera parameters applied to any Location field left unset."""

    heading: float = Field(0.0, ge=0, lt=360, description="Compass heading (0=north, 90=east).")
    pitch: float = Field(0.0, ge=-90, le=90, description="Vertical angle (0=horizontal).")
    fov: float = Field(60.0, gt=0, le=120, description="Horizontal field of view in degrees.")
    size: str = Field("640x640", description="Image size as 'WIDTHxHEIGHT'.")
    radius: int = Field(50, ge=0, description="Search radius in metres.")


class Location(BaseModel):
    id: Optional[str] = Field(None, description="Human-readable label. Auto-generated if omitted.")
    lat: float = Field(..., ge=-90, le=90, description="Latitude in decimal degrees.")
    lng: float = Field(..., ge=-180, le=180, description="Longitude in decimal degrees.")

    target_years: list[int] = Field(
        default_factory=list,
        description="Years of interest. Ignored when all_dates=True.",
    )
    all_dates: bool = Field(
        False,
        description="If True, every discovered historical pano is downloaded.",
    )
    year_from: Optional[int] = Field(
        None,
        ge=2007,
        description="Exclude panos captured before this year.",
    )
    year_to: Optional[int] = Field(
        None,
        ge=2007,
        description="Exclude panos captured after this year.",
    )

    # Camera overrides (fall back to Config.defaults when None)
    heading: Optional[float] = Field(None, ge=0, lt=360)
    pitch: Optional[float] = Field(None, ge=-90, le=90)
    fov: Optional[float] = Field(None, gt=0, le=120)
    size: Optional[str] = None
    radius: Optional[int] = Field(None, ge=0)

    @field_validator("size")
    @classmethod
    def _check_size(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SIZE_RE.match(v):
            raise ValueError(f"size must look like '640x640', got {v!r}")
        return v

    @model_validator(mode="after")
    def _check_temporal(self) -> "Location":
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise ValueError(f"year_from ({self.year_from}) must be ≤ year_to ({self.year_to}).")
        return self

    @model_validator(mode="after")
    def _auto_id(self) -> "Location":
        if self.id is None:
            self.id = f"loc_{self.lat:.5f}_{self.lng:.5f}".replace(".", "p").replace("-", "m")
        return self

    def fill(self, defaults: Defaults) -> "Location":
        """Return a copy with unset camera fields filled from *defaults*."""
        return self.model_copy(
            update={
                "heading": self.heading if self.heading is not None else defaults.heading,
                "pitch": self.pitch if self.pitch is not None else defaults.pitch,
                "fov": self.fov if self.fov is not None else defaults.fov,
                "size": self.size or defaults.size,
                "radius": self.radius if self.radius is not None else defaults.radius,
            }
        )


class Config(BaseModel):
    package_name: str = Field("temporal_svdl")
    output_dir: Path = Field(
        Path("data/output"),
        description="Root directory for downloaded images and cache files.",
    )
    defaults: Defaults = Field(
        default_factory=Defaults,
        description="Camera parameter fallbacks for any Location that omits them.",
    )

    # Concurrency
    discovery_workers: int = Field(4, ge=1, le=32, description="Parallel discovery workers.")
    download_workers: int = Field(16, ge=1, le=128, description="Parallel download workers.")

    # Retry / back-off
    max_retries: int = Field(5, ge=1, description="Maximum download attempts per image.")
    initial_backoff_seconds: float = Field(
        1.0, gt=0, description="Initial retry back-off (seconds)."
    )
    max_backoff_seconds: float = Field(30.0, gt=0, description="Maximum retry back-off (seconds).")

    # Logging
    log_level: str = Field("INFO", description="Python logging level (DEBUG/INFO/WARNING/ERROR).")
    log_file: Optional[Path] = Field(
        None, description="Path to log file. If None, logs are only written to console."
    )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Load a Config from a YAML file, merging over model defaults."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.model_validate(data)

    @property
    def manifest_path(self) -> Path:
        """CSV file that records every download attempt (enables resume)."""
        return self.output_dir / "manifest.csv"

    @property
    def panos_cache_path(self) -> Path:
        """JSON cache of discovered pano IDs (avoids re-querying on re-runs)."""
        return self.output_dir / "discovered_panos.json"


def get_api_key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GOOGLE_MAPS_API_KEY is not set.\n"
            "  1. Copy .env.example → .env\n"
            "  2. Fill in GOOGLE_MAPS_API_KEY=<your-key>\n"
            "  3. The key must have 'Street View Static API' enabled."
        )
    return key


def get_signing_secret() -> Optional[str]:
    """Return the optional URL-signing secret, or None if not configured."""
    return os.environ.get("GOOGLE_MAPS_URL_SIGNING_SECRET") or None
