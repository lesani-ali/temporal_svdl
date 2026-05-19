import json
import pytest
from temporal_svdl.loaders import load_locations_json, load_urls_file, parse_google_maps_url


# load_locations_json
class TestLoadLocationsJson:
    def test_loads_valid_array(self, tmp_path):
        data = [{"lat": 43.0, "lng": -79.0}]
        p = tmp_path / "locs.json"
        p.write_text(json.dumps(data))
        locs = load_locations_json(p)
        assert len(locs) == 1
        assert locs[0].lat == 43.0
        assert locs[0].lng == -79.0

    def test_loads_multiple_entries(self, tmp_path):
        data = [
            {"lat": 43.0, "lng": -79.0},
            {"lat": 44.0, "lng": -80.0, "all_dates": True},
        ]
        p = tmp_path / "locs.json"
        p.write_text(json.dumps(data))
        locs = load_locations_json(p)
        assert len(locs) == 2
        assert locs[1].all_dates is True

    def test_raises_if_not_array(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text('{"lat": 43.0}')
        with pytest.raises(ValueError, match="JSON array"):
            load_locations_json(p)

    def test_accepts_string_path(self, tmp_path):
        data = [{"lat": 43.0, "lng": -79.0}]
        p = tmp_path / "locs.json"
        p.write_text(json.dumps(data))
        locs = load_locations_json(str(p))
        assert len(locs) == 1

    def test_preserves_optional_camera_fields(self, tmp_path):
        data = [{"lat": 43.0, "lng": -79.0, "heading": 90.0, "fov": 60.0, "size": "320x240"}]
        p = tmp_path / "locs.json"
        p.write_text(json.dumps(data))
        locs = load_locations_json(p)
        assert locs[0].heading == 90.0
        assert locs[0].fov == 60.0
        assert locs[0].size == "320x240"


# load_urls_file
class TestLoadUrlsFile:
    def test_returns_non_empty_non_comment_lines(self, tmp_path):
        content = (
            "# comment\n"
            "\n"
            "https://maps.google.com/@43.0,-79.0,17z\n"
            "\n"
            "# another comment\n"
            "https://maps.google.com/@44.0,-80.0,17z\n"
        )
        p = tmp_path / "urls.txt"
        p.write_text(content)
        urls = load_urls_file(p)
        assert len(urls) == 2
        assert all(u.startswith("https://") for u in urls)

    def test_empty_file_returns_empty_list(self, tmp_path):
        p = tmp_path / "empty.txt"
        p.write_text("")
        assert load_urls_file(p) == []

    def test_only_comments_returns_empty_list(self, tmp_path):
        p = tmp_path / "comments.txt"
        p.write_text("# line 1\n# line 2\n")
        assert load_urls_file(p) == []

    def test_strips_trailing_whitespace(self, tmp_path):
        p = tmp_path / "urls.txt"
        p.write_text("https://maps.google.com/@43.0,-79.0,17z   \n")
        urls = load_urls_file(p)
        assert urls[0] == "https://maps.google.com/@43.0,-79.0,17z"


# parse_google_maps_url
class TestParseGoogleMapsUrl:
    def test_extracts_lat_lng(self):
        url = "https://www.google.com/maps/@43.6629,-79.3957,17z"
        loc = parse_google_maps_url(url)
        assert abs(loc.lat - 43.6629) < 1e-4
        assert abs(loc.lng - (-79.3957)) < 1e-4

    def test_extracts_camera_params_from_street_view_url(self):
        # ,75y,134h,90t → fov=75, heading=134, tilt=90 → pitch=0
        url = "https://www.google.com/maps/@43.66,-79.39,3a,75y,134h,90t/data=!3m6"
        loc = parse_google_maps_url(url)
        assert loc.fov == 75.0
        assert loc.heading == 134.0
        assert loc.pitch == 0.0  # tilt 90 = horizon → pitch 0

    def test_tilt_to_pitch_conversion(self):
        # tilt 0 → pitch -90 (looking straight up)
        # tilt 180 → pitch +90 (looking straight down)
        url = "https://www.google.com/maps/@43.66,-79.39,3a,90y,0h,0t"
        loc = parse_google_maps_url(url)
        assert loc.pitch == -90.0

    def test_no_camera_params_leaves_fields_none(self):
        url = "https://www.google.com/maps/@43.0,-79.0,17z"
        loc = parse_google_maps_url(url)
        assert loc.fov is None
        assert loc.heading is None
        assert loc.pitch is None

    def test_raises_if_no_lat_lng_in_url(self):
        with pytest.raises(ValueError, match="lat/lng"):
            parse_google_maps_url("https://www.google.com/maps/place/Toronto")
