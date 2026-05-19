from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from .config import Config, Location
from .discovery import DiscoveryResult, HistoricalPano, discover_locations
from .downloader import DownloadJob, DownloadResult, download_all
from .logging import get_console, get_logger
from .manifest import Manifest, _load_pano_cache, _save_pano_cache
from .selection import filter_by_date_range, select_panos_for_years

logger = get_logger(__name__)
console = get_console()


def _sanitize(s: str) -> str:
    """Replace characters not safe for filenames with underscores."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)


def _output_path(output_dir: Path, loc: Location, target_year: int, pano: HistoricalPano) -> Path:
    """Build the output file path for one download job."""
    filename = (
        f"{pano.iso}_{_sanitize(pano.pano_id)[:24]}"
        f"_h{loc.heading:g}_p{loc.pitch:g}_f{loc.fov:g}"
        f"_y{target_year}.jpg"
    )
    return output_dir / loc.id / filename


def _plan_jobs(
    cfg: Config,
    locations: list[Location],
    panos_by_loc: dict[str, list[HistoricalPano]],
    manifest: Manifest,
) -> tuple[list[DownloadJob], int]:
    """Build the list of jobs to run, skipping those already in the manifest."""
    jobs: list[DownloadJob] = []
    n_skipped = 0

    for loc in locations:
        discovered = panos_by_loc.get(loc.id, [])
        candidates = filter_by_date_range(discovered, loc.year_from, loc.year_to)

        if loc.all_dates:
            # One job per unique pano
            selections: list[tuple[int, HistoricalPano]] = [(p.year, p) for p in candidates]
        elif loc.target_years:
            selections = list(select_panos_for_years(candidates, loc.target_years).items())
        else:
            # No temporal selection specified: download only the most recent pano.
            if candidates:
                latest = max(candidates, key=lambda p: (p.year, p.month))
                selections = [(latest.year, latest)]
            else:
                selections = []

        for target_year, pano in selections:
            job = DownloadJob(
                location_id=loc.id,
                pano_id=pano.pano_id,
                target_year=target_year,
                pano_iso=pano.iso,
                heading=loc.heading,
                pitch=loc.pitch,
                fov=loc.fov,
                size=loc.size,
                out_path=_output_path(cfg.output_dir, loc, target_year, pano),
            )
            if manifest.is_done(job):
                n_skipped += 1
            else:
                jobs.append(job)

    return jobs, n_skipped


def _print_discovery_summary(
    locations: list[Location],
    panos_by_loc: dict[str, list[HistoricalPano]],
) -> None:
    """Print a Rich table summarising what was discovered."""
    table = Table(title="Discovery Results", show_lines=False)
    table.add_column("Location", style="cyan", no_wrap=True)
    table.add_column("Panos", justify="right")
    table.add_column("Date range", style="dim")
    table.add_column("Status", justify="center")

    for loc in locations:
        panos = panos_by_loc.get(loc.id, [])
        if panos:
            years = sorted({p.year for p in panos})
            date_range = f"{years[0]} – {years[-1]}" if len(years) > 1 else str(years[0])
            status = "[green]✓[/]"
        else:
            date_range = "—"
            status = "[red]✗ no imagery[/]"
        table.add_row(loc.id, str(len(panos)), date_range, status)

    console.print(table)


def _print_download_summary(report: "Report") -> None:
    """Print a Rich summary panel after all downloads complete."""
    ok = report.downloads_ok
    failed = report.downloads_failed
    color = "green" if failed == 0 else "yellow" if ok > 0 else "red"
    console.print(
        f"\n[bold {color}]Download complete[/] — "
        f"[green]{ok} ok[/]  [red]{failed} failed[/]  "
        f"[dim]{report.n_skipped} skipped (already done)[/]\n"
        f"Manifest: [dim]{report.cfg.manifest_path}[/]"
    )


@dataclass
class Report:
    """Result object returned by :func:`run`.

    Attributes:
        locations:    Locations that were processed.
        cfg:          Pipeline configuration used for this run.
        panos_by_loc: Discovered panos keyed by ``location_id``.
        n_planned:    Total number of download jobs planned.
        n_skipped:    Jobs skipped because they were already in the manifest.
        downloads:    Individual download outcomes (in completion order).
    """

    locations: list[Location]
    cfg: Config
    panos_by_loc: dict[str, list[HistoricalPano]] = field(default_factory=dict)
    n_planned: int = 0
    n_skipped: int = 0
    downloads: list[DownloadResult] = field(default_factory=list)

    @property
    def downloads_ok(self) -> int:
        """Number of images downloaded successfully in this run."""
        return sum(1 for r in self.downloads if r.ok)

    @property
    def downloads_failed(self) -> int:
        """Number of download attempts that ended in a permanent failure."""
        return sum(1 for r in self.downloads if not r.ok)


async def run(
    cfg: Config,
    locations: list[Location],
    *,
    api_key: str,
    signing_secret: Optional[str] = None,
    discover_only: bool = False,
    download_only: bool = False,
    refresh_discovery: bool = False,
    confirm: bool = True,
    show_progress: bool = True,
) -> Report:
    """Run the full pipeline (discovery → planning → download).

    Args:
        cfg:               Pipeline configuration.
        locations:         Locations to process (camera defaults already filled).
        api_key:           Google Maps API key (Street View Static API).
        signing_secret:    Optional URL-signing secret.
        discover_only:     Stop after phase 1 (discovery).
        download_only:     Skip phase 1; use the cached pano discovery file.
        refresh_discovery: Ignore the pano cache and re-query all locations.
        confirm:           Prompt the user for confirmation before downloading.
        show_progress:     Render Rich progress bars.
    """
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    locations = [loc.fill(cfg.defaults) for loc in locations]
    report = Report(locations=locations, cfg=cfg)

    # Phase 1: discovery
    if download_only:
        report.panos_by_loc = _load_pano_cache(cfg.panos_cache_path)
        if not report.panos_by_loc:
            raise RuntimeError(
                f"--download-only requires a pano cache from a previous run.\n"
                f"Expected: {cfg.panos_cache_path}"
            )
        logger.info(
            "Loaded %d cached location(s) from %s",
            len(report.panos_by_loc),
            cfg.panos_cache_path,
        )
    else:
        cached = {} if refresh_discovery else _load_pano_cache(cfg.panos_cache_path)
        pending = [loc for loc in locations if loc.id not in cached]
        if cached:
            logger.info("Using cached discovery for %d location(s).", len(cached))

        fresh: list[DiscoveryResult] = []
        if pending:
            fresh = await _run_discovery(pending, cfg, show_progress)

        merged = {**cached, **{r.location_id: r.panos for r in fresh}}
        _save_pano_cache(cfg.panos_cache_path, merged)
        report.panos_by_loc = merged

    _print_discovery_summary(locations, report.panos_by_loc)

    if discover_only:
        return report

    # Phase 2: plan
    manifest = Manifest(cfg.manifest_path)
    jobs, n_skipped = _plan_jobs(cfg, locations, report.panos_by_loc, manifest)
    report.n_planned = len(jobs)
    report.n_skipped = n_skipped

    console.print(
        f"\n[bold]Planned:[/] {len(jobs):,} image(s)"
        + (f"  [dim]({n_skipped:,} already done, skipped)[/]" if n_skipped else "")
    )

    if not jobs:
        console.print("[green]Nothing new to download.[/]")
        return report

    if confirm:
        answer = input(f"Download {len(jobs):,} image(s)? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            console.print("[yellow]Aborted.[/]")
            return report

    # Phase 3: download
    report.downloads = await _run_downloads(
        jobs, cfg, api_key, signing_secret, manifest, show_progress
    )
    _print_download_summary(report)
    return report


def _progress_bar(label: str) -> Progress:
    return Progress(
        TextColumn(f"[bold]{label}[/]"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )


async def _run_discovery(
    locations: list[Location],
    cfg: Config,
    show_progress: bool,
) -> list[DiscoveryResult]:
    if not show_progress:
        return await discover_locations(locations, cfg)
    with _progress_bar("Discovering") as progress:
        tid = progress.add_task("discover", total=len(locations))
        return await discover_locations(
            locations,
            cfg,
            on_done=lambda: progress.update(tid, advance=1),
        )


async def _run_downloads(
    jobs: list[DownloadJob],
    cfg: Config,
    api_key: str,
    signing_secret: Optional[str],
    manifest: Manifest,
    show_progress: bool,
) -> list[DownloadResult]:
    def on_result(res: DownloadResult) -> None:
        manifest.record(res)

    if not show_progress:
        return await download_all(jobs, cfg, api_key, signing_secret, on_result=on_result)

    with _progress_bar("Downloading") as progress:
        tid = progress.add_task("download", total=len(jobs))

        def on_result_with_progress(res: DownloadResult) -> None:
            on_result(res)
            progress.update(tid, advance=1)

        return await download_all(
            jobs,
            cfg,
            api_key,
            signing_secret,
            on_result=on_result_with_progress,
        )


__all__ = ["Report", "run"]
