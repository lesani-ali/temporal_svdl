from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .discovery import HistoricalPano
from .downloader import DownloadJob, DownloadResult

_MANIFEST_FIELDS = [
    "location_id",
    "target_year",
    "pano_id",
    "pano_iso",
    "heading",
    "pitch",
    "fov",
    "size",
    "out_path",
    "bytes",
    "status",
    "error",
    "ts_utc",
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Manifest:
    """Append-only CSV that records every download attempt.

    Re-running the pipeline skips any job already marked ``ok``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._done: set[tuple] = set()
        if path.exists():
            self._load_existing()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=_MANIFEST_FIELDS).writeheader()

    @staticmethod
    def _job_key(job: DownloadJob) -> tuple:
        return (
            job.location_id,
            job.target_year,
            job.pano_id,
            job.heading,
            job.pitch,
            job.fov,
            job.size,
        )

    def _load_existing(self) -> None:
        with self.path.open("r", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("status") != "ok":
                    continue
                try:
                    self._done.add(
                        (
                            row["location_id"],
                            int(row["target_year"]),
                            row["pano_id"],
                            float(row["heading"]),
                            float(row["pitch"]),
                            float(row["fov"]),
                            row["size"],
                        )
                    )
                except (KeyError, ValueError):
                    # Skip malformed rows — don't abort a resume run over corruption.
                    continue

    def is_done(self, job: DownloadJob) -> bool:
        """Return ``True`` if this job completed successfully in a previous run."""
        return self._job_key(job) in self._done

    def record(self, result: DownloadResult) -> None:
        """Append one download result to the CSV."""
        row = {
            "location_id": result.job.location_id,
            "target_year": result.job.target_year,
            "pano_id": result.job.pano_id,
            "pano_iso": result.job.pano_iso,
            "heading": result.job.heading,
            "pitch": result.job.pitch,
            "fov": result.job.fov,
            "size": result.job.size,
            "out_path": str(result.job.out_path),
            "bytes": result.bytes_written,
            "status": "ok" if result.ok else "fail",
            "error": result.error or "",
            "ts_utc": _utcnow(),
        }
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=_MANIFEST_FIELDS).writerow(row)
            if result.ok:
                self._done.add(self._job_key(result.job))


def _load_pano_cache(path: Path) -> dict[str, list[HistoricalPano]]:
    """Load previously discovered panos from path."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        content = fh.read().strip()
    if not content:
        return {}
    raw = json.loads(content)
    return {
        entry["location_id"]: [HistoricalPano(**p) for p in entry.get("panos", [])] for entry in raw
    }


def _save_pano_cache(path: Path, panos_by_loc: dict[str, list[HistoricalPano]]) -> None:
    """Persist pano discovery results to path as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {"location_id": loc_id, "panos": [asdict(p) for p in panos]}
        for loc_id, panos in panos_by_loc.items()
    ]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
