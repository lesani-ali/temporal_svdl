import pytest
from temporal_svdl.discovery import HistoricalPano


@pytest.fixture
def sample_panos() -> list[HistoricalPano]:
    """Five panos spanning 2012–2023, including two in 2019."""
    return [
        HistoricalPano(pano_id="aaa", year=2012, month=3, iso="2012-03"),
        HistoricalPano(pano_id="bbb", year=2015, month=6, iso="2015-06"),
        HistoricalPano(pano_id="ccc", year=2019, month=9, iso="2019-09"),
        HistoricalPano(pano_id="ddd", year=2019, month=3, iso="2019-03"),
        HistoricalPano(pano_id="eee", year=2023, month=1, iso="2023-01"),
    ]
