from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlencode, urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Config
from .logging import get_logger

logger = get_logger(__name__)

_STATIC_API_URL = "https://maps.googleapis.com/maps/api/streetview"

# Google returns a ~6 KB grey "no imagery" placeholder for missing panos.
# Any genuine photograph is well above this threshold.
_MIN_IMAGE_BYTES = 5_000


class _RetryableError(Exception):
    """Raised for retriable HTTP status codes (429, 5xx); never raised for permanent errors."""


@dataclass(frozen=True)
class DownloadJob:
    """Everything needed to fetch one Street View image from the Static API.

    Attributes:
        location_id: ID of the location.
        pano_id:     Google panorama identifier.
        target_year: Year this pano was chosen for.
        pano_iso:    Actual capture date as ``'YYYY-MM'``.
        heading:     Camera heading in degrees.
        pitch:       Camera pitch in degrees.
        fov:         Field of view in degrees.
        size:        Image dimensions as ``'WIDTHxHEIGHT'``.
        out_path:    Filesystem path where the JPEG will be written.
    """

    location_id: str
    pano_id: str
    target_year: int
    pano_iso: str  # "YYYY-MM"
    heading: float
    pitch: float
    fov: float
    size: str
    out_path: Path


@dataclass
class DownloadResult:
    """Outcome of a single download attempt."""

    job: DownloadJob
    ok: bool
    bytes_written: int = 0
    error: Optional[str] = None


def _sign_url(url: str, secret: str) -> str:
    """Append an HMAC-SHA1 signature required when URL signing is enforced."""
    parsed = urlparse(url)
    message = (parsed.path + "?" + parsed.query).encode("utf-8")
    key = base64.urlsafe_b64decode(secret)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    sig = base64.urlsafe_b64encode(digest).decode("utf-8")
    return f"{url}&signature={sig}"


def build_download_url(
    job: DownloadJob,
    api_key: str,
    signing_secret: Optional[str],
) -> str:
    """Build the Street View Static API request URL for *job*."""
    params = {
        "size": job.size,
        "pano": job.pano_id,
        "heading": f"{job.heading:g}",
        "pitch": f"{job.pitch:g}",
        "fov": f"{job.fov:g}",
        "key": api_key,
    }
    url = f"{_STATIC_API_URL}?{urlencode(params)}"
    return _sign_url(url, signing_secret) if signing_secret else url


async def _fetch_image(
    client: httpx.AsyncClient,
    job: DownloadJob,
    api_key: str,
    signing_secret: Optional[str],
    cfg: Config,
) -> DownloadResult:
    """Download one image, write it atomically to disk, and return a result."""
    url = build_download_url(job, api_key, signing_secret)

    async def _attempt() -> bytes:
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.content
        if resp.status_code == 403:
            raise RuntimeError(
                "HTTP 403 Forbidden — verify that 'Street View Static API' "
                "is enabled for your Google Maps API key."
            )
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            raise _RetryableError(f"HTTP {resp.status_code}")
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(cfg.max_retries),
            wait=wait_exponential(
                multiplier=cfg.initial_backoff_seconds,
                max=cfg.max_backoff_seconds,
            ),
            retry=retry_if_exception_type((_RetryableError, httpx.TransportError)),
            reraise=True,
        ):
            with attempt:
                content = await _attempt()

    except (RetryError, Exception, httpx.TransportError, RuntimeError) as exc:
        logger.warning("FAIL  %s  %s  — %s", job.location_id, job.pano_iso, exc)
        return DownloadResult(job=job, ok=False, error=str(exc))

    if len(content) < _MIN_IMAGE_BYTES:
        msg = f"response only {len(content)} B — likely a 'no imagery' placeholder"
        logger.warning("SKIP  %s  %s  — %s", job.location_id, job.pano_iso, msg)
        return DownloadResult(job=job, ok=False, error=msg)

    # Atomic write: write to <name>.part, then rename to the final path.
    job.out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = job.out_path.with_suffix(".jpg.part")
    tmp.write_bytes(content)
    tmp.replace(job.out_path)

    logger.debug("OK    %s  %s  → %s", job.location_id, job.pano_iso, job.out_path.name)
    return DownloadResult(job=job, ok=True, bytes_written=len(content))


async def download_all(
    jobs: list[DownloadJob],
    cfg: Config,
    api_key: str,
    signing_secret: Optional[str],
    *,
    on_result: Callable[[DownloadResult], None] = lambda _: None,
) -> list[DownloadResult]:
    """Download all jobs concurrently, capped at ``cfg.download_workers`` in flight.

    Args:
        jobs:           Jobs to execute.
        cfg:            Pipeline config (concurrency, retry settings).
        api_key:        Google Maps API key.
        signing_secret: Optional URL-signing secret.
        on_result:      Callback invoked after each job completes.  Use this
                        to write to the manifest or advance a progress bar.
    """
    semaphore = asyncio.Semaphore(cfg.download_workers)
    results: list[DownloadResult] = []

    timeout = httpx.Timeout(30.0, connect=10.0)
    limits = httpx.Limits(
        max_connections=cfg.download_workers * 2,
        max_keepalive_connections=cfg.download_workers,
    )

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:

        async def _worker(job: DownloadJob) -> None:
            async with semaphore:
                result = await _fetch_image(client, job, api_key, signing_secret, cfg)
            results.append(result)
            on_result(result)

        await asyncio.gather(*(_worker(job) for job in jobs))

    return results
