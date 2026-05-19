from pathlib import Path

from temporal_svdl.config import Config, Location
from temporal_svdl.discovery import HistoricalPano
from temporal_svdl.downloader import DownloadJob, DownloadResult
from temporal_svdl.manifest import Manifest
from temporal_svdl.pipeline import Report, _output_path, _plan_jobs, _sanitize


# helpers
def _make_loc(
    *,
    id: str = "loc1",
    all_dates: bool = False,
    target_years: list[int] | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
) -> Location:
    return Location(
        id=id,
        lat=43.0,
        lng=-79.0,
        all_dates=all_dates,
        target_years=target_years or [],
        year_from=year_from,
        year_to=year_to,
        heading=0.0,
        pitch=0.0,
        fov=90.0,
        size="640x640",
        radius=50,
    )


def _make_pano(pano_id: str, year: int, month: int = 6) -> HistoricalPano:
    return HistoricalPano(pano_id=pano_id, year=year, month=month, iso=f"{year}-{month:02d}")


def _record_done(manifest: Manifest, tmp_path: Path, loc_id: str, pano_id: str, year: int) -> None:
    job = DownloadJob(
        location_id=loc_id,
        pano_id=pano_id,
        target_year=year,
        pano_iso=f"{year}-06",
        heading=0.0,
        pitch=0.0,
        fov=90.0,
        size="640x640",
        out_path=tmp_path / loc_id / f"{pano_id}.jpg",
    )
    manifest.record(DownloadResult(job=job, ok=True, bytes_written=10_000))


# _sanitize
class TestSanitize:
    def test_alphanumeric_unchanged(self):
        assert _sanitize("abc123") == "abc123"

    def test_hyphens_and_underscores_unchanged(self):
        assert _sanitize("abc-123_OK") == "abc-123_OK"

    def test_slash_replaced(self):
        assert _sanitize("a/b") == "a_b"

    def test_dot_replaced(self):
        assert _sanitize("a.b") == "a_b"

    def test_space_replaced(self):
        assert _sanitize("hello world") == "hello_world"

    def test_empty_string(self):
        assert _sanitize("") == ""


# _output_path
class TestOutputPath:
    def test_parent_directory_is_location_folder(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc()
        pano = _make_pano("PanoXYZ", 2020)
        path = _output_path(cfg.output_dir, loc, 2020, pano)
        assert path.parent == tmp_path / "loc1"

    def test_filename_contains_pano_iso(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc()
        pano = _make_pano("abc", 2020, 5)
        path = _output_path(cfg.output_dir, loc, 2020, pano)
        assert "2020-05" in path.name

    def test_filename_contains_target_year(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc()
        pano = _make_pano("abc", 2019)
        path = _output_path(cfg.output_dir, loc, 2020, pano)
        assert "y2020" in path.name

    def test_filename_contains_camera_params(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc()
        pano = _make_pano("abc", 2020)
        path = _output_path(cfg.output_dir, loc, 2020, pano)
        assert "h0" in path.name
        assert "p0" in path.name
        assert "f90" in path.name

    def test_long_pano_id_is_truncated(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc()
        pano = _make_pano("A" * 50, 2020)
        path = _output_path(cfg.output_dir, loc, 2020, pano)
        # pano_id part should be at most 24 chars
        assert "A" * 25 not in path.name


# _plan_jobs
class TestPlanJobs:
    def test_target_years_creates_one_job_per_year(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(target_years=[2015, 2020])
        panos = [_make_pano("a", 2015), _make_pano("b", 2020)]
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, n_skipped = _plan_jobs(cfg, [loc], {"loc1": panos}, manifest)
        assert len(jobs) == 2
        assert n_skipped == 0

    def test_all_dates_creates_one_job_per_pano(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(all_dates=True)
        panos = [
            _make_pano("a", 2019, 3),
            _make_pano("b", 2019, 9),
            _make_pano("c", 2021, 6),
        ]
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, n_skipped = _plan_jobs(cfg, [loc], {"loc1": panos}, manifest)
        assert len(jobs) == 3
        assert n_skipped == 0

    def test_already_done_jobs_are_skipped(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(target_years=[2015, 2020])
        panos = [_make_pano("p15", 2015), _make_pano("p20", 2020)]
        manifest = Manifest(tmp_path / "manifest.csv")
        _record_done(manifest, tmp_path, "loc1", "p15", 2015)
        jobs, n_skipped = _plan_jobs(cfg, [loc], {"loc1": panos}, manifest)
        assert len(jobs) == 1
        assert n_skipped == 1
        assert jobs[0].pano_id == "p20"

    def test_all_jobs_already_done(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(target_years=[2020])
        panos = [_make_pano("p1", 2020)]
        manifest = Manifest(tmp_path / "manifest.csv")
        _record_done(manifest, tmp_path, "loc1", "p1", 2020)
        jobs, n_skipped = _plan_jobs(cfg, [loc], {"loc1": panos}, manifest)
        assert len(jobs) == 0
        assert n_skipped == 1

    def test_year_range_filter_applied(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(all_dates=True, year_from=2015, year_to=2020)
        panos = [
            _make_pano("old", 2012),
            _make_pano("mid", 2017),
            _make_pano("new", 2023),
        ]
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, _ = _plan_jobs(cfg, [loc], {"loc1": panos}, manifest)
        assert len(jobs) == 1
        assert jobs[0].pano_id == "mid"

    def test_no_temporal_selection_downloads_latest_pano(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(all_dates=False, target_years=[])  # no temporal → latest
        panos = [
            _make_pano("old", 2015, 3),
            _make_pano("mid", 2019, 6),
            _make_pano("newest", 2023, 11),
        ]
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, _ = _plan_jobs(cfg, [loc], {"loc1": panos}, manifest)
        assert len(jobs) == 1
        assert jobs[0].pano_id == "newest"

    def test_no_temporal_selection_empty_candidates_creates_no_jobs(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(all_dates=False, target_years=[])
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, _ = _plan_jobs(cfg, [loc], {"loc1": []}, manifest)
        assert len(jobs) == 0

    def test_missing_location_in_cache_creates_no_jobs(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(target_years=[2020])
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, n_skipped = _plan_jobs(cfg, [loc], {}, manifest)
        assert len(jobs) == 0
        assert n_skipped == 0

    def test_multiple_locations(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc1 = _make_loc(id="a", target_years=[2020])
        loc2 = _make_loc(id="b", target_years=[2020])
        panos = {"a": [_make_pano("p1", 2020)], "b": [_make_pano("p2", 2020)]}
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, _ = _plan_jobs(cfg, [loc1, loc2], panos, manifest)
        assert len(jobs) == 2

    def test_job_fields_populated_correctly(self, tmp_path):
        cfg = Config(output_dir=tmp_path)
        loc = _make_loc(target_years=[2020])
        pano = _make_pano("pano_xyz", 2020, 5)
        manifest = Manifest(tmp_path / "manifest.csv")
        jobs, _ = _plan_jobs(cfg, [loc], {"loc1": [pano]}, manifest)
        job = jobs[0]
        assert job.pano_id == "pano_xyz"
        assert job.target_year == 2020
        assert job.location_id == "loc1"
        assert job.heading == loc.heading
        assert job.size == loc.size


# Report
class TestReport:
    def _make_download_result(self, ok: bool, loc_id: str = "loc1") -> DownloadResult:
        job = DownloadJob(
            location_id=loc_id,
            pano_id="p",
            target_year=2020,
            pano_iso="2020-05",
            heading=0.0,
            pitch=0.0,
            fov=90.0,
            size="640x640",
            out_path=Path("/tmp/img.jpg"),
        )
        return DownloadResult(job=job, ok=ok, bytes_written=5000 if ok else 0)

    def test_downloads_ok_count(self):
        report = Report(
            locations=[],
            cfg=Config(),
            downloads=[
                self._make_download_result(True),
                self._make_download_result(True),
                self._make_download_result(False),
            ],
        )
        assert report.downloads_ok == 2

    def test_downloads_failed_count(self):
        report = Report(
            locations=[],
            cfg=Config(),
            downloads=[
                self._make_download_result(True),
                self._make_download_result(False),
                self._make_download_result(False),
            ],
        )
        assert report.downloads_failed == 2

    def test_empty_downloads(self):
        report = Report(locations=[], cfg=Config())
        assert report.downloads_ok == 0
        assert report.downloads_failed == 0
