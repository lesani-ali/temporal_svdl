from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click
from rich.table import Table

from . import adownload
from .config import Config, Location
from .discovery import discover_locations
from .loaders import (
    load_locations_json,
    load_urls_file,
    parse_google_maps_url,
)
from .logging import get_console, get_logger, setup_logger
from .selection import filter_by_date_range

logger = get_logger(__name__)
console = get_console()


def _load_config(config_path: Optional[Path], output_dir: Optional[Path] = None) -> Config:
    cfg = Config.from_yaml(config_path) if config_path else Config()
    if output_dir:
        cfg = cfg.model_copy(update={"output_dir": output_dir})
    return cfg


def _run_pipeline(
    locations: list[Location],
    *,
    config_path: Optional[Path],
    output_dir: Optional[Path],
    auto_yes: bool,
    discover_only: bool,
    download_only: bool,
    refresh_discovery: bool,
) -> None:
    """Build config and run the async pipeline."""
    cfg = _load_config(config_path, output_dir)
    setup_logger(cfg.package_name, cfg.log_level, cfg.log_file)
    asyncio.run(
        adownload(
            locations=locations,
            config=cfg,
            confirm=not auto_yes,
            discover_only=discover_only,
            download_only=download_only,
            refresh_discovery=refresh_discovery,
        )
    )


def _run_options(f):
    """Decorator that attaches common pipeline options to a command."""
    options = [
        click.option(
            "--config",
            "-c",
            "config_path",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="YAML config file.",
        ),
        click.option(
            "--output",
            "-o",
            "output_dir",
            type=click.Path(file_okay=False, path_type=Path),
            help="Override output directory.",
        ),
        click.option(
            "--yes",
            "auto_yes",
            is_flag=True,
            help="Skip the confirmation prompt before downloading.",
        ),
        click.option(
            "--discover-only",
            is_flag=True,
            help="Run pano discovery only — do not download images.",
        ),
        click.option(
            "--download-only",
            is_flag=True,
            help="Skip discovery — reuse the cached pano list from a previous run.",
        ),
        click.option(
            "--refresh-discovery",
            is_flag=True,
            help="Ignore the pano cache and re-query all locations.",
        ),
    ]
    for opt in reversed(options):
        f = opt(f)
    return f


def _temporal_options(f):
    """Decorator that attaches temporal-selection options (years / all-dates)."""
    options = [
        click.option(
            "--years",
            "-y",
            help="Comma-separated target years, e.g. 2015,2020,2023.",
        ),
        click.option(
            "--all-dates",
            is_flag=True,
            help="Download every available historical panorama.",
        ),
        click.option(
            "--year-from",
            type=int,
            default=None,
            help="Exclude panoramas captured before this year.",
        ),
        click.option(
            "--year-to",
            type=int,
            default=None,
            help="Exclude panoramas captured after this year.",
        ),
    ]
    for opt in reversed(options):
        f = opt(f)
    return f


def _parse_years(years_str: Optional[str]) -> list[int]:
    """Parse years string and return a list of target years."""
    if not years_str:
        return []
    return [int(y.strip()) for y in years_str.split(",") if y.strip()]


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="temporal-svdl")
def cli() -> None:
    """Historical Google Street View image downloader."""
    pass


@cli.command()
@click.option(
    "--json-file",
    "-j",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="JSON array of locations. Each entry carries its own target_years or all_dates.",
)
@_run_options
def batch(json_file: Path, **kwargs) -> None:
    """Download a batch of locations defined in a JSON file."""
    locations = load_locations_json(json_file)
    _run_pipeline(locations, **kwargs)


@cli.command()
@click.option("--lat", type=float, required=True, help="Latitude  (-90 … 90).")
@click.option("--lng", type=float, required=True, help="Longitude (-180 … 180).")
@click.option(
    "--heading",
    "heading_str",
    default=None,
    help="Camera heading in degrees (0–360). Omit to compute automatically from the target location.",
)
@_temporal_options
@_run_options
def point(
    lat: float,
    lng: float,
    heading_str: Optional[str],
    years: Optional[str],
    all_dates: bool,
    year_from: Optional[int],
    year_to: Optional[int],
    **kwargs,
) -> None:
    """Download Street View images for a single coordinate.

    Heading defaults to automatic: the camera is aimed toward the target
    location from the Street View camera position.

    Examples:
      temporal-svdl point --lat 43.66 --lng -79.39 --years 2015,2020,2023
      temporal-svdl point --lat 43.66 --lng -79.39 --all-dates
      temporal-svdl point --lat 43.66 --lng -79.39 --heading 90 --all-dates
    """
    heading = float(heading_str) if heading_str is not None else None
    target_years = _parse_years(years)
    location = Location(
        lat=lat,
        lng=lng,
        heading=heading,
        target_years=target_years,
        all_dates=all_dates,
        year_from=year_from,
        year_to=year_to,
    )
    _run_pipeline([location], **kwargs)


@cli.command()
@click.option(
    "--url",
    "-u",
    "url_str",
    required=True,
    help="A Google Maps URL (place, Street View, or short link).",
)
@_temporal_options
@_run_options
def url(
    url_str: str,
    years: Optional[str],
    all_dates: bool,
    year_from: Optional[int],
    year_to: Optional[int],
    **kwargs,
) -> None:
    """Download Street View images for a single Google Maps URL.

    Camera parameters (heading, pitch, FOV) are extracted from Street View
    URLs automatically.

    Examples:
      temporal-svdl url --url "https://maps.google.com/@43.66,-79.39,17z" --years 2015,2023
      temporal-svdl url --url "https://maps.google.com/@43.66,-79.39,17z" --all-dates
    """
    target_years = _parse_years(years)
    location = parse_google_maps_url(
        url_str,
        target_years=target_years,
        all_dates=all_dates,
        year_from=year_from,
        year_to=year_to,
    )
    _run_pipeline([location], **kwargs)


@cli.command()
@click.option(
    "--urls-file",
    "-f",
    "urls_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Text file with one Google Maps URL per line (# comments and blank lines ignored).",
)
@_temporal_options
@_run_options
def urls(
    urls_file: Path,
    years: Optional[str],
    all_dates: bool,
    year_from: Optional[int],
    year_to: Optional[int],
    **kwargs,
) -> None:
    """Download Street View images for many Google Maps URLs from a file."""
    target_years = _parse_years(years)
    locations = [
        parse_google_maps_url(
            u,
            target_years=target_years,
            all_dates=all_dates,
            year_from=year_from,
            year_to=year_to,
        )
        for u in load_urls_file(urls_file)
    ]
    _run_pipeline(locations, **kwargs)


@cli.command(name="list")
@click.option("--lat", type=float, default=None, help="Latitude  (-90 … 90).")
@click.option("--lng", type=float, default=None, help="Longitude (-180 … 180).")
@click.option(
    "--url",
    "-u",
    "url_str",
    default=None,
    help="A Google Maps URL instead of lat/lng.",
)
@click.option(
    "--json-file",
    "-j",
    "json_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="List panos for all locations in a JSON file.",
)
@click.option("--year-from", type=int, default=None, help="Filter: show panos from this year.")
@click.option("--year-to", type=int, default=None, help="Filter: show panos up to this year.")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="YAML config file.",
)
def list_panos(
    lat: Optional[float],
    lng: Optional[float],
    url_str: Optional[str],
    json_file: Optional[Path],
    year_from: Optional[int],
    year_to: Optional[int],
    config_path: Optional[Path],
) -> None:
    """List all available historical panoramas for a location — no download.

    Use this to explore what dates Google has for a location before deciding
    which years to download.

    Examples:
      temporal-svdl list --lat 43.66 --lng -79.39
      temporal-svdl list --url "https://maps.google.com/@43.66,-79.39,17z"
      temporal-svdl list --json-file locations.json --year-from 2015
    """
    cfg = _load_config(config_path)
    setup_logger(cfg.package_name, "WARNING")  # suppress INFO noise during list

    if json_file:
        locations = load_locations_json(json_file)
    elif url_str:
        locations = [parse_google_maps_url(url_str)]
    elif lat is not None and lng is not None:
        locations = [Location(lat=lat, lng=lng)]
    else:
        raise click.UsageError("Provide --lat/--lng, --url, or --json-file.")

    locations = [loc.fill(cfg.defaults) for loc in locations]

    results = asyncio.run(discover_locations(locations, cfg))

    for loc, result in zip(locations, results):
        if result.error:
            console.print(f"[red]✗  {loc.id}  —  {result.error}[/]")
            continue

        panos = filter_by_date_range(result.panos, year_from, year_to)
        if not panos:
            console.print(f"[yellow]✗  {loc.id}  —  no panos in range[/]")
            continue

        table = Table(
            title=f"{loc.id}  ({loc.lat}, {loc.lng})",
            show_lines=False,
        )
        table.add_column("#", justify="right", style="dim")
        table.add_column("Date", style="cyan")
        table.add_column("Pano ID", style="dim")
        table.add_column("Heading", justify="right")

        heading_display = "—" if loc.heading is None else f"{loc.heading:g}°"
        for i, pano in enumerate(sorted(panos, key=lambda p: p.iso), start=1):
            table.add_row(str(i), pano.iso, pano.pano_id, heading_display)

        console.print(table)
        console.print(f"  [dim]Total: {len(panos)} panorama(s)[/]\n")


if __name__ == "__main__":
    cli()
