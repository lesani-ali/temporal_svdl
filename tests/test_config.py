import pytest
from pydantic import ValidationError
from temporal_svdl.config import Config, CameraDefaults, Location


# Location
class TestLocation:
    def test_auto_id_generated_from_coords(self):
        loc = Location(lat=43.0, lng=-79.0)
        assert loc.id is not None
        assert "43" in loc.id

    def test_auto_id_format(self):
        loc = Location(lat=43.12345, lng=-79.98765)
        # Should not contain '.' or '-' (replaced with 'p' and 'm')
        assert "." not in loc.id
        assert loc.id.startswith("loc_")

    def test_explicit_id_preserved(self):
        loc = Location(id="my_site", lat=43.0, lng=-79.0)
        assert loc.id == "my_site"

    def test_year_from_to_valid(self):
        loc = Location(lat=43.0, lng=-79.0, all_dates=True, year_from=2015, year_to=2020)
        assert loc.year_from == 2015
        assert loc.year_to == 2020

    def test_year_from_greater_than_year_to_raises(self):
        with pytest.raises(ValidationError, match="year_from"):
            Location(lat=43.0, lng=-79.0, all_dates=True, year_from=2020, year_to=2015)

    def test_year_from_equal_year_to_is_valid(self):
        loc = Location(lat=43.0, lng=-79.0, all_dates=True, year_from=2018, year_to=2018)
        assert loc.year_from == loc.year_to == 2018

    def test_invalid_size_raises(self):
        with pytest.raises(ValidationError, match="size"):
            Location(lat=43.0, lng=-79.0, size="invalid")

    def test_valid_size_accepted(self):
        loc = Location(lat=43.0, lng=-79.0, size="640x480")
        assert loc.size == "640x480"

    def test_fill_applies_defaults_for_unset_fields(self):
        defaults = CameraDefaults(heading=45.0, pitch=10.0, fov=60.0, size="320x240", radius=100)
        loc = Location(lat=43.0, lng=-79.0)
        filled = loc.fill(defaults)
        assert filled.heading == 45.0
        assert filled.pitch == 10.0
        assert filled.fov == 60.0
        assert filled.size == "320x240"
        assert filled.radius == 100

    def test_fill_preserves_explicit_field_values(self):
        defaults = CameraDefaults(heading=45.0, fov=60.0)
        loc = Location(lat=43.0, lng=-79.0, heading=270.0, fov=90.0)
        filled = loc.fill(defaults)
        assert filled.heading == 270.0
        assert filled.fov == 90.0

    def test_lat_lng_bounds_enforced(self):
        with pytest.raises(ValidationError):
            Location(lat=91.0, lng=0.0)
        with pytest.raises(ValidationError):
            Location(lat=0.0, lng=181.0)


# Config
class TestConfig:
    def test_default_values(self):
        cfg = Config()
        assert cfg.download_workers == 16
        assert cfg.discovery_workers == 4
        assert cfg.max_retries == 5
        assert str(cfg.output_dir) == "data/output"

    def test_manifest_path_name(self):
        cfg = Config(output_dir="/tmp/svdl_out")
        assert cfg.manifest_path.name == "manifest.csv"
        assert cfg.manifest_path.parent == cfg.output_dir

    def test_panos_cache_path_name(self):
        cfg = Config(output_dir="/tmp/svdl_out")
        assert cfg.panos_cache_path.name == "discovered_panos.json"

    def test_from_yaml_loads_values(self, tmp_path):
        yaml_content = "output_dir: /tmp/test_out\ndownload_workers: 8\nmax_retries: 3\n"
        p = tmp_path / "config.yaml"
        p.write_text(yaml_content)
        cfg = Config.from_yaml(p)
        assert cfg.download_workers == 8
        assert cfg.max_retries == 3

    def test_from_yaml_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Config.from_yaml(tmp_path / "nonexistent.yaml")

    def test_from_yaml_empty_file_uses_defaults(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        cfg = Config.from_yaml(p)
        assert cfg.download_workers == 16

    def test_from_yaml_defaults_section(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text("camera_defaults:\n  heading: 90\n  fov: 60\n")
        cfg = Config.from_yaml(p)
        assert cfg.camera_defaults.heading == 90.0
        assert cfg.camera_defaults.fov == 60.0


# CameraDefaults
class TestCameraDefaults:
    def test_default_values(self):
        d = CameraDefaults()
        assert d.heading is None  # None means: compute heading automatically
        assert d.pitch == 0.0
        assert d.fov == 60.0
        assert d.size == "640x640"
        assert d.radius == 50

    def test_explicit_heading_accepted(self):
        d = CameraDefaults(heading=90.0)
        assert d.heading == 90.0

    def test_heading_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            CameraDefaults(heading=361.0)


class TestLocationHeadingResolution:
    def test_none_heading_stays_none_when_default_also_none(self):
        defaults = CameraDefaults()  # heading=None
        loc = Location(lat=43.0, lng=-79.0)
        filled = loc.fill(defaults)
        assert filled.heading is None  # pipeline will compute it

    def test_fill_uses_explicit_default_heading(self):
        defaults = CameraDefaults(heading=180.0)
        loc = Location(lat=43.0, lng=-79.0)
        filled = loc.fill(defaults)
        assert filled.heading == 180.0

    def test_location_heading_overrides_default(self):
        defaults = CameraDefaults(heading=90.0)
        loc = Location(lat=43.0, lng=-79.0, heading=270.0)
        filled = loc.fill(defaults)
        assert filled.heading == 270.0
