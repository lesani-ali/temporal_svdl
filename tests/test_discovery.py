import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from temporal_svdl.config import Location
from temporal_svdl.discovery import (
    _build_request_url,
    _extract_panos,
    _parse_jsonp,
    _query_location,
)


# helpers
def _make_geophoto_data(entries: list[tuple[str, int, int]]) -> list:
    """Build a minimal GeoPhoto response for the given (pano_id, year, month) entries.

    Entries are given oldest-first; the response format is most-recent-first,
    so this helper reverses them before building the structure.

    Response layout mirrored from _extract_panos docstring:
      data[1][5][0]  = cluster
      cluster[3][0]  = raw_panos  (entry[0][1] = pano_id)
      cluster[8]     = raw_dates  (d[1][0]=year, d[1][1]=month)
    """
    rev = list(reversed(entries))
    raw_panos = [[[None, pid]] for pid, _y, _m in rev]
    raw_dates = [["_", [y, m]] for _pid, y, m in rev]
    cluster = [None, None, None, [raw_panos], None, None, None, None, raw_dates]
    return [None, [None, None, None, None, None, [cluster]]]


def _make_loc(**kwargs) -> Location:
    defaults = {"lat": 43.0, "lng": -79.0, "radius": 50}
    defaults.update(kwargs)
    return Location(**defaults)


# _build_request_url
class TestBuildRequestUrl:
    def test_contains_lat_lng_radius(self):
        url = _build_request_url(43.66, -79.39, 50)
        assert "43.66" in url
        assert "-79.39" in url
        assert "50" in url

    def test_starts_with_geophoto_endpoint(self):
        url = _build_request_url(0.0, 0.0, 25)
        assert url.startswith("https://maps.googleapis.com/maps/api/js/GeoPhotoService")

    def test_contains_callback(self):
        url = _build_request_url(0.0, 0.0, 25)
        assert "callback=" in url


# _parse_jsonp
class TestParseJsonp:
    def test_strips_callback_wrapper(self):
        result = _parse_jsonp("callbackfunc([1, 2, 3])")
        assert result == [1, 2, 3]

    def test_handles_whitespace_inside_wrapper(self):
        result = _parse_jsonp("callbackfunc(  [1, 2, 3]  )")
        assert result == [1, 2, 3]

    def test_raises_on_non_jsonp(self):
        with pytest.raises(ValueError, match="JSONP"):
            _parse_jsonp("not jsonp at all")

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="JSONP"):
            _parse_jsonp("")


# _extract_panos
class TestExtractPanos:
    def test_no_imagery_sentinel_returns_empty(self):
        data = [[5, "generic", "Search returned no images."]]
        assert _extract_panos(data) == []

    def test_parses_single_pano(self):
        data = _make_geophoto_data([("pano_a", 2015, 8)])
        result = _extract_panos(data)
        assert len(result) == 1
        assert result[0].pano_id == "pano_a"
        assert result[0].year == 2015
        assert result[0].month == 8
        assert result[0].iso == "2015-08"

    def test_parses_multiple_panos_oldest_first(self):
        data = _make_geophoto_data(
            [
                ("pano_a", 2015, 8),
                ("pano_b", 2020, 5),
            ]
        )
        result = _extract_panos(data)
        assert len(result) == 2
        assert result[0].pano_id == "pano_a"
        assert result[0].year == 2015
        assert result[1].pano_id == "pano_b"
        assert result[1].year == 2020

    def test_month_zero_padded_in_iso(self):
        data = _make_geophoto_data([("p", 2020, 3)])
        result = _extract_panos(data)
        assert result[0].iso == "2020-03"

    def test_skips_undated_panos_at_end(self):
        # Start from a 1-entry dataset and inject an extra undated pano
        # (most-recent) so it lands beyond the dates list after reversing.
        data = _make_geophoto_data([("dated", 2020, 5)])
        cluster = data[1][5][0]
        # Insert undated pano at front (most-recent position)
        cluster[3][0].insert(0, [[None, "undated"]])
        result = _extract_panos(data)
        assert len(result) == 1
        assert result[0].pano_id == "dated"

    def test_skips_malformed_pano_entry(self):
        # Insert a pano entry whose [0][1] access raises TypeError
        data = _make_geophoto_data([("good", 2020, 5)])
        cluster = data[1][5][0]
        # Inject a malformed entry (most-recent) together with a matching date
        cluster[3][0].insert(0, [None])  # entry[0] = None → TypeError
        cluster[8].insert(0, ["_", [2021, 1]])
        result = _extract_panos(data)
        assert len(result) == 1
        assert result[0].pano_id == "good"

    def test_raises_on_unexpected_response_structure(self):
        with pytest.raises(ValueError, match="Unexpected"):
            _extract_panos([None, "unexpected"])


# _query_location
class TestQueryLocation:
    async def test_success_returns_ok_result(self):
        body = 'callbackfunc([[5, "generic", "Search returned no images."]])'
        mock_resp = MagicMock()
        mock_resp.text = body
        mock_resp.raise_for_status = MagicMock()

        loc = _make_loc()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            async with httpx.AsyncClient() as client:
                result = await _query_location(client, loc)

        assert result.ok
        assert result.error is None
        assert result.panos == []

    async def test_success_with_panos(self):
        data = _make_geophoto_data([("pano1", 2018, 6)])
        import json as _json

        body = f"callbackfunc({_json.dumps(data)})"
        mock_resp = MagicMock()
        mock_resp.text = body
        mock_resp.raise_for_status = MagicMock()

        loc = _make_loc()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            async with httpx.AsyncClient() as client:
                result = await _query_location(client, loc)

        assert result.ok
        assert len(result.panos) == 1
        assert result.panos[0].pano_id == "pano1"

    async def test_http_error_captured_in_result(self):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(500),
            )
        )

        loc = _make_loc()
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            async with httpx.AsyncClient() as client:
                result = await _query_location(client, loc)

        assert not result.ok
        assert "500" in result.error

    async def test_network_error_captured_in_result(self):
        loc = _make_loc()
        with patch.object(
            httpx.AsyncClient,
            "get",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("connection refused"),
        ):
            async with httpx.AsyncClient() as client:
                result = await _query_location(client, loc)

        assert not result.ok
        assert result.error is not None
