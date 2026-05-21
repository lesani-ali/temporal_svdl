import csv
from pathlib import Path

from temporal_svdl.discovery import HistoricalPano
from temporal_svdl.downloader import DownloadJob, DownloadResult
from temporal_svdl.manifest import Manifest, _load_pano_cache, _save_pano_cache


# helpers
def _make_job(
    tmp_path: Path,
    *,
    location_id: str = "loc1",
    pano_id: str = "pano1",
    target_year: int = 2020,
    heading: float = 0.0,
    pitch: float = 0.0,
    fov: float = 90.0,
    size: str = "640x640",
) -> DownloadJob:
    return DownloadJob(
        location_id=location_id,
        pano_id=pano_id,
        target_year=target_year,
        pano_iso="2020-05",
        heading=heading,
        pitch=pitch,
        fov=fov,
        size=size,
        out_path=tmp_path / location_id / f"{pano_id}.jpg",
    )


def _ok_result(job: DownloadJob) -> DownloadResult:
    return DownloadResult(job=job, ok=True, bytes_written=10_000)


def _fail_result(job: DownloadJob) -> DownloadResult:
    return DownloadResult(job=job, ok=False, error="HTTP 403")


# Manifest
class TestManifest:
    def test_creates_csv_file(self, tmp_path):
        Manifest(tmp_path / "manifest.csv")
        assert (tmp_path / "manifest.csv").exists()

    def test_creates_parent_directories(self, tmp_path):
        nested = tmp_path / "a" / "b" / "manifest.csv"
        Manifest(nested)
        assert nested.exists()

    def test_new_job_is_not_done(self, tmp_path):
        m = Manifest(tmp_path / "manifest.csv")
        job = _make_job(tmp_path)
        assert not m.is_done(job)

    def test_record_ok_marks_job_done(self, tmp_path):
        m = Manifest(tmp_path / "manifest.csv")
        job = _make_job(tmp_path)
        m.record(_ok_result(job))
        assert m.is_done(job)

    def test_record_fail_does_not_mark_done(self, tmp_path):
        m = Manifest(tmp_path / "manifest.csv")
        job = _make_job(tmp_path)
        m.record(_fail_result(job))
        assert not m.is_done(job)

    def test_record_writes_row_to_csv(self, tmp_path):
        path = tmp_path / "manifest.csv"
        m = Manifest(path)
        job = _make_job(tmp_path)
        m.record(_ok_result(job))
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert len(rows) == 1
        assert rows[0]["pano_id"] == "pano1"
        assert rows[0]["status"] == "ok"

    def test_record_fail_writes_status_fail(self, tmp_path):
        path = tmp_path / "manifest.csv"
        m = Manifest(path)
        job = _make_job(tmp_path)
        m.record(_fail_result(job))
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert rows[0]["status"] == "fail"
        assert rows[0]["error"] == "HTTP 403"

    def test_resume_from_existing_csv(self, tmp_path):
        path = tmp_path / "manifest.csv"
        m1 = Manifest(path)
        job = _make_job(tmp_path)
        m1.record(_ok_result(job))

        m2 = Manifest(path)
        assert m2.is_done(job)

    def test_resume_does_not_load_failed_rows(self, tmp_path):
        path = tmp_path / "manifest.csv"
        m1 = Manifest(path)
        job = _make_job(tmp_path)
        m1.record(_fail_result(job))

        m2 = Manifest(path)
        assert not m2.is_done(job)

    def test_skips_malformed_rows_on_load(self, tmp_path):
        path = tmp_path / "manifest.csv"
        _ = Manifest(path)
        # Append a garbage row directly
        with path.open("a", encoding="utf-8") as fh:
            fh.write("bad,row,with,too,few,fields\n")
        # Second instance should not raise
        m2 = Manifest(path)
        assert len(m2._done) == 0

    def test_job_key_differentiates_camera_settings(self, tmp_path):
        m = Manifest(tmp_path / "manifest.csv")
        job_a = _make_job(tmp_path, heading=0.0, fov=90.0)
        job_b = _make_job(tmp_path, heading=90.0, fov=60.0)
        m.record(_ok_result(job_a))
        assert m.is_done(job_a)
        assert not m.is_done(job_b)

    def test_multiple_records_appended(self, tmp_path):
        path = tmp_path / "manifest.csv"
        m = Manifest(path)
        job_a = _make_job(tmp_path, pano_id="p1", target_year=2015)
        job_b = _make_job(tmp_path, pano_id="p2", target_year=2020)
        m.record(_ok_result(job_a))
        m.record(_ok_result(job_b))
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        assert len(rows) == 2


# _load_pano_cache / _save_pano_cache
class TestPanoCache:
    def test_roundtrip_preserves_panos(self, tmp_path):
        panos = {
            "loc1": [
                HistoricalPano(pano_id="a1", year=2015, month=6, iso="2015-06"),
                HistoricalPano(pano_id="a2", year=2020, month=3, iso="2020-03"),
            ],
        }
        path = tmp_path / "panos.json"
        _save_pano_cache(path, panos)
        loaded = _load_pano_cache(path)

        assert "loc1" in loaded
        assert len(loaded["loc1"]) == 2
        assert loaded["loc1"][0].pano_id == "a1"
        assert loaded["loc1"][0].year == 2015
        assert loaded["loc1"][1].pano_id == "a2"

    def test_empty_pano_list_preserved(self, tmp_path):
        panos = {"loc1": []}
        path = tmp_path / "panos.json"
        _save_pano_cache(path, panos)
        loaded = _load_pano_cache(path)
        assert loaded["loc1"] == []

    def test_multiple_locations(self, tmp_path):
        panos = {
            "loc1": [HistoricalPano("a", 2015, 6, "2015-06")],
            "loc2": [HistoricalPano("b", 2020, 3, "2020-03")],
        }
        path = tmp_path / "panos.json"
        _save_pano_cache(path, panos)
        loaded = _load_pano_cache(path)
        assert set(loaded.keys()) == {"loc1", "loc2"}

    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = _load_pano_cache(tmp_path / "nonexistent.json")
        assert result == {}

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "subdir" / "panos.json"
        _save_pano_cache(path, {})
        assert path.exists()
