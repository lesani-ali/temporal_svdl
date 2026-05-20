# temporal-svdl

<!-- [![PyPI](https://img.shields.io/pypi/v/temporal-svdl)](https://pypi.org/project/temporal-svdl/)
[![Python](https://img.shields.io/pypi/pyversions/temporal-svdl)](https://pypi.org/project/temporal-svdl/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE) -->

**Historical Google Street View downloader.** Fetches panoramas for the *same viewpoint* across multiple points in time.

Useful for **change detection**, **longitudinal urban studies**, and **disaster-impact analysis**. True viewpoint consistency is guaranteed by pinning each Static API request to a specific `pano_id`, so the camera position is identical across all years.

---

## How it works

```
Discovery  →  Selection  →  Download
```

1. **Discovery** — queries Google's internal GeoPhoto API to retrieve the full timeline of panoramas at each coordinate (no API key required for this step).
2. **Selection** — for each target year, picks the captured panorama whose date is closest to that year.
3. **Download** — calls the Street View Static API with `pano=<id>` (not `lat,lng`), guaranteeing the same camera position across all years. All images are fetched concurrently for speed.

Results are written to an append-only `manifest.csv` so interrupted runs can resume without re-downloading completed images. Discovery results are also cached to avoid re-querying locations on repeat runs.

---

## Requirements

- Python 3.10+
- A Google Maps API key with **Street View Static API** enabled

---

## Installation

<!-- ```bash
pip install temporal-svdl
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv add temporal-svdl
```

Or from source: -->

```bash
git clone https://github.com/cviss-lab/temporal-svdl
cd temporal-svdl

# pip
pip install -e .

# or with uv
uv sync
```

**Set up your API key:**

```bash
cp .env.example .env
# open .env and fill in GOOGLE_MAPS_API_KEY=<your-key>
```

If your key has URL signing enforced, also set `GOOGLE_MAPS_URL_SIGNING_SECRET` in `.env`.

---

## Quickstart

### Python API

```python
from temporal_svdl import download

# Single coordinate — pick the closest pano to each target year
report = download(lat=43.6629, lng=-79.3957, target_years=[2015, 2020, 2023])

# Single coordinate — every available historical panorama
report = download(lat=43.6629, lng=-79.3957, all_dates=True)

# Limit to a date range
report = download(lat=43.6629, lng=-79.3957, all_dates=True, year_from=2015, year_to=2022)

# From a Google Maps URL (camera angles extracted automatically)
report = download(
    url="https://www.google.com/maps/@43.6629,-79.3957,3a,75y,134h,90t",
    target_years=[2015, 2023],
)

# From a JSON batch file
report = download(json_file="data/input/locations.json")

# From a text file of URLs
report = download(urls_file="data/input/urls.txt", target_years=[2015, 2023])

print(f"Downloaded {report.downloads_ok}, failed {report.downloads_failed}")
```

**Async entry point** — use this inside an existing event loop:

```python
import asyncio
from temporal_svdl import adownload

report = asyncio.run(adownload(lat=43.66, lng=-79.39, target_years=[2015, 2023]))
```

**Custom configuration:**

```python
from temporal_svdl import Config, download

cfg = Config(
    output_dir="data/output",
    download_workers=32,
    max_retries=3,
)
report = download(json_file="locations.json", config=cfg)
```

### CLI

```bash
# Single coordinate
temporal-svdl point --lat 43.6629 --lng -79.3957 --years 2015,2020,2023

# Every available date at a coordinate
temporal-svdl point --lat 43.6629 --lng -79.3957 --all-dates

# From a Google Maps URL
temporal-svdl url --url "https://www.google.com/maps/@43.66,-79.39,17z" --years 2015,2023

# From a text file of URLs
temporal-svdl urls --urls-file data/input/urls.txt --years 2015,2023

# From a JSON batch file (years defined per location in the file)
temporal-svdl batch --json-file data/input/locations.json
```

---

## CLI reference

All download commands (`point`, `url`, `urls`, `batch`) share a common set of flags:

| Flag | Description |
|---|---|
| `-c / --config PATH` | YAML config file (see [Configuration](#configuration)). |
| `-o / --output PATH` | Override the output directory from config. |
| `--yes` | Skip the confirmation prompt before downloading. |
| `--discover-only` | Run discovery only — no images are downloaded. |
| `--download-only` | Skip discovery and use the pano cache from a previous run. |
| `--refresh-discovery` | Ignore the pano cache and re-query all locations. |

The `point`, `url`, and `urls` commands also accept:

| Flag | Description |
|---|---|
| `-y / --years 2015,2020` | Comma-separated target years. |
| `--all-dates` | Download every available historical panorama. |
| `--year-from YEAR` | Exclude panoramas captured before this year. |
| `--year-to YEAR` | Exclude panoramas captured after this year. |

### Explore available dates before downloading

Use the `list` command to see what Google holds for a location without downloading anything:

```bash
# By coordinate
temporal-svdl list --lat 43.6629 --lng -79.3957

# By Google Maps URL
temporal-svdl list --url "https://www.google.com/maps/@43.66,-79.39,17z"

# With a date filter
temporal-svdl list --lat 43.6629 --lng -79.3957 --year-from 2015 --year-to 2022

# For all locations in a batch file
temporal-svdl list --json-file data/input/locations.json
```

---

## Input formats

### JSON batch file

Each entry is a location. `target_years` or `all_dates` must be set per entry. All camera fields and `id` are optional — they fall back to `Config.defaults`.

```json
[
  {
    "id": "cn_tower",
    "lat": 43.6426,
    "lng": -79.3871,
    "target_years": [2014, 2019, 2023],
    "heading": 45,
    "pitch": 0,
    "fov": 90,
    "size": "640x640",
    "radius": 50
  },
  {
    "lat": 43.6532,
    "lng": -79.3832,
    "all_dates": true,
    "year_from": 2015
  }
]
```

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | string | auto | Human-readable label. Auto-generated from coordinates if omitted. |
| `lat` | float | — | Latitude in decimal degrees. |
| `lng` | float | — | Longitude in decimal degrees. |
| `target_years` | list[int] | — | Years of interest (mutually exclusive with `all_dates`). |
| `all_dates` | bool | `false` | If `true`, every discovered historical panorama is downloaded. |
| `year_from` | int | `null` | Exclude panoramas captured before this year. |
| `year_to` | int | `null` | Exclude panoramas captured after this year. |
| `heading` | float | 0 | Compass heading in degrees (0 = north, 90 = east). |
| `pitch` | float | 0 | Vertical angle in degrees (0 = horizontal). |
| `fov` | float | 90 | Horizontal field of view in degrees (max 120). |
| `size` | string | `"640x640"` | Image dimensions as `WIDTHxHEIGHT`. |
| `radius` | int | 50 | Search radius in metres for the nearest panorama. |

### URL text file

One Google Maps URL per line. Blank lines and lines beginning with `#` are ignored.
Supports place URLs (`@lat,lng`), Street View URLs (heading/pitch/FOV extracted automatically),
and shortlinks (`goo.gl`, `maps.app.goo.gl`).

```
# Downtown Toronto
https://www.google.com/maps/@43.6532,-79.3832,3a,75y,134h,90t/data=...

# Another location
https://maps.app.goo.gl/abc123
```

---

## Configuration

Create `configs/config.yaml` (or point to any YAML file with `-c`):

```yaml
output_dir: data/output

# Camera parameter defaults — applied to any location that omits them.
defaults:
  heading: 0        # Compass heading (0 = north, 90 = east).
  pitch: 0          # Vertical angle: 0 = horizontal.
  fov: 90           # Horizontal field of view in degrees (max 120).
  size: 640x640     # Image dimensions as WIDTHxHEIGHT.
  radius: 50        # Search radius in metres.

# Concurrency
discovery_workers: 4    # Parallel GeoPhoto API workers.
download_workers: 16    # Parallel Static API download workers.

# Retry / back-off for failed downloads
max_retries: 5
initial_backoff_seconds: 1.0
max_backoff_seconds: 30.0

# Logging
log_level: INFO         # DEBUG | INFO | WARNING | ERROR
log_file: null          # Set a path to also write logs to a file.
```

All fields are optional — the values above are the defaults.

### Environment variables

Store credentials in `.env` (never commit this file):

```bash
GOOGLE_MAPS_API_KEY=your-api-key-here

# Optional — set only if your key has URL signing enforced.
# GOOGLE_MAPS_URL_SIGNING_SECRET=your-signing-secret
```

---

## Output structure

```
data/output/
├── manifest.csv               # Append-only record of every download attempt.
├── discovered_panos.json      # Cache of GeoPhoto discovery results.
└── <location_id>/
    └── <YYYY-MM>_<pano_id>_h<heading>_p<pitch>_f<fov>_y<target_year>.jpg
```

**Example filename:**
```
2019-06_AbCdEfGhIjKlMnOpQrStUv_h45_p0_f90_y2019.jpg
```

### Resume behaviour

Re-running the same command is safe:

- Images already marked `ok` in `manifest.csv` are skipped.
- Locations already in `discovered_panos.json` skip the GeoPhoto query. Use `--refresh-discovery` to force a re-query.
- Use `--download-only` to skip discovery entirely and re-use the cached pano list.

---

## Python API reference

### `download(**kwargs) → Report`
### `adownload(**kwargs) → Report`

Synchronous and async entry points. Both accept the same keyword arguments:

| Argument | Type | Description |
|---|---|---|
| `locations` | `list[Location]` | Pre-built location objects. |
| `json_file` | `str \| Path` | Path to a JSON batch file. |
| `lat`, `lng` | `float` | Single coordinate. |
| `url` | `str` | A Google Maps URL. |
| `urls_file` | `str \| Path` | Path to a URL text file. |
| `target_years` | `list[int]` | Years of interest. |
| `all_dates` | `bool` | Download every available historical pano. |
| `year_from` | `int` | Filter: exclude panos before this year. |
| `year_to` | `int` | Filter: exclude panos after this year. |
| `config` | `Config` | Pipeline config. Defaults used if omitted. |
| `confirm` | `bool` | Prompt before downloading (default `True`). |
| `discover_only` | `bool` | Stop after discovery. |
| `download_only` | `bool` | Skip discovery, use cached panos. |
| `refresh_discovery` | `bool` | Ignore cache and re-query. |
| `show_progress` | `bool` | Show Rich progress bars (default `True`). |

Provide exactly one of `locations`, `json_file`, `lat+lng`, `url`, or `urls_file`.

### `list_panos(**kwargs) → dict[str, list[HistoricalPano]]`

Async. Discovers and returns all available panoramas without downloading. Returns a mapping of `location_id → [HistoricalPano, ...]`.

```python
import asyncio
from temporal_svdl import list_panos

panos = asyncio.run(list_panos(lat=43.6629, lng=-79.3957, year_from=2015))
for loc_id, history in panos.items():
    for p in history:
        print(p.iso, p.pano_id)
```

### `Report`

| Property / field | Type | Description |
|---|---|---|
| `locations` | `list[Location]` | Locations that were processed. |
| `cfg` | `Config` | Config used for the run. |
| `panos_by_loc` | `dict[str, list[HistoricalPano]]` | All discovered panos. |
| `n_planned` | `int` | Total download jobs planned. |
| `n_skipped` | `int` | Jobs skipped (already in manifest). |
| `downloads_ok` | `int` | Images downloaded successfully. |
| `downloads_failed` | `int` | Permanently failed download attempts. |
| `downloads` | `list[DownloadResult]` | Per-image outcomes. |

### `HistoricalPano`

| Field | Type | Description |
|---|---|---|
| `pano_id` | `str` | Google panorama identifier. |
| `year` | `int` | Capture year. |
| `month` | `int` | Capture month (1–12). |
| `iso` | `str` | Capture date as `'YYYY-MM'`. |

---

## Contributing

Bug reports and pull requests are welcome on [GitHub](https://github.com/lesani-ali/temporal_svdl/issues).

When contributing code, please:
- Run `ruff check src/ tests/` before submitting.
- Add or update tests under `tests/` for any behaviour changes.
- Keep PRs focused — one logical change per PR.

---

## License

Apache 2.0 — see [LICENSE](LICENSE) for the full text.