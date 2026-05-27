# temporal-svdl

<!-- [![PyPI](https://img.shields.io/pypi/v/temporal-svdl)](https://pypi.org/project/temporal-svdl/)
[![Python](https://img.shields.io/pypi/pyversions/temporal-svdl)](https://pypi.org/project/temporal-svdl/) -->
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

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

**Set up your API key** (required regardless of whether you use the Python API or CLI):

```bash
cp .env.example .env
# open .env and fill in GOOGLE_MAPS_API_KEY=<your-key>
```

If your key has URL signing enforced, also set `GOOGLE_MAPS_URL_SIGNING_SECRET` in `.env`.

---

## Jump to your use case:
- [Python API](#python-api) — import and call from Python scripts or notebooks.
- [CLI](#cli) — run from the terminal without writing Python code.

## Input modes

Both the Python API and the CLI accept locations in four ways:

1. **Single coordinate** — provide a latitude/longitude pair directly. See [Python API › Basic usage](#basic-usage) or [CLI › Quick start](#quick-start).
2. **Google Maps URL** — paste a URL from Google Maps; heading, pitch, and FOV are extracted automatically when present. See [Python API › Input from URLs or files](#input-from-urls-or-files) or [CLI › Quick start](#quick-start).
3. **URL text file** — a plain-text file with one Google Maps URL per line (blank lines and `#` comments ignored). See [URL text file](#url-text-file).
4. **JSON batch file** — a JSON array where each entry is a location with its own camera settings and temporal selection. Recommended for large or recurring jobs. See [JSON batch file](#json-batch-file).

## Python API

### Basic usage

```python
from temporal_svdl import download

# Single coordinate — pick the closest pano to each target year
report = download(lat=43.6629, lng=-79.3957, target_years=[2015, 2020, 2023])

# Single coordinate — every available historical panorama
report = download(lat=43.6629, lng=-79.3957, all_dates=True)

# Limit to a date range
report = download(lat=43.6629, lng=-79.3957, all_dates=True, year_from=2015, year_to=2022)

print(f"Downloaded {report.downloads_ok}, failed {report.downloads_failed}")
```

### Setting camera parameters

Camera parameters — heading, pitch, field of view, image size, and search radius — are set by
passing `Location` objects. Every parameter is optional; omitting it uses the default shown below.

```python
from temporal_svdl import download, Location

report = download(
    locations=[
        Location(
            lat=43.6629,
            lng=-79.3957,
            target_years=[2015, 2020, 2023],
            # heading  — omit to aim at the target automatically (see below)
            heading=90,    # explicit: face east
            pitch=-5,      # tilt slightly downward (default: 0)
            fov=90,        # field of view in degrees (default: 90, max: 120)
            size="640x640",# image dimensions (default: "640x640")
            radius=50,     # search radius in metres (default: 50)
        )
    ]
)
```

**Multiple locations** — pass a list:

```python
from temporal_svdl import download, Location

locations = [
    Location(lat=43.6426, lng=-79.3871, target_years=[2015, 2020]),
    Location(lat=43.6532, lng=-79.3832, all_dates=True, year_from=2018),
]
report = download(locations=locations)
```

**Shared defaults** — use `Config` + `CameraDefaults` to apply the same camera settings to every
location without repeating them:

```python
from temporal_svdl import Config, CameraDefaults, Location, download

cfg = Config(
    output_dir="data/output",
    camera_defaults=CameraDefaults(
        pitch=-5,
        fov=90,
        size="640x640",
        radius=50,
        # heading omitted → auto-computed per location
    ),
)

locations = [
    Location(lat=43.6426, lng=-79.3871, all_dates=True),
    Location(lat=43.6532, lng=-79.3832, all_dates=True),
]
report = download(locations=locations, config=cfg)
```

A location-level value always overrides the shared default — for example, one location can have
`heading=270` while all others use the auto-computed heading.

### Automatic heading

If `heading` is not provided for a location, the pipeline computes it automatically:

1. Calls the Street View Metadata API with the target coordinates to find the nearest camera on the street.
2. Computes the compass bearing from that camera toward your target.
3. Uses that bearing as the heading for all downloads at that location.

```python
# heading omitted → automatically aimed at the building
Location(lat=43.6426, lng=-79.3871, all_dates=True)

# heading explicit → overrides auto-computation
Location(lat=43.6426, lng=-79.3871, all_dates=True, heading=270)
```

### Input from URLs or files

```python
from temporal_svdl import download

# From a Google Maps URL (heading/pitch/FOV extracted automatically when present)
report = download(
    url="https://www.google.com/maps/@43.6629,-79.3957,3a,75y,134h,90t",
    target_years=[2015, 2023],
)

# From a text file of URLs
report = download(urls_file="data/input/urls.txt", target_years=[2015, 2023])

# From a JSON batch file
report = download(json_file="data/input/locations.json")
```

### Async entry point
Use `adownload` inside an existing async event loop:

```python
from temporal_svdl import adownload

report = await adownload(lat=43.66, lng=-79.39, target_years=[2015, 2023])
```

### `download` / `adownload` — all arguments

| Argument | Type | Description |
|---|---|---|
| `locations` | `list[Location]` | Pre-built location objects. |
| `json_file` | `str \| Path` | Path to a JSON batch file. |
| `lat`, `lng` | `float` | Single coordinate (no camera control; use `locations=` for that). |
| `url` | `str` | A Google Maps URL. |
| `urls_file` | `str \| Path` | Path to a URL text file. |
| `target_years` | `list[int]` | Years of interest. |
| `all_dates` | `bool` | Download every available historical pano. |
| `year_from` | `int` | Filter: exclude panos before this year. |
| `year_to` | `int` | Filter: exclude panos after this year. |
| `config` | `Config` | Pipeline config (workers, retries, output dir, shared defaults). |
| `confirm` | `bool` | Prompt before downloading (default `True`). |
| `discover_only` | `bool` | Stop after discovery. |
| `download_only` | `bool` | Skip discovery, use cached panos. |
| `refresh_discovery` | `bool` | Ignore cache and re-query. |
| `show_progress` | `bool` | Show Rich progress bars (default `True`). |

Provide exactly one of `locations`, `json_file`, `lat+lng`, `url`, or `urls_file`.

### `list_panos` — inspect available dates

Discovers and returns all available panoramas without downloading anything:

```python
import asyncio
from temporal_svdl import list_panos

# If running in a regular Python script:
panos = asyncio.run(list_panos(lat=43.6629, lng=-79.3957, year_from=2015))

# If running inside a Jupyter notebook:
panos = await list_panos(lat=43.6629, lng=-79.3957, year_from=2015)

# Print the discovered panoramas
for loc_id, history in panos.items():
    for p in history:
        print(p.iso, p.pano_id)
```

### `Report` (Output of `download` / `adownload`)

| Property | Type | Description |
|---|---|---|
| `locations` | `list[Location]` | Locations processed (with resolved headings). |
| `cfg` | `Config` | Config used for the run. |
| `panos_by_loc` | `dict[str, list[HistoricalPano]]` | All discovered panos keyed by location ID. |
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

## CLI

### Quick start

```bash
# Single coordinate — closest pano to each year
temporal-svdl point --lat 43.6629 --lng -79.3957 --years 2015,2020,2023

# Every available date
temporal-svdl point --lat 43.6629 --lng -79.3957 --all-dates

# With explicit heading (omit --heading to aim at the target automatically)
temporal-svdl point --lat 43.6629 --lng -79.3957 --heading 90 --all-dates

# From a Google Maps URL (heading/pitch/FOV extracted automatically when present)
temporal-svdl url --url "https://www.google.com/maps/@43.66,-79.39,17z" --years 2015,2023

# From a text file of URLs
temporal-svdl urls --urls-file data/input/urls.txt --years 2015,2023

# From a JSON batch file (camera settings and years defined per location in the file)
temporal-svdl batch --json-file data/input/locations.json
```

### Explore available dates before downloading

```bash
temporal-svdl list --lat 43.6629 --lng -79.3957
temporal-svdl list --url "https://www.google.com/maps/@43.66,-79.39,17z"
temporal-svdl list --lat 43.6629 --lng -79.3957 --year-from 2015 --year-to 2022
temporal-svdl list --json-file data/input/locations.json
```

### Flags

All download commands (`point`, `url`, `urls`, `batch`) share:

| Flag | Description |
|---|---|
| `-c / --config PATH` | YAML config file (see [Configuration file](#configuration-file-cli-only)). |
| `-o / --output PATH` | Override the output directory. |
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

The `point` command also accepts:

| Flag | Description |
|---|---|
| `--heading DEGREES` | Camera heading (0 = north, 90 = east). Omit to aim at the target automatically. |

### Configuration file (CLI only)

The YAML config file sets shared defaults that apply to every location and controls pipeline
behaviour (workers, retries, logging). It is **not used by the Python API** — Python users pass
a `Config` object directly instead.

Create `configs/config.yaml` (or point to any YAML with `-c`):

```yaml
output_dir: data/output

# Shared camera defaults — applied to any location that does not set its own value.
camera_defaults:
  # heading is omitted → computed automatically for every location.
  # Set heading: 90 here to use the same explicit heading for all locations.
  pitch: 0          # Vertical angle: 0 = horizontal.
  fov: 90           # Field of view in degrees (max 120).
  size: 640x640     # Image dimensions as WIDTHxHEIGHT.
  radius: 50        # Search radius in metres for the nearest panorama.

# Concurrency
discovery_workers: 4    # Parallel GeoPhoto API workers.
download_workers: 16    # Parallel Static API download workers.

# Retry / back-off
max_retries: 5
initial_backoff_seconds: 1.0
max_backoff_seconds: 30.0

# Logging
log_level: INFO         # DEBUG | INFO | WARNING | ERROR
log_file: null          # Path to a log file, or null for console only.
```

All fields are optional — the values above are the defaults.

### JSON batch file

Used with `temporal-svdl batch` (CLI) or `download(json_file=...)` (Python API).

Each entry is one location. All camera fields are optional — unset ones fall back to
`camera_defaults    ` (from the config file for CLI, or from `Config.camera_defaults` for the Python API).
If neither `target_years` nor `all_dates` is set, only the most recent panorama is downloaded.

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
| `lat` | float | — | Latitude in decimal degrees. **Required.** |
| `lng` | float | — | Longitude in decimal degrees. **Required.** |
| `target_years` | list[int] | `[]` | Years of interest. Mutually exclusive with `all_dates`. If both are unset, the latest panorama is downloaded. |
| `all_dates` | bool | `false` | Download every available historical panorama. |
| `year_from` | int | `null` | Exclude panoramas captured before this year. |
| `year_to` | int | `null` | Exclude panoramas captured after this year. |
| `heading` | float | `null` | Compass heading (0 = north, 90 = east). Omit to aim at the target automatically. |
| `pitch` | float | `0` | Vertical angle in degrees (0 = horizontal). |
| `fov` | float | `90` | Horizontal field of view in degrees (max 120). |
| `size` | string | `"640x640"` | Image dimensions as `WIDTHxHEIGHT`. |
| `radius` | int | `50` | Search radius in metres for the nearest panorama. |

### URL text file

One Google Maps URL per line. Blank lines and `#` comments are ignored.
Supports place URLs (`@lat,lng`), Street View URLs (heading/pitch/FOV extracted automatically),
and shortlinks (`goo.gl`, `maps.app.goo.gl`).

```
# Downtown Toronto
https://www.google.com/maps/@43.6532,-79.3832,3a,75y,134h,90t/data=...

# Another location
https://maps.app.goo.gl/abc123
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

Re-running the same command or `download()` call is safe:

- Images already marked `ok` in `manifest.csv` are skipped.
- Locations already in `discovered_panos.json` skip the GeoPhoto query. Use `--refresh-discovery` (CLI) or `refresh_discovery=True` (API) to force a re-query.
- Use `--download-only` / `download_only=True` to skip discovery entirely and reuse the cached pano list.

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
