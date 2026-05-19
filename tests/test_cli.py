import json
from click.testing import CliRunner
from unittest.mock import AsyncMock, patch

from temporal_svdl.cli import _parse_years, cli
from temporal_svdl.discovery import DiscoveryResult, HistoricalPano


# _parse_years
class TestParseYears:
    def test_parses_single_year(self):
        assert _parse_years("2015") == [2015]

    def test_parses_multiple_years(self):
        assert _parse_years("2015,2020,2023") == [2015, 2020, 2023]

    def test_strips_whitespace_around_years(self):
        assert _parse_years(" 2015 , 2020 ") == [2015, 2020]

    def test_none_returns_empty_list(self):
        assert _parse_years(None) == []

    def test_empty_string_returns_empty_list(self):
        assert _parse_years("") == []


# CLI help / structure
class TestCliHelp:
    def test_root_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Street View" in result.output

    def test_point_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["point", "--help"])
        assert result.exit_code == 0
        assert "--lat" in result.output

    def test_url_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["url", "--help"])
        assert result.exit_code == 0

    def test_urls_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["urls", "--help"])
        assert result.exit_code == 0

    def test_batch_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["batch", "--help"])
        assert result.exit_code == 0

    def test_list_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["list", "--help"])
        assert result.exit_code == 0


# Error handling in commands
class TestCommandErrors:
    def test_point_without_lat_lng_fails(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["point"])
        assert result.exit_code != 0

    def test_url_without_url_flag_fails(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["url"])
        assert result.exit_code != 0

    def test_list_without_input_fails(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["list"])
        assert result.exit_code != 0

    def test_batch_without_json_file_fails(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["batch"])
        assert result.exit_code != 0


# list command (mocked discovery)


class TestListCommand:
    def test_list_by_latlong_prints_pano_table(self):
        mock_results = [
            DiscoveryResult(
                location_id="loc_43p00000_m79p00000",
                panos=[
                    HistoricalPano("pano1", 2018, 6, "2018-06"),
                    HistoricalPano("pano2", 2021, 3, "2021-03"),
                ],
            )
        ]
        runner = CliRunner()
        with patch(
            "temporal_svdl.cli.discover_locations", new=AsyncMock(return_value=mock_results)
        ):
            result = runner.invoke(cli, ["list", "--lat", "43.0", "--lng", "-79.0"])

        assert result.exit_code == 0
        assert "2018-06" in result.output
        assert "2021-03" in result.output

    def test_list_with_year_range_filters_output(self):
        mock_results = [
            DiscoveryResult(
                location_id="loc_43p00000_m79p00000",
                panos=[
                    HistoricalPano("old", 2012, 1, "2012-01"),
                    HistoricalPano("mid", 2018, 6, "2018-06"),
                    HistoricalPano("new", 2023, 9, "2023-09"),
                ],
            )
        ]
        runner = CliRunner()
        with patch(
            "temporal_svdl.cli.discover_locations", new=AsyncMock(return_value=mock_results)
        ):
            result = runner.invoke(
                cli,
                [
                    "list",
                    "--lat",
                    "43.0",
                    "--lng",
                    "-79.0",
                    "--year-from",
                    "2015",
                    "--year-to",
                    "2020",
                ],
            )

        assert result.exit_code == 0
        assert "2018-06" in result.output
        assert "2012-01" not in result.output
        assert "2023-09" not in result.output

    def test_list_discovery_error_shown(self):
        mock_results = [
            DiscoveryResult(
                location_id="loc_43p00000_m79p00000",
                panos=[],
                error="HTTP 500 from GeoPhotoService",
            )
        ]
        runner = CliRunner()
        with patch(
            "temporal_svdl.cli.discover_locations", new=AsyncMock(return_value=mock_results)
        ):
            result = runner.invoke(cli, ["list", "--lat", "43.0", "--lng", "-79.0"])

        assert result.exit_code == 0
        assert "HTTP 500" in result.output

    def test_list_no_panos_in_range_shows_warning(self):
        mock_results = [
            DiscoveryResult(
                location_id="loc_43p00000_m79p00000",
                panos=[HistoricalPano("p", 2010, 1, "2010-01")],
            )
        ]
        runner = CliRunner()
        with patch(
            "temporal_svdl.cli.discover_locations", new=AsyncMock(return_value=mock_results)
        ):
            result = runner.invoke(
                cli,
                [
                    "list",
                    "--lat",
                    "43.0",
                    "--lng",
                    "-79.0",
                    "--year-from",
                    "2020",
                ],
            )

        assert result.exit_code == 0
        assert "no panos in range" in result.output

    def test_list_from_json_file(self, tmp_path):
        data = [{"id": "site1", "lat": 43.0, "lng": -79.0, "target_years": [2020]}]
        json_file = tmp_path / "locs.json"
        json_file.write_text(json.dumps(data))

        mock_results = [
            DiscoveryResult(
                location_id="site1",
                panos=[HistoricalPano("p1", 2019, 6, "2019-06")],
            )
        ]
        runner = CliRunner()
        with patch(
            "temporal_svdl.cli.discover_locations", new=AsyncMock(return_value=mock_results)
        ):
            result = runner.invoke(cli, ["list", "--json-file", str(json_file)])

        assert result.exit_code == 0
        assert "2019-06" in result.output
