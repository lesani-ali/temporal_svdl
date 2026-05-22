import math

from temporal_svdl.geo import compute_bearing


class TestComputeBearing:
    def test_due_north(self):
        # Moving north: same longitude, higher latitude
        b = compute_bearing(0.0, 0.0, 1.0, 0.0)
        assert math.isclose(b, 0.0, abs_tol=0.01)

    def test_due_south(self):
        b = compute_bearing(1.0, 0.0, 0.0, 0.0)
        assert math.isclose(b, 180.0, abs_tol=0.01)

    def test_due_east(self):
        b = compute_bearing(0.0, 0.0, 0.0, 1.0)
        assert math.isclose(b, 90.0, abs_tol=0.01)

    def test_due_west(self):
        b = compute_bearing(0.0, 0.0, 0.0, -1.0)
        assert math.isclose(b, 270.0, abs_tol=0.01)

    def test_result_in_range(self):
        b = compute_bearing(51.5, -0.1, 48.8, 2.35)
        assert 0 <= b < 360

    def test_northeast_quadrant(self):
        # From south-west to north-east should be roughly 45°
        b = compute_bearing(0.0, 0.0, 0.7, 0.7)
        assert 44 < b < 46
