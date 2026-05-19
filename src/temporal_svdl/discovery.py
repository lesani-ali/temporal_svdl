from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Optional

import httpx

from .config import Config, Location
from .logging import get_logger

logger = get_logger(__name__)

# Internal GeoPhoto API endpoint.
_GEOPHOTO_ENDPOINT = "https://maps.googleapis.com/maps/api/js/GeoPhotoService.SingleImageSearch"

# Protobuf-lite encoded query template for the GeoPhoto API.
# Notable fields:
#   3d / 4d  — latitude / longitude
#   2d       — search radius in metres
#   1sen     — response language (English)
#   2sGB     — region hint (GB)
#   1e2      — imagery-type filter (Street View only)
_PB_TEMPLATE = (
    "!1m5!1sapiv3!5sUS!11m2!1m1!1b0"
    "!2m4!1m2!3d{lat}!4d{lng}!2d{radius}"
    "!3m10!2m2!1sen!2sGB!9m1!1e2"
    "!11m4!1m3!1e2!2b1!3e2"
    "!4m10!1e1!1e2!1e3!1e4!1e8!1e6!5m1!1e2!6m1!1e2"
)

# JSONP callback name (arbitrary, but must match the server's response wrapper).
_CALLBACK = "callbackfunc"

_JSONP_WRAPPER_RE = re.compile(r"\w+\(\s*(.*)\s*\)\s*$", re.DOTALL)


@dataclass(frozen=True)
class HistoricalPano:
    """A single Street View panorama at a specific point in time.

    Attributes:
        pano_id: Google panorama identifier.
        year:    Capture year.
        month:   Capture month (1–12).
        iso:     Capture date as ``'YYYY-MM'``.
    """

    pano_id: str
    year: int
    month: int
    iso: str


@dataclass
class DiscoveryResult:
    """Outcome of a single-location GeoPhoto query.

    Attributes:
        location_id: ID of the queried :class:`~config.Location`.
        panos:       Discovered panoramas, oldest first.
        error:       Human-readable error string, or ``None`` on success.
    """

    location_id: str
    panos: list[HistoricalPano]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """``True`` when discovery succeeded (even if zero panos were found)."""
        return self.error is None


def _build_request_url(lat: float, lng: float, radius: int) -> str:
    """Build the JSONP request URL for the GeoPhoto internal API."""
    pb = _PB_TEMPLATE.format(lat=lat, lng=lng, radius=radius)
    return f"{_GEOPHOTO_ENDPOINT}?pb={pb}&callback={_CALLBACK}"


def _parse_jsonp(text: str) -> list:
    """Strip the JSONP callback wrapper and parse the inner JSON array."""
    m = _JSONP_WRAPPER_RE.search(text)
    if not m:
        raise ValueError("Response is not valid JSONP — callback wrapper not found.")
    return json.loads(m.group(1))


def _extract_panos(data: list) -> list[HistoricalPano]:
    """Parse the GeoPhotoService nested-array response into :class:`HistoricalPano` objects.

    The response layout (protobuf-lite encoded as a JSON array):

    * ``data[1][5][0]``   — panorama cluster for this location.
    * ``cluster[3][0]``   — panorama entries, most-recent first.
    * ``cluster[8]``      — date entries ``[[pano_id], [year, month]]``;
                            shorter than the panos list — aligns from the end.

    Panos without a known date are skipped (they cannot be used for
    temporal selection or date-range filtering).
    """
    # Sentinel returned when no Street View imagery exists at this location.
    if data == [[5, "generic", "Search returned no images."]]:
        return []

    try:
        cluster = data[1][5][0]
        raw_panos = cluster[3][0]
        raw_dates = cluster[8] if len(cluster) > 8 and cluster[8] else []
    except (IndexError, TypeError) as exc:
        raise ValueError(f"Unexpected GeoPhotoService response structure: {exc}") from exc

    # Oldest pano first (response arrives most-recent first).
    raw_panos = raw_panos[::-1]
    raw_dates = raw_dates[::-1]

    dates = [f"{d[1][0]}-{d[1][1]:02d}" for d in raw_dates]

    panos: list[HistoricalPano] = []
    for i, entry in enumerate(raw_panos):
        if i >= len(dates):
            n_undated = len(raw_panos) - len(dates)
            logger.debug("Skipping %d pano(s) with no date metadata", n_undated)
            break  # all remaining entries also lack dates
        try:
            pano_id = entry[0][1]
        except (IndexError, TypeError):
            logger.debug("Skipping malformed pano entry at index %d", i)
            continue

        iso = dates[i]
        year = int(iso[:4])
        month = int(iso[5:7])
        panos.append(HistoricalPano(pano_id=pano_id, year=year, month=month, iso=iso))

    return panos


async def _query_location(
    client: httpx.AsyncClient,
    loc: Location,
    timeout: float = 15.0,
) -> DiscoveryResult:
    """Query the GeoPhoto API for all historical panoramas at *loc*.

    Network and parse errors are captured into :attr:`DiscoveryResult.error`
    rather than raised, so a single bad location does not abort a batch run.

    Args:
        client:  Shared :class:`httpx.AsyncClient`.
        loc:     Location to query (uses ``lat``, ``lng``, ``radius``).
        timeout: Per-request timeout in seconds.
    """
    url = _build_request_url(loc.lat, loc.lng, loc.radius)
    try:
        resp = await client.get(url, timeout=timeout)
        resp.raise_for_status()
        data = _parse_jsonp(resp.text)
        panos = _extract_panos(data)
    except httpx.HTTPStatusError as exc:
        err = f"HTTP {exc.response.status_code} from GeoPhotoService"
        logger.warning("%s — %s", loc.id, err)
        return DiscoveryResult(location_id=loc.id, panos=[], error=err)
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        logger.warning("%s — discovery error: %s", loc.id, err)
        return DiscoveryResult(location_id=loc.id, panos=[], error=err)

    if panos:
        if logger.isEnabledFor(logging.DEBUG):
            years = sorted({p.year for p in panos})
            logger.debug("%s — %d pano(s) found  (years: %s)", loc.id, len(panos), years)
    else:
        logger.warning("%s — no panoramas found at this location", loc.id)

    return DiscoveryResult(location_id=loc.id, panos=panos)


async def discover_locations(
    locations: list[Location],
    cfg: Config,
    *,
    on_done: Callable[[], None] = lambda: None,
) -> list[DiscoveryResult]:
    """Discover historical panoramas for every location, running in parallel.

    Args:
        locations: Locations to query.
        cfg:       Pipeline config (controls ``discovery_workers`` concurrency).
        on_done:   Callback invoked after each location completes — use this
                   to advance a progress bar.
    """
    semaphore = asyncio.Semaphore(cfg.discovery_workers)
    results: dict[str, DiscoveryResult] = {}

    async with httpx.AsyncClient(follow_redirects=True) as client:

        async def _worker(loc: Location) -> None:
            async with semaphore:
                result = await _query_location(client, loc)
            results[loc.id] = result
            on_done()

        await asyncio.gather(*(_worker(loc) for loc in locations))

    return [results[loc.id] for loc in locations]
