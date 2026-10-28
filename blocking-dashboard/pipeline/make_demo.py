"""Generate reproducible SYNTHETIC fields; never imply that these are ERA5.

Both methods are actually run on the same synthetic Z500 field. Historical
statistics and contours are derived from their masks, not invented KPI values.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import argparse
import numpy as np
from blocking import detect, daily_climatology, day_key, METHODS
from bundle import save_bundle, REGIONS


def synthetic_fields(dates, latitude, longitude):
    d = np.asarray(dates, dtype="datetime64[D]")
    t = (d - np.datetime64("1980-01-01")).astype(float)[:, None, None]
    lat = np.asarray(latitude)[None, :, None]
    lon = np.asarray(longitude)[None, None, :]
    q = np.abs(lat)
    seasonal = np.cos(2 * np.pi * day_key(d)[:, None, None] / 366)
    field = 5860 - .12 * q ** 2 + 60 * seasonal * np.sign(lat)
    field = field + 32 * np.sin(np.deg2rad(3 * lon) + t * .09) * np.exp(-((q - 50) / 23) ** 2)
    for k, region in enumerate(REGIONS):
        cx, cy = region["center"]
        # Slow stationary episodes, with interannual modulation and zonal drift.
        phase = 2 * np.pi * t / (31 + k * 5) + k * 1.34
        amplitude = np.maximum(0, np.sin(phase)) ** 2 * (390 + 100 * np.cos(t / 480 + k))
        distance = (lon - cx + 180) % 360 - 180
        kernel = np.exp(-(distance / 23) ** 2 - ((lat - cy) / 8.5) ** 2)
        field = field + amplitude * kernel
    return field.astype(np.float32)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=(datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat())
    parser.add_argument("--output", default=str(Path(__file__).parents[1] / "data" / "demo.js"))
    args = parser.parse_args()
    end = np.datetime64(args.end)
    latitude = np.arange(90, -91, -5)
    longitude = np.arange(-180, 180, 5)
    ref_dates = np.arange(np.datetime64("1980-01-01"), np.datetime64("2015-01-01"))
    # Compute reference in year-sized pieces to keep peak memory modest.
    climate_sum = np.zeros((366, len(latitude), len(longitude)), dtype=np.float64)
    climate_count = np.zeros(366, dtype=int)
    for year in range(1980, 2015):
        dates = ref_dates[ref_dates.astype("datetime64[Y]").astype(int) + 1970 == year]
        field = synthetic_fields(dates, latitude, longitude)
        for i, k in enumerate(day_key(dates)):
            climate_sum[k] += field[i]
            climate_count[k] += 1
    climate = (climate_sum / climate_count[:, None, None]).astype(np.float32)
    climate[59] = (climate[58] + climate[60]) / 2
    all_dates, all_masks = [], {k: [] for k in ["ppa", "tr", "pending_ppa", "pending_tr", "valid_ppa", "valid_tr"]}
    latest_fields = None
    last_year = int(str(end)[:4])
    output_lat = latitude[(latitude <= 75) & (latitude >= -75)]
    band_selection = (latitude <= 75) & (latitude >= -75)
    for year in range(1980, last_year + 1):
        start = np.datetime64(f"{year}-01-01")
        stop = min(np.datetime64(f"{year + 1}-01-01"), end + 1)
        # Halo allows cross-year runs to qualify without a January reset.
        dates = np.arange(start - 10, min(stop + 10, end + 1))
        field = synthetic_fields(dates, latitude, longitude)
        result = detect(field, latitude, dates, climate)
        choose = (dates >= start) & (dates < stop)
        all_dates.extend(dates[choose])
        for key in all_masks:
            all_masks[key].append(result[key][choose][:, band_selection, :])
        if year == last_year:
            latest_fields = {"dates": dates[choose], "z500": field[choose][:, band_selection, :],
                             "anomaly": result["anomaly"][choose][:, band_selection, :]}
    masks = {k: np.concatenate(v) for k, v in all_masks.items()}
    metadata = {"source": "synthetic", "title": "Synthetic demonstration · not ERA5 observations",
                "generated_at": datetime.now(timezone.utc).isoformat(), "latest_date": str(end),
                "anomaly_reference": [1980, 2014], "sample_time": "00:00 UTC",
                "grid_degrees": 5, "methods": METHODS, "nh_status": "mirrored extension; author validation pending",
                "regional_bounds_status": "editable illustrative boxes; not transcribed from paper Figure S1",
                "provisional_note": "Short ongoing runs are candidates until temporal persistence is satisfied."}
    print(save_bundle(args.output, all_dates, output_lat, longitude, masks, metadata, latest_fields))


if __name__ == "__main__":
    main()
