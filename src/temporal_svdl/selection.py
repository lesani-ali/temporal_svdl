from __future__ import annotations

from typing import Optional

from .discovery import HistoricalPano


def filter_by_date_range(
    panos: list[HistoricalPano],
    year_from: Optional[int],
    year_to: Optional[int],
) -> list[HistoricalPano]:
    """Return only panos whose capture year falls within ``[year_from, year_to]``.

    Args:
        panos:     Input panorama list.
        year_from: Earliest year to include (inclusive).  ``None`` = no lower bound.
        year_to:   Latest year to include (inclusive).    ``None`` = no upper bound.
    """
    if year_from is None and year_to is None:
        return panos
    return [
        p
        for p in panos
        if (year_from is None or p.year >= year_from) and (year_to is None or p.year <= year_to)
    ]


def select_panos_for_years(
    panos: list[HistoricalPano],
    target_years: list[int],
) -> dict[int, HistoricalPano]:
    """For each target year, pick the pano whose capture date is closest to it.

    Tie-breaking rule: when two panos are equidistant in years, the one captured
    closer to June (month 6) is preferred.  This tends to favour summer imagery
    with better daylight and fewer obstructions.

    Args:
        panos:        Pool of candidate panoramas.
        target_years: Years of interest.
    """
    if not panos:
        return {}
    return {
        year: min(panos, key=lambda p: (abs(p.year - year), abs(p.month - 6)))
        for year in target_years
    }

def select_unique_panos_for_years(
    panos: list[HistoricalPano],
    target_years: list[int],
) -> dict[int, HistoricalPano]:
    """Pick panos for each target year such that no two target years map to the same pano.

    Tie-breaking rule: when two panos are equidistant in years, the one captured
    closer to June (month 6) is preferred.  This tends to favour summer imagery
    with better daylight and fewer obstructions.

    Args:
        panos:        Pool of candidate panoramas.
        target_years: Years of interest.
    """
    if not panos:
        return {}

    seen_pano_ids = set()
    selection = {}

    for year in target_years:
        pano = min(panos, key=lambda p: (abs(p.year - year), abs(p.month - 6)))
        if pano.pano_id not in seen_pano_ids:
            seen_pano_ids.add(pano.pano_id)
            selection[year] = pano
    
    return selection
