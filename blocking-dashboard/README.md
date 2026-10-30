# Blocking Observatory — real ERA5 review build

This unpublished review branch adds `blocking-dashboard/` to Prasad Shelke's
GitHub Pages repository. The existing home page, Pages configuration and live
website are unchanged. No deployment or automatic schedule is active.

## Current data connection

The dashboard now loads **real ERA5 / preliminary ERA5T geopotential at 500 hPa**
from [Google Research's public ARCO-ERA5 mirror](https://github.com/google-research/arco-era5).
No CDS account token is required for this public source.

- Displayed observations: **10–19 October 2026**, at **00:00 UTC** each day.
- Retrieved observations: **1–19 October**, providing earlier days for temporal
  persistence at the beginning of the displayed window.
- Latest verified mirror date: **19 October 2026**; source metadata was last
  updated on **25 October 2026**. Availability follows the mirror, not an
  assumed real-time cut-off.
- Grid: **5° grid-point sampling** of the mirror's 0.25° analysis-ready field.
  This is a coarse review grid, configurable in the downloader.
- Available: real Z500 contours, TR blocking masks, pending runs, regional
  weighting, daily calendar, aggregation of the observed sample, and exports.
- **PPA and historical climatology are unavailable** because their historical
  Z500 reference has not been downloaded. Their controls are disabled and
  missing reference values are not represented as zero blocking.
- Dates outside the observed window are visibly unavailable. Monthly, seasonal
  and annual views are labelled incomplete and use actual valid observations.

The observed-data asset is `data/era5.js`; source details are preserved in
`data/era5-provenance.json`. The site does **not** fall back to synthetic data
if this asset is missing. The original demonstration generator/data are
retained only as development fixtures and are no longer loaded by the page.

## View it privately

Open `blocking-dashboard/index.html` after extracting the branch ZIP in a
current browser. All code, geography and observed data are included locally.
The single-file `Blocking_Observatory_ERA5_Preview.html` supplied in the review
handoff can also be downloaded and opened in a browser. Browser file-preview
panes may suppress scripts; open the downloaded HTML file itself.

This source repository is public, so branch source is publicly readable. The
website is not deployed. Do not put a confidential new method into this public
repository.

## Scientific definitions

Method source: Shelke & Renwick (2026), GRL,
[doi:10.1029/2025GL120428](https://doi.org/10.1029/2025GL120428), sections 2.1–2.2.
ERA5 pressure-level dataset:
[doi:10.24381/cds.bd0915c6](https://doi.org/10.24381/cds.bd0915c6).

Convert instantaneous 00:00 UTC geopotential from m² s⁻² to geopotential height
with **Z500 = geopotential / 9.80665**. A daily mean is not substituted.

**PPA (pending historical reference):** anomaly from a gridpoint calendar-day
Z500 climatology, ≥100 m for ≥5 consecutive days. The intended reference is
1980–2014. All days in a qualifying run are blocked. Changing a blocking-
frequency comparison in the UI does not redefine this height reference.

**TR:** use a poleward-positive coordinate `q = abs(latitude)` and
`H(q) = Z500(sign(latitude) * q)`, with Δ = 15°:

```
(H(q) − H(q−15)) / 15 > 0 m/degree
(H(q+15) − H(q)) / 15 < −10 m/degree
(H(q−15) − H(q−30)) / 15 < −5 m/degree
```

All three conditions persist for ≥4 consecutive days. The NH diagnostic uses
an explicitly mirrored version with the same duration and remains an
adaptation requiring author validation against original code. The regional
boxes are editable examples, not an exact transcription of paper Figure S1.

Missing dates and NaNs break persistence. Short ongoing runs remain pending;
qualifying sequences are marked retroactively. Full builds overlap years,
so December–January runs continue. Leap-day height climatology uses the mean
of 28 February and 1 March. DJF belongs to the January/February year.

Blocked area uses cosine-latitude weights over valid cells. Regional blocked
days mean ≥1 confirmed grid cell; equivalent blocked days sum daily area
fractions. These are not object-tracked blocking-event counts. The author's
new detection method has not been invented or implemented here.

## Lossless public-data access and resource limits

The public mirror stores each geopotential time step as a 37-level Blosc
chunk. The downloader reads only the compressed blocks intersecting 500 hPa
using HTTP byte ranges and the public Blosc decoder. It validates coordinates,
units, pressure level, time origin, response ranges, object identity and the
physical plausibility of the resulting height field.

A genuine 19 October field extracted this way was checked **bit-for-bit**
against an independent full 37-level decode. Tests also cover shuffled and
unshuffled blocks, uncompressed chunks, changed dimensions, physical block
ordering and transfer-budget enforcement.

Defaults are deliberately bounded: **2 workers, at most 31 days, 80 MB of
field transfers, and no individual field range larger than 8 MB**. A server
that ignores a range is rejected before its body is downloaded. Complete
monthly cache files are replaced only after validation. No token is stored
in browser assets or source.

To reproduce the current sample, from the repository root:

```bash
python -m pip install -r blocking-dashboard/pipeline/requirements.txt
python blocking-dashboard/pipeline/download_arco.py --cache working-data/era5-arco-recent --start 2026-10-01 --end 2026-10-19 --grid 5 --workers 2 --max-transfer-mb 80 --max-days 19
python blocking-dashboard/pipeline/build_recent.py --cache working-data/era5-arco-recent --start 2026-10-10
python blocking-dashboard/pipeline/make_preview.py --output Blocking_Observatory_ERA5_Preview.html
```

To request the mirror's latest rolling sample, omit `--start` and `--end`.
The downloader then uses the latest 19 verified dates; the exporter displays
10 days with earlier observations available to test persistence.

## Historical backfill — authorized recovery run

A complete historical record is required for PPA, arbitrary climatological
comparisons and full-year statistics. Header-only probes of six representative
source dates estimate **about 41 GB** of public-mirror network transfer for
1980–19 October 2026. The uncompressed sampled NetCDF field volume is about
**182 MB** before filesystem/compression overhead; byte-range extraction does
not retain the much larger full-resolution source chunks.

The user authorized the bounded historical download and removal of raw fields
after retaining and verifying the compact outputs. An earlier chat reported a
completed historical build, but its update was not saved to this branch before
the chat failed. The recovery run is capped at **50 GB**, with **2 workers** and
resumable monthly checkpoints. The cap bounds transfer; reaching it stops the
job and preserves complete cached months.

The concrete recovery commands are:

```bash
python blocking-dashboard/pipeline/download_arco.py --cache working-data/era5-arco-5deg --start 1979-12-22 --end 2026-10-23 --grid 5 --workers 2 --max-transfer-mb 50000 --max-days 17200
python blocking-dashboard/pipeline/build_data.py --cache working-data/era5-arco-5deg --archive-start 1980 --reference-start 1980 --reference-end 2014
```

The December 1979 halo supports January 1980 persistence; the exported archive
starts in 1980. The complete exporter enables both methods and comparison
controls automatically. It also saves the exact float32 fixed height reference
in `data/era5-height-reference.npz` and checksums in `data/era5-manifest.json`.
`verify_retained.py` checks coverage, checksums and masks; with `--cache`, it
independently recomputes historical and recent PPA/TR masks before raw deletion.
`update_compact.py` can merge a recent raw window into the retained history
without downloading the historical record again. `refresh_arco.py` wraps this
in a bounded keyless refresh: two workers, 500 MB and at most 180 daily samples,
with all previously preliminary dates refreshed. It stages and verifies the
updated products before replacing the browser archive and removes its own
temporary raw cache only after success. A ten-day halo protects
persistence across the replacement boundary; original files are preserved
when the recent cache has gaps. Daily update templates remain inactive.

A CDS alternative is retained in `download_era5.py` and the disabled CDS
workflow templates. That alternative needs an accepted CDS dataset licence
and a securely configured API token, as documented by the
[official CDS setup guide](https://cds.climate.copernicus.eu/how-to-api).

## Updates and deployment

`pipeline/era5-arco-recent-update.yml.disabled` is an **inactive** bounded,
keyless recent-data workflow template. It never deploys GitHub Pages. The older
CDS templates also remain inactive. No task, schedule or publication has been
created. Turning a schedule on and publishing the website are separate actions.

## Verification

```bash
python -m pytest blocking-dashboard/tests -q
node --test blocking-dashboard/tests/core.test.cjs
node --check blocking-dashboard/app.js
```

Numerical fixtures verify the algorithms and data handling; the real-field
comparison verifies public-data extraction. These do not replace scientific
validation against the author's original NH/SH implementation.

Map geography is Natural Earth 1:110m public-domain land. D3 7.9.0 is ISC-
licensed. The interaction concept is inspired by [Extreme Weather Data and
Visualization Hub](https://extremewx.org/). See `THIRD_PARTY.md`.


### Compact-archive verification and a single manual refresh

```bash
python blocking-dashboard/pipeline/verify_retained.py --cache working-data/era5-arco-5deg
python blocking-dashboard/pipeline/refresh_arco.py
```

The first command is run before removing the historical raw cache. Later, the
second command reads the retained height reference and only downloads a recent
window. It does not enable a schedule, commit to GitHub, or publish a website.
The saved masks preserve custom blocking-frequency climatologies. Changing the
fixed PPA height reference or detection algorithm later requires raw-data
reprocessing; it cannot be reconstructed from blocking statistics alone.
