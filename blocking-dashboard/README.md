# Blocking Observatory — unpublished review build

An offline-capable atmospheric blocking explorer for Prasad Shelke's GitHub
Pages repository. This branch adds a self-contained `blocking-dashboard/`
directory; it does not change the existing home page, Pages settings, or
deployment branch. No deployment or schedule is enabled.

## View it privately

Download this branch as a ZIP, extract it, and open
`blocking-dashboard/index.html` in a current Chrome, Edge, Firefox, or Safari.
The scripts, geography and demonstration data are bundled locally. No server,
API token or internet connection is needed to explore the preview. The data
loader needs browser support for `DecompressionStream('gzip')`.

A single-file `Blocking_Observatory_Preview.html` is also supplied with the
review handoff. Download it and open it in a browser. Browser file-preview
panes may suppress JavaScript; use the actual downloaded file.

The source repository is public, so a review branch is publicly readable source.
The dashboard itself is **not deployed**. Do not put confidential data or a
new unpublished method into this public repository.

## What works

- Global 30°–75° maps for both hemispheres, hemisphere filters and regional zoom.
- PPA and TR diagnostics calculated on the same underlying synthetic Z500 fields.
- Daily anomaly/height contours with confirmed and pending blocking outlines.
- Daily blocking masks; monthly, seasonal, annual and custom-reference frequency maps.
- Date picker, previous/next day, animation, interactive calendar and shareable state.
- Region-specific area weighting, blocked-day counts, equivalent blocked days,
  daily/monthly/seasonal/annual series and a monthly climatological comparison.
- Reference years plus all-year, seasonal or monthly climatology maps.
- CSV and SVG export, keyboard-operable controls and responsive layout.

The controls operate on an explicitly labelled **synthetic** archive from
1980 through 23 October 2026. It is not a record of actual weather or ERA5
conditions. A deterministic generator constructs height fields and runs the
same scientific code as the real-data pipeline. No KPI is hard-coded as an
observed blocking statistic. Maps deliberately use a coarse 5° demonstration
grid. Fields are quantized to metres **after** detection for compact display;
this does not change the detector thresholds.

## Scientific definitions and review points

Primary source: Shelke, P. B., & Renwick, J. A. (2026), *Southern Hemispheric
atmospheric blocking patterns in CESM-LENS2: Effects of reversal versus anomaly
approaches*, GRL, doi:[10.1029/2025GL120428](https://doi.org/10.1029/2025GL120428),
sections 2.1–2.2.

Input is daily instantaneous **00:00 UTC geopotential at 500 hPa**, rather than
a daily mean. Convert geopotential (m² s⁻²) to geopotential height (m) by
dividing by **9.80665**. The pressure-level CDS dataset is
[`reanalysis-era5-pressure-levels`](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels),
doi:[10.24381/cds.bd0915c6](https://doi.org/10.24381/cds.bd0915c6).

**PPA:** subtract a calendar-day height climatology at every grid point. An
anomaly **≥100 m for ≥5 consecutive days** qualifies. Every day in the run
is included. The default height reference is **1980–2014**, matching the
paper's present-day analysis period. Rebuilding with another height reference
requires the pipeline, not merely changing the frequency comparison in the UI.

**TR:** define `q = abs(latitude)` increasing poleward and
`H(q) = Z500(sign(latitude) * q)`. With Δ=15°:

```
equatorward gradient = (H(q) − H(q−15)) / 15 > 0 m/degree
poleward gradient   = (H(q+15) − H(q)) / 15 < −10 m/degree
subtropical gradient= (H(q−15) − H(q−30)) / 15 < −5 m/degree
```

All conditions must hold at a grid point for **≥4 consecutive days**. A
poleward-positive coordinate makes the SH sign convention explicit. Numerical
tests verify symmetric responses to mirrored NH/SH fields and rejection of a
normal westerly profile. **The NH version is an adaptation, with the same
four-day setting, not a validated claim from this SH paper. Compare both
implementations with the author's original code before scientific release.**

Other declared choices:

- Gap days and NaNs break persistence. Missing cells are excluded from
  denominators, not treated as unblocked cells.
- Runs cross year boundaries through overlapping processing windows. A short
  ongoing run is pending. Once it qualifies, the complete run is marked.
- Calendar-day keys use month/day; 29 February's height reference is the mean
  of 28 February and 1 March. No unstated smoothing is applied.
- DJF belongs to the year containing January/February. A missing preceding
  December makes that season incomplete; this is displayed.
- Frequency = confirmed blocked samples / valid samples. Incomplete periods
  are labelled and future days are unavailable, not zero.
- Area weights are cosine(latitude), on a regular latitude–longitude grid.
  Regional blocked days use at least one confirmed cell; equivalent blocked
  days are the sum of daily area fractions. Neither is an object-tracked event count.
- Regional boxes are editable examples in `pipeline/bundle.py`, **not** claimed
  exact transcriptions of Figure S1. The supplement was not retrievable in this
  session. Replace with the author's exact regional bounds during validation.
- The new unpublished method has not been invented or implemented. Add it
  later through the diagnostic output/schema and matching UI controls.

## Connect real ERA5 without exposing a token

The current handoff has no CDS credentials and contains no observed ERA5 data.
Configure the account locally or use an encrypted GitHub Actions secret; never
place the token in JavaScript, a commit, a URL, or the data directory.

1. Follow the official [CDS API setup](https://cds.climate.copernicus.eu/how-to-api)
   and accept the pressure-level dataset licence on CDS.
2. From the repository root, install the processing dependencies:

   ```bash
   python -m pip install -r blocking-dashboard/pipeline/requirements.txt
   ```

3. Set `CDSAPI_KEY` securely in your execution environment, or use your existing
   local `.cdsapirc` (git-ignored). Bootstrap the monthly archive:

   ```bash
   python blocking-dashboard/pipeline/download_era5.py --start-year 1980 --grid 2.5
   python blocking-dashboard/pipeline/build_data.py --reference-start 1980 --reference-end 2014
   ```

   Downloading decades of global fields is an initial data-preparation job,
   potentially hours or longer depending on the CDS queue. Downloads are
   cached as `working-data/era5/era5-z500-YYYY-MM.nc`, outside public browser
   assets. Interrupted jobs can be resumed. The detector processes one year
   at a time; each file must use one consistent global grid. Grid resolution
   is configurable; re-bootstrap into a separate cache if you change it.

4. If matching ERA5 files are already available on your research system, place
   the monthly NetCDFs into that cache and run only `build_data.py`. It accepts
   common CDS dimension names, 500-hPa levels, longitude conventions, and
   final/preliminary `expver` mixtures. It rejects incorrect units, times,
   pressure levels, grids and implausible heights.
5. A successful build atomically replaces `data/era5.js` with a verified
   observed-data bundle. The website automatically prefers it over demo data
   and changes the source notices. A failed build retains the previous bundle.

ERA5T is usually about **five days delayed**, and preliminary fields can later
be revised. The date is UTC and comes from verified records, not the computer's
display date. Retrieval refreshes the last 100 days to pick up final ERA5.
Daily samples at the newest persistence edge may still be pending.

The first production baseline must contain every reference day and grid
cell. Outside the reference, missing days are preserved and visibly unavailable.
The baseline is not recomputed in the browser. Changing the comparison years
there recomputes the selected **blocking frequency** climatology from the
existing archive.

## Daily updates — deliberately inactive

`pipeline/era5-update.yml.disabled` is a reviewed workflow **template** outside
`.github/workflows`. It cannot execute. It retrieves/validates data and
commits only the resulting observed-data asset; it contains no Pages deploy.
Its proposed daily schedule is 15:35 UTC, after the usual ERA5T availability
window, without assuming availability is guaranteed.

When the data/methods are validated and daily updates are wanted:

1. Seed a runner-accessible historical cache. The separate disabled bootstrap
   workflow can retrieve year ranges in resumable jobs; do this before enabling
   the daily template.
2. Configure the encrypted repository secret `CDSAPI_KEY`.
3. Copy the desired templates into `.github/workflows/` on the chosen default
   branch. Scheduled GitHub Actions run from the default branch; a feature
   branch alone does not activate them.
4. Choose deployment of the dashboard separately, after review. Publishing is
   not part of either data workflow and has not been performed here.

`github-actions[bot]` pushes normally do not trigger another workflow; if
Pages is eventually built with a custom Actions workflow, combine the data
job and deployment explicitly at that stage. Do not assume updating the data
asset automatically publishes a Pages build.

## Reproduce checks and the demonstration

```bash
python -m pytest blocking-dashboard/tests -q
node --test blocking-dashboard/tests/core.test.cjs
node --check blocking-dashboard/app.js
python blocking-dashboard/pipeline/make_demo.py --end 2026-10-23
```

Tests cover sign conventions, strict gradient inequalities, persistence,
retroactivity, missing days/cells, New Year continuity, leap days, date-line
regions, actual denominators, CDS request fields, NetCDF normalization and a
complete ERA5-format-to-browser-bundle integration. These use controlled
fixtures; they are not empirical validation against actual ERA5 or author code.

## Attribution

The interaction concept is inspired by [Extreme Weather Data and Visualization
Hub](https://extremewx.org/). The layout, blocking application and code here are
new; no claim of affiliation is made. Map land is Natural Earth 1:110m public
domain geography. D3 v7.9.0 is distributed under ISC; its licence is bundled
at `assets/d3-LICENSE`. See `THIRD_PARTY.md`.
