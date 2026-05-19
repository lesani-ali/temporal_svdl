import base64
import httpx
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from temporal_svdl.config import Config
from temporal_svdl.downloader import (
    DownloadJob,
    _fetch_image,
    _sign_url,
    build_download_url,
)

_MIN_IMAGE_BYTES = 5_000  # must match downloader._MIN_IMAGE_BYTES


# helpers


def _make_job(tmp_path: Path, *, pano_id: str = "test_pano") -> DownloadJob:
    return DownloadJob(
        location_id="loc1",
        pano_id=pano_id,
        target_year=2020,
        pano_iso="2020-05",
        heading=45.0,
        pitch=0.0,
        fov=90.0,
        size="640x640",
        out_path=tmp_path / "loc1" / "img.jpg",
    )


def _dummy_secret() -> str:
    return base64.urlsafe_b64encode(b"test_secret_key_").decode()


# _sign_url
class TestSignUrl:
    def test_appends_signature_param(self):
        url = "https://example.com/api?param=value"
        signed = _sign_url(url, _dummy_secret())
        assert "signature=" in signed

    def test_deterministic_for_same_input(self):
        url = "https://example.com/api?param=value"
        secret = _dummy_secret()
        assert _sign_url(url, secret) == _sign_url(url, secret)

    def test_different_urls_produce_different_signatures(self):
        secret = _dummy_secret()
        s1 = _sign_url("https://example.com/api?a=1", secret)
        s2 = _sign_url("https://example.com/api?a=2", secret)
        assert s1 != s2


# build_download_url
class TestBuildDownloadUrl:
    def test_contains_pano_id(self, tmp_path):
        job = _make_job(tmp_path)
        url = build_download_url(job, api_key="MY_KEY", signing_secret=None)
        assert "pano=test_pano" in url

    def test_contains_api_key(self, tmp_path):
        job = _make_job(tmp_path)
        url = build_download_url(job, api_key="MY_KEY", signing_secret=None)
        assert "key=MY_KEY" in url

    def test_contains_size(self, tmp_path):
        job = _make_job(tmp_path)
        url = build_download_url(job, api_key="MY_KEY", signing_secret=None)
        assert "size=640x640" in url

    def test_contains_camera_params(self, tmp_path):
        job = _make_job(tmp_path)
        url = build_download_url(job, api_key="MY_KEY", signing_secret=None)
        assert "heading=45" in url
        assert "pitch=0" in url
        assert "fov=90" in url

    def test_no_signature_without_secret(self, tmp_path):
        job = _make_job(tmp_path)
        url = build_download_url(job, api_key="MY_KEY", signing_secret=None)
        assert "signature" not in url

    def test_signature_appended_with_secret(self, tmp_path):
        job = _make_job(tmp_path)
        url = build_download_url(job, api_key="MY_KEY", signing_secret=_dummy_secret())
        assert "signature=" in url

    def test_starts_with_static_api_url(self, tmp_path):
        job = _make_job(tmp_path)
        url = build_download_url(job, api_key="KEY", signing_secret=None)
        assert url.startswith("https://maps.googleapis.com/maps/api/streetview")


# _fetch_image
class TestFetchImage:
    async def test_success_writes_file(self, tmp_path):
        job = _make_job(tmp_path)
        fake_image = b"\xff\xd8\xff" + b"\x00" * (_MIN_IMAGE_BYTES + 100)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_image

        cfg = Config(max_retries=1, initial_backoff_seconds=0.01, max_backoff_seconds=0.01)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            async with httpx.AsyncClient() as client:
                result = await _fetch_image(client, job, "MY_KEY", None, cfg)

        assert result.ok
        assert result.bytes_written == len(fake_image)
        assert job.out_path.exists()

    async def test_403_fails_immediately_without_retry(self, tmp_path):
        job = _make_job(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.content = b""

        cfg = Config(max_retries=5, initial_backoff_seconds=0.01, max_backoff_seconds=0.01)
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp

        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            async with httpx.AsyncClient() as client:
                result = await _fetch_image(client, job, "MY_KEY", None, cfg)

        assert not result.ok
        assert "403" in result.error
        assert call_count == 1  # no retries for 403

    async def test_small_response_treated_as_no_imagery(self, tmp_path):
        job = _make_job(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"tiny"  # well below _MIN_IMAGE_BYTES

        cfg = Config(max_retries=1, initial_backoff_seconds=0.01, max_backoff_seconds=0.01)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            async with httpx.AsyncClient() as client:
                result = await _fetch_image(client, job, "MY_KEY", None, cfg)

        assert not result.ok
        assert result.error is not None
        assert not job.out_path.exists()  # no file written for placeholder

    async def test_429_triggers_retry(self, tmp_path):
        job = _make_job(tmp_path)

        call_count = 0
        fake_image = b"x" * (_MIN_IMAGE_BYTES + 1)

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(status_code=429, content=b"")
            return MagicMock(status_code=200, content=fake_image)

        cfg = Config(max_retries=3, initial_backoff_seconds=0.001, max_backoff_seconds=0.001)
        with patch.object(httpx.AsyncClient, "get", side_effect=mock_get):
            async with httpx.AsyncClient() as client:
                result = await _fetch_image(client, job, "MY_KEY", None, cfg)

        assert result.ok
        assert call_count == 2  # failed once, succeeded on retry

    async def test_atomic_write_no_partial_file_on_error(self, tmp_path):
        job = _make_job(tmp_path)
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.content = b""

        cfg = Config(max_retries=1, initial_backoff_seconds=0.01, max_backoff_seconds=0.01)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            async with httpx.AsyncClient() as client:
                await _fetch_image(client, job, "MY_KEY", None, cfg)

        # Neither the final file nor a leftover .part file should exist
        assert not job.out_path.exists()
        assert not job.out_path.with_suffix(".jpg.part").exists()
