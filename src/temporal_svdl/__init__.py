"""temporal-svdl — Historical Google Street View image downloader.

Downloads Street View panoramas for the *same viewpoint* across multiple
points in time.  Useful for change detection, longitudinal studies, and
disaster-impact analysis.

Discovery uses Google's internal GeoPhoto API.
Downloading uses the official Street View Static API (API key required).

Quickstart::

    from temporal_svdl import download

    # Single coordinate — specific years
    report = download(lat=43.6629, lng=-79.3957, target_years=[2015, 2020, 2023])

    # Single coordinate — every available date
    report = download(lat=43.6629, lng=-79.3957, all_dates=True)

    # From a JSON batch file
    report = download(json_file="locations.json")

    # Async
    import asyncio
    report = asyncio.run(adownload(lat=43.66, lng=-79.39, target_years=[2015, 2023]))

Set ``GOOGLE_MAPS_API_KEY`` in ``.env`` (or your shell).
The key must have **Street View Static API** enabled.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterable, Optional, Union

logging.getLogger(__name__).addHandler(logging.NullHandler())

from .config import Config, CameraDefaults, Location, get_api_key, get_signing_secret
from .discovery import DiscoveryResult, HistoricalPano, discover_locations
from .downloader import DownloadJob, DownloadResult
from .loaders import (
    load_locations_json,
    load_urls_file,
    parse_google_maps_url,
)
from .manifest import Manifest
from .pipeline import Report, run
from .selection import filter_by_date_range, select_panos_for_years

try:
    __version__ = version("temporal-svdl")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    # Config
    "Config",
    "CameraDefaults",
    "Location",
    # Pipeline
    "Report",
    "Manifest",
    # Loaders
    "parse_google_maps_url",
    "load_locations_json",
    "load_urls_file",
    # Discovery
    "DiscoveryResult",
    "HistoricalPano",
    "discover_locations",
    # Download
    "DownloadJob",
    "DownloadResult",
    # Selection
    "filter_by_date_range",
    "select_panos_for_years",
    # Entry points
    "download",
    "adownload",
    "list_panos",
]

PathLike = Union[str, Path]


def _build_locations(
    *,
    locations: Optional[list[Location]],
    json_file: Optional[PathLike],
    lat: Optional[float],
    lng: Optional[float],
    url: Optional[str],
    urls_file: Optional[PathLike],
    target_years: Optional[Iterable[int]],
    all_dates: bool,
    year_from: Optional[int],
    year_to: Optional[int],
) -> list[Location]:
    """Collapse the various input modes into a single list of Locations."""
    n_provided = sum(
        [
            locations is not None,
            json_file is not None,
            lat is not None and lng is not None,
            url is not None,
            urls_file is not None,
        ]
    )

    if n_provided == 0:
        raise ValueError("Provide one of: locations=, json_file=, lat= + lng=, url=, urls_file=")
    if n_provided > 1:
        raise ValueError("Provide only one input mode at a time.")

    years = list(target_years or [])
    tmp_kwargs = {
        "target_years": years,
        "all_dates": all_dates,
        "year_from": year_from,
        "year_to": year_to,
    }

    if locations is not None:
        return list(locations)

    if json_file is not None:
        return load_locations_json(json_file)

    if lat is not None and lng is not None:
        return [Location(lat=lat, lng=lng, **tmp_kwargs)]

    if url is not None:
        return [parse_google_maps_url(url, **tmp_kwargs)]

    if urls_file is not None:
        return [parse_google_maps_url(u, **tmp_kwargs) for u in load_urls_file(urls_file)]

    raise AssertionError("unreachable")


# Public API


async def adownload(
    *,
    # Input modes (choose one)
    locations: Optional[list[Location]] = None,
    json_file: Optional[PathLike] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    url: Optional[str] = None,
    urls_file: Optional[PathLike] = None,
    # Temporal selection
    target_years: Optional[Iterable[int]] = None,
    all_dates: bool = False,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    # Pipeline control
    config: Optional[Config] = None,
    confirm: bool = True,
    discover_only: bool = False,
    download_only: bool = False,
    refresh_discovery: bool = False,
    show_progress: bool = True,
) -> Report:
    """Async pipeline entry point.  Choose exactly one input mode.

    Input modes:
        locations    — list[Location]
        json_file    — path to a JSON array of locations
        lat + lng    — single coordinate
        url          — a Google Maps URL
        urls_file    — text file with one URL per line

    Temporal selection (applied to lat/lng, url, urls_file):
        target_years — list of years; closest pano per year is downloaded.
        all_dates    — download every available historical pano.
        year_from    — ignore panos captured before this year.
        year_to      — ignore panos captured after this year.

    Args:
        config:            Pipeline config.  CameraDefaults are used when omitted.
        confirm:           Prompt before downloading (pass ``False`` to skip).
        discover_only:     Stop after discovery; do not download images.
        download_only:     Skip discovery and use the cached pano list.
        refresh_discovery: Re-query all locations, ignoring the cache.
        show_progress:     Show Rich progress bars.
    """
    cfg = config or Config()

    locs = _build_locations(
        locations=locations,
        json_file=json_file,
        lat=lat,
        lng=lng,
        url=url,
        urls_file=urls_file,
        target_years=target_years,
        all_dates=all_dates,
        year_from=year_from,
        year_to=year_to,
    )
    return await run(
        cfg,
        locs,
        api_key=get_api_key(),
        signing_secret=get_signing_secret(),
        discover_only=discover_only,
        download_only=download_only,
        refresh_discovery=refresh_discovery,
        confirm=confirm,
        show_progress=show_progress,
    )


def download(**kwargs) -> Report:
    """Synchronous wrapper around :func:`adownload`.  Accepts the same arguments."""
    try:
        # Check if there is an active running event loop (e.g., Jupyter)
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop is running; safe to use standard asyncio.run()
        return asyncio.run(adownload(**kwargs))
    
    # If a loop IS running, execute the async function in a separate thread
    # and block until it returns the result.
    with ThreadPoolExecutor() as executor:
        future = executor.submit(lambda: asyncio.run(adownload(**kwargs)))
        return future.result()

    


async def list_panos(
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    url: Optional[str] = None,
    json_file: Optional[PathLike] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    config: Optional[Config] = None,
) -> dict[str, list[HistoricalPano]]:
    """Discover and return all available historical panoramas without downloading.

    Useful for inspecting what dates Google holds for a location before
    committing to a full download run.

    Args:
        lat, lng:  Single coordinate (provide either lat+lng, url, or json_file).
        url:       A Google Maps URL.
        json_file: Path to a JSON batch file.
        year_from: Filter — exclude panos before this year.
        year_to:   Filter — exclude panos after this year.
        config:    Optional pipeline config.
    """
    cfg = config or Config()

    if json_file:
        locations = load_locations_json(json_file)
    elif url:
        locations = [parse_google_maps_url(url)]
    elif lat is not None and lng is not None:
        locations = [Location(lat=lat, lng=lng)]
    else:
        raise ValueError("Provide lat+lng, url, or json_file.")

    locations = [loc.fill(cfg.camera_defaults) for loc in locations]
    results = await discover_locations(locations, cfg)

    return {
        r.location_id: filter_by_date_range(r.panos, year_from, year_to) for r in results if r.ok
    }
