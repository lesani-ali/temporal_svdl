from temporal_svdl.discovery import HistoricalPano
from temporal_svdl.selection import filter_by_date_range, select_panos_for_years


# filter_by_date_range
class TestFilterByDateRange:
    def test_no_bounds_returns_same_list(self, sample_panos):
        result = filter_by_date_range(sample_panos, None, None)
        assert result is sample_panos

    def test_year_from_excludes_older(self, sample_panos):
        result = filter_by_date_range(sample_panos, 2015, None)
        assert all(p.year >= 2015 for p in result)
        assert not any(p.year < 2015 for p in result)

    def test_year_to_excludes_newer(self, sample_panos):
        result = filter_by_date_range(sample_panos, None, 2019)
        assert all(p.year <= 2019 for p in result)

    def test_both_bounds_filters_correctly(self, sample_panos):
        result = filter_by_date_range(sample_panos, 2015, 2019)
        years = {p.year for p in result}
        assert years == {2015, 2019}

    def test_year_from_is_inclusive(self):
        panos = [HistoricalPano("x", 2015, 1, "2015-01")]
        assert filter_by_date_range(panos, 2015, None) == panos

    def test_year_to_is_inclusive(self):
        panos = [HistoricalPano("x", 2020, 1, "2020-01")]
        assert filter_by_date_range(panos, None, 2020) == panos

    def test_empty_input_returns_empty(self):
        assert filter_by_date_range([], 2015, 2020) == []

    def test_no_match_returns_empty(self, sample_panos):
        result = filter_by_date_range(sample_panos, 2030, 2035)
        assert result == []

    def test_order_preserved(self, sample_panos):
        result = filter_by_date_range(sample_panos, 2012, 2023)
        assert [p.pano_id for p in result] == [p.pano_id for p in sample_panos]


# select_panos_for_years
class TestSelectPanosForYears:
    def test_empty_panos_returns_empty(self):
        assert select_panos_for_years([], [2015, 2020]) == {}

    def test_empty_target_years_returns_empty(self, sample_panos):
        assert select_panos_for_years(sample_panos, []) == {}

    def test_exact_year_match(self, sample_panos):
        result = select_panos_for_years(sample_panos, [2015])
        assert result[2015].pano_id == "bbb"

    def test_picks_closest_year(self, sample_panos):
        # 2014: aaa(2012)=2 away, bbb(2015)=1 away → bbb wins
        result = select_panos_for_years(sample_panos, [2014])
        assert result[2014].year == 2015

    def test_june_tiebreaker_prefers_june(self):
        # Both 2019, month 3 vs month 6 — June (6) wins tiebreak
        panos = [
            HistoricalPano("march", 2019, 3, "2019-03"),
            HistoricalPano("june", 2019, 6, "2019-06"),
        ]
        result = select_panos_for_years(panos, [2019])
        assert result[2019].pano_id == "june"

    def test_multiple_target_years(self, sample_panos):
        result = select_panos_for_years(sample_panos, [2012, 2015, 2023])
        assert result[2012].pano_id == "aaa"
        assert result[2015].pano_id == "bbb"
        assert result[2023].pano_id == "eee"

    def test_single_pano_pool_matches_any_year(self):
        panos = [HistoricalPano("only", 2015, 6, "2015-06")]
        result = select_panos_for_years(panos, [2010, 2020])
        assert result[2010].pano_id == "only"
        assert result[2020].pano_id == "only"
