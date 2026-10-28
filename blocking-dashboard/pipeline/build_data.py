"""Validate a CDS cache, calculate diagnostics and write the browser ERA5 bundle.

No network access here: can also process monthly NetCDFs exported by the user.
Processing uses yearly windows, with overlap across year boundaries.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
from blocking import METHODS, day_key, detect, geopotential_to_height
from bundle import save_bundle


def read_month(path):
    with xr.open_dataset(path) as ds:
        rename = {k: v for k, v in [("valid_time", "time"), ("latitude", "lat"), ("longitude", "lon")] if k in ds and v not in ds}
        ds = ds.rename(rename)
        if not all(k in ds for k in ["time", "lat", "lon"]):
            raise ValueError(f"Missing time/lat/lon coordinates in {path.name}")
        variable = next((k for k in ["z", "geopotential", "gh", "z500"] if k in ds.data_vars), None)
        if not variable:
            raise ValueError(f"No geopotential variable in {path.name}")
        arr = ds[variable]
        for level in ["pressure_level", "level", "isobaricInhPa"]:
            if level in arr.dims:
                if 500 not in arr[level].values:
                    raise ValueError("500 hPa is absent")
                arr = arr.sel({level: 500})
        if "expver" in arr.dims:
            # Prefer final ERA5 (1), fill only missing values with ERA5T (5).
            versions = sorted(arr.expver.values)
            merged = arr.sel(expver=versions[0], drop=True)
            for version in versions[1:]:
                merged = merged.combine_first(arr.sel(expver=version, drop=True))
            arr = merged
        for dim in list(arr.dims):
            if dim not in ["time", "lat", "lon"]:
                if arr.sizes[dim] != 1:
                    raise ValueError(f"Unexpected dimension {dim} in {path.name}")
                arr = arr.isel({dim: 0}, drop=True)
        arr = arr.assign_coords(lon=((arr.lon + 180) % 360) - 180).sortby("lon").sortby("lat", ascending=False).transpose("time", "lat", "lon")
        times = arr.time.values.astype("datetime64[ns]")
        dates = times.astype("datetime64[D]")
        if np.any(times != dates.astype("datetime64[ns]")):
            raise ValueError("Input must contain instantaneous daily 00:00 UTC samples")
        if len(np.unique(dates)) != len(dates) or np.any(np.diff(dates).astype(int) <= 0):
            raise ValueError("Dates must be unique and increasing")
        units = arr.attrs.get("units", "")
        z500 = geopotential_to_height(arr.values, units)
        if not np.isfinite(z500).any() or np.nanmin(z500) < 2500 or np.nanmax(z500) > 7000:
            raise ValueError("Implausible 500 hPa geopotential height; check variable, units and pressure level")
        lat, lon = arr.lat.values.copy(), arr.lon.values.copy()
        if lat[0] < 90 or lat[-1] > -90:
            raise ValueError("Global -90° to 90° input is required for 15° meridional gradient stencils")
        step = float(lon[1] - lon[0])
        if (not np.allclose(np.diff(lon), step) or not np.allclose(np.diff(lat), -step)
                or not np.isclose(len(lon) * step, 360) or not np.isclose(lon[0], -180)):
            raise ValueError("Expected one global uniform regular grid without a duplicate longitude endpoint")
        return dates, z500, lat, lon


class MonthlyArchive:
    def __init__(self, cache):
        self.paths = sorted(Path(cache).glob("era5-z500-????-??.nc"))
        if not self.paths:
            raise ValueError("No monthly ERA5 NetCDF files found. Run download_era5.py first.")
        self.by_month = {p.stem[-7:]: p for p in self.paths}
        first_dates, first_values, self.latitude, self.longitude = read_month(self.paths[0])
        last_dates, last_values, _, _ = read_month(self.paths[-1])
        self.first = first_dates[np.isfinite(first_values).any(axis=(1, 2))]
        self.last = last_dates[np.isfinite(last_values).any(axis=(1, 2))]
        if not len(self.first) or not len(self.last):
            raise ValueError("First/last cached month has no verified observations")

    def load(self, start, stop):
        dates = np.arange(np.datetime64(start), np.datetime64(stop))
        values = np.full((len(dates), len(self.latitude), len(self.longitude)), np.nan, dtype=np.float32)
        first = dates[0] if len(dates) else np.datetime64(start)
        for month in np.unique(dates.astype("datetime64[M]")):
            path = self.by_month.get(str(month))
            if not path:
                continue
            times, z, lat, lon = read_month(path)
            if not (np.array_equal(lat, self.latitude) and np.array_equal(lon, self.longitude)):
                raise ValueError("All cache files must use the same grid")
            choose = (times >= first) & (times < np.datetime64(stop))
            offsets = (times[choose] - first).astype(int)
            values[offsets] = z[choose]
        return dates, values


def build(cache, output, reference=(1980, 2014), archive_start=None):
    archive = MonthlyArchive(cache)
    start_year = archive_start or int(str(archive.first[0])[:4])
    end_date = archive.last[-1]
    last_year = int(str(end_date)[:4])
    if reference[0] > reference[1] or reference[0] < start_year or reference[1] >= last_year:
        raise ValueError("Use a complete historical anomaly reference within the available archive")
    shape = (366, len(archive.latitude), len(archive.longitude))
    total = np.zeros(shape, dtype=np.float64)
    count = np.zeros(shape, dtype=np.uint16)
    for year in range(reference[0], reference[1] + 1):
        dates, z500 = archive.load(f"{year}-01-01", f"{year+1}-01-01")
        if np.any(~np.isfinite(z500)):
            raise ValueError(f"Reference year {year} contains missing dates/grid cells. Complete the cache first.")
        for i, k in enumerate(day_key(dates)):
            total[k] += z500[i]
            count[k] += 1
    climate = np.divide(total, count, out=np.full(shape, np.nan, dtype=np.float64), where=count > 0).astype(np.float32)
    climate[59] = (climate[58] + climate[60]) / 2
    choose_lat = (archive.latitude >= -75) & (archive.latitude <= 75)
    output_lat = archive.latitude[choose_lat]
    masks = {k: [] for k in ["ppa", "tr", "pending_ppa", "pending_tr", "valid_ppa", "valid_tr"]}
    all_dates, missing_dates, fields = [], [], None
    for year in range(start_year, last_year + 1):
        start = np.datetime64(f"{year}-01-01")
        stop = min(np.datetime64(f"{year+1}-01-01"), end_date + 1)
        dates, z500 = archive.load(start - 10, min(stop + 10, end_date + 1))
        result = detect(z500, archive.latitude, dates, climate)
        choose = (dates >= start) & (dates < stop)
        for key in masks:
            masks[key].append(result[key][choose][:, choose_lat, :])
        all_dates.extend(dates[choose])
        missing_dates.extend(str(d) for d in dates[choose][~np.isfinite(z500[choose]).any(axis=(1, 2))])
        if year == last_year:
            fields = {"dates": dates[choose], "z500": z500[choose][:, choose_lat, :], "anomaly": result["anomaly"][choose][:, choose_lat, :]}
        print(f"Diagnosed {year}: {choose.sum()} calendar days", flush=True)
    metadata = {"source": "ERA5/ERA5T", "title": "ERA5 500 hPa blocking diagnostics",
                "dataset": "reanalysis-era5-pressure-levels", "dataset_doi": "10.24381/cds.bd0915c6",
                "generated_at": datetime.now(timezone.utc).isoformat(), "latest_date": str(end_date),
                "anomaly_reference": list(reference), "sample_time": "00:00 UTC",
                "grid_degrees": float(archive.longitude[1] - archive.longitude[0]), "methods": METHODS,
                "nh_status": "mirrored extension; author validation pending", "missing_dates": missing_dates,
                "regional_bounds_status": "editable illustrative boxes; not transcribed from paper Figure S1",
                "preliminary": "Recent ERA5T may be revised; cache retrieval refreshes the most recent 100 days."}
    print(save_bundle(output, all_dates, output_lat, archive.longitude, {k: np.concatenate(v) for k, v in masks.items()}, metadata, fields, variable="BLOCKING_ERA5_GZIP"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("working-data/era5"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "data" / "era5.js")
    parser.add_argument("--reference-start", type=int, default=1980)
    parser.add_argument("--reference-end", type=int, default=2014)
    parser.add_argument("--archive-start", type=int)
    args = parser.parse_args()
    build(args.cache, args.output, (args.reference_start, args.reference_end), args.archive_start)


if __name__ == "__main__":
    main()
