from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

import httpx
from .config import Location
from .logging import get_logger

logger = get_logger(__name__)

# Matches @lat,lng in any Google Maps URL.
_LATLNG_RE = re.compile(r"@(-?\d+\.?\d*),(-?\d+\.?\d*)")

# Matches camera params encoded in Street View URLs: ",75y,134h,90t"
# Groups: fov, heading, tilt (tilt 0–180; 90 = horizon).
_CAMERA_RE = re.compile(r",(\d+(?:\.\d+)?)y,(\d+(?:\.\d+)?)h,(\d+(?:\.\d+)?)t")


def load_locations_json(path: str | Path) -> list[Location]:
    """Load a list of :class:`Location` objects from a JSON array file."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a JSON array, got {type(raw).__name__}")
    locations = [Location.model_validate(item) for item in raw]
    logger.debug("Loaded %d location(s) from %s", len(locations), path.name)
    return locations


def load_urls_file(path: str | Path) -> list[str]:
    """Read a plain-text file of Google Maps URLs, one per line.

    Blank lines and lines starting with ``#`` are ignored.
    """
    lines = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    logger.debug("Loaded %d URL(s) from %s", len(lines), Path(path).name)
    return lines


def _resolve_shortlink(url: str, timeout: float = 5.0) -> str:
    """Follow HTTP redirects for goo.gl / maps.app.goo.gl short links."""
    host = urlparse(url).hostname or ""
    if not any(h in host for h in ("goo.gl", "maps.app.goo.gl")):
        return url
    logger.debug("Resolving short link: %s", url)
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        return str(client.get(url).url)


def parse_google_maps_url(
    url: str,
    *,
    target_years: Iterable[int] | None = None,
    all_dates: bool = False,
    year_from: int | None = None,
    year_to: int | None = None,
) -> Location:
    """Parse a Google Maps URL into a :class:`~config.Location`."""
    decoded = unquote(_resolve_shortlink(url))

    m = _LATLNG_RE.search(decoded)
    if not m:
        raise ValueError(f"Could not extract lat/lng from URL: {url!r}")
    lat, lng = float(m.group(1)), float(m.group(2))

    # Extract optional camera params from Street View URLs.
    fov = heading = pitch = None
    cam = _CAMERA_RE.search(decoded)
    if cam:
        fov = float(cam.group(1))
        heading = float(cam.group(2))
        # Street View tilt: 0–180, where 90 = horizon → convert to pitch −90..+90.
        pitch = float(cam.group(3)) - 90.0

    return Location(
        lat=lat,
        lng=lng,
        target_years=list(target_years or []),
        all_dates=all_dates,
        year_from=year_from,
        year_to=year_to,
        heading=heading,
        pitch=pitch,
        fov=fov,
    )
