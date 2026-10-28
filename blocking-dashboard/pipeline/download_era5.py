"""Retrieve monthly ERA5 500-hPa geopotential at 00:00 UTC from CDS.

Uses CDSAPI_KEY from the environment, or the user's existing cdsapi config.
Credentials are never written into this repository or browser assets.
"""
from __future__ import annotations
import argparse
import calendar
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path


def request_for_month(year, month, last_day, grid=2.5):
    return {"product_type": ["reanalysis"], "variable": ["geopotential"],
            "pressure_level": ["500"], "year": [str(year)], "month": [f"{month:02d}"],
            "day": [f"{d:02d}" for d in range(1, last_day + 1)], "time": ["00:00"],
            "data_format": "netcdf", "download_format": "unarchived", "grid": [grid, grid]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=1980)
    parser.add_argument("--end-date", default=(datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat())
    parser.add_argument("--cache", type=Path, default=Path("working-data/era5"))
    parser.add_argument("--grid", type=float, default=2.5)
    parser.add_argument("--refresh-days", type=int, default=100,
                        help="Re-request recent months to incorporate final ERA5 replacing ERA5T")
    args = parser.parse_args()
    end = date.fromisoformat(args.end_date)
    if args.start_year < 1940 or args.start_year > end.year:
        parser.error("ERA5 start year must be between 1940 and the end date")
    if args.grid <= 0 or abs(180 / args.grid - round(180 / args.grid)) > 1e-8:
        parser.error("Grid must divide 180 degrees exactly")
    import cdsapi
    token = os.getenv("CDSAPI_KEY")
    client = cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=token) if token else cdsapi.Client()
    args.cache.mkdir(parents=True, exist_ok=True)
    refresh_after = end - timedelta(days=args.refresh_days)
    for year in range(args.start_year, end.year + 1):
        for month in range(1, 13):
            start = date(year, month, 1)
            if start > end:
                break
            last = min(calendar.monthrange(year, month)[1], end.day if (year, month) == (end.year, end.month) else 31)
            path = args.cache / f"era5-z500-{year}-{month:02d}.nc"
            month_end = date(year, month, last)
            if path.exists() and month_end < refresh_after:
                continue
            print(f"Retrieving {year}-{month:02d}: {last} daily 00:00 samples on {args.grid}° grid", flush=True)
            temporary = path.with_suffix(".download.nc")
            client.retrieve("reanalysis-era5-pressure-levels", request_for_month(year, month, last, args.grid), str(temporary))
            # Validate before replacing any previously good cached observations.
            from build_data import read_month
            times, _, _, _ = read_month(temporary)
            expected = np_dates(year, month, last)
            if not (times.shape == expected.shape and (times == expected).all()):
                temporary.unlink(missing_ok=True)
                raise ValueError(f"Incomplete or unexpected dates in {year}-{month:02d}; old cache retained")
            temporary.replace(path)
    print("Retrieval complete. Run build_data.py to validate, diagnose and export the archive.")


def np_dates(year, month, last):
    import numpy as np
    return np.arange(np.datetime64(f"{year}-{month:02d}-01"), np.datetime64(f"{year}-{month:02d}-{last:02d}") + 1)


if __name__ == "__main__":
    main()
