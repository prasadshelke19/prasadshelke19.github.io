"""Verify compact products and optionally cross-check real raw ERA5 samples."""
from __future__ import annotations
import argparse
import calendar
import hashlib
import json
from pathlib import Path
import numpy as np
from build_data import MonthlyArchive
from update_compact import read_bundle


def runs(raw, days):
    """Independent run-boundary implementation for validation only."""
    flat = raw.reshape(len(raw), -1)
    confirmed = np.zeros_like(flat)
    pending = np.zeros_like(flat)
    for cell in range(flat.shape[1]):
        edges = np.diff(np.r_[False, flat[:, cell], False].astype(np.int8))
        starts, stops = np.where(edges == 1)[0], np.where(edges == -1)[0]
        for start, stop in zip(starts, stops):
            if stop - start >= days:
                confirmed[start:stop, cell] = True
            elif stop == len(raw):
                pending[start:stop, cell] = True
    return confirmed.reshape(raw.shape), pending.reshape(raw.shape)


def cross_check(data, reference, cache, start, stop):
    archive = MonthlyArchive(cache)
    start, stop = np.datetime64(start), np.datetime64(stop)
    dates, height = archive.load(start - 10, min(stop + 11, np.datetime64(data["dates"][-1]) + 1))
    if not np.isfinite(height).all():
        raise ValueError("Raw validation sample contains gaps")
    latitude = archive.latitude
    band = (latitude >= -75) & (latitude <= 75)
    key = np.asarray([(np.datetime64("2000" + str(day)[4:]) - np.datetime64("2000-01-01")).astype(int) for day in dates])
    anomaly = height - reference["z500_climatology"][key]
    in_domain = ((abs(latitude) >= 30) & (abs(latitude) <= 75))[None, :, None]
    expected = {}
    expected["ppa"], expected["pending_ppa"] = runs((anomaly >= 100) & in_domain, 5)
    candidate = np.zeros_like(height, dtype=bool)
    for j, lat in enumerate(latitude):
        if not 30 <= abs(lat) <= 75:
            continue
        s = 1 if lat > 0 else -1
        get = lambda q: height[:, np.where(latitude == s * q)[0][0], :]
        q = abs(lat)
        candidate[:, j] = ((get(q) - get(q - 15)) / 15 > 0) & ((get(q + 15) - get(q)) / 15 < -10) & ((get(q - 15) - get(q - 30)) / 15 < -5)
    expected["tr"], expected["pending_tr"] = runs(candidate, 4)
    chosen = (dates >= start) & (dates <= stop)
    old_dates = np.asarray(data["dates"], dtype="datetime64[D]")
    positions = np.searchsorted(old_dates, dates[chosen])
    if not np.array_equal(old_dates[positions], dates[chosen]):
        raise ValueError("Validation dates are absent from the retained archive")
    for name, values in expected.items():
        if not np.array_equal(values[chosen][:, band], data["masks"][name][positions]):
            raise ValueError(f"Independent raw-data check failed for {name}")
    # Independent weighted summary for an actual regional historical season.
    lat, lon = np.asarray(data["grid"]["latitudes"]), np.asarray(data["grid"]["longitudes"])
    europe = (lat[:, None] >= 35) & (lat[:, None] <= 75) & (lon[None, :] >= -15) & (lon[None, :] <= 40)
    weights = np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], europe.shape)[europe]
    summary = {}
    for name in ["ppa", "tr"]:
        fractions = (expected[name][chosen][:, band][:, europe] * weights).sum(axis=1) / weights.sum()
        summary[name] = {"mean_blocked_area_percent": float(100 * fractions.mean()),
                         "regional_blocked_days": int(np.count_nonzero(fractions)),
                         "equivalent_blocked_days": float(fractions.sum())}
    return {"from": str(start), "through": str(stop), "days": int(chosen.sum()),
            "checked": "Both hemispheres: exact PPA/TR and pending-mask agreement with independent run-boundary calculation",
            "europe_summary": summary}


def verify(directory, cache=None):
    directory = Path(directory)
    manifest = json.loads((directory / "era5-manifest.json").read_text())
    for name, identity in manifest["products"].items():
        path = directory / name
        if path.stat().st_size != identity["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != identity["sha256"]:
            raise ValueError(f"Retained product checksum mismatch: {name}")
    data = read_bundle(directory / "era5.js")
    dates = np.asarray(data["dates"], dtype="datetime64[D]")
    if not np.array_equal(dates, np.arange(dates[0], dates[-1] + 1)) or len(dates) != manifest["days"]:
        raise ValueError("Retained date history is not complete and continuous")
    if data["meta"].get("missing_dates") or manifest["missing_dates"]:
        raise ValueError("Historical build has missing observations")
    for method in ["ppa", "tr"]:
        confirmed, pending, valid = [data["masks"][prefix + method] for prefix in ["", "pending_", "valid_"]]
        if np.any(confirmed & pending) or np.any((confirmed | pending) & ~valid):
            raise ValueError(f"Invalid {method} mask relationships")
        duration = data["meta"]["methods"][method]["persistence_days"]
        if pending[:-duration + 1].any():
            raise ValueError(f"Historical {method} days incorrectly remain pending")
        lat = np.asarray(data["grid"]["latitudes"])
        band = (abs(lat) >= 30) & (abs(lat) <= 75)
        if not valid[:, band].all() or valid[:, ~band].any():
            raise ValueError(f"Invalid {method} observation coverage")
    with np.load(directory / "era5-height-reference.npz", allow_pickle=False) as file:
        reference = {key: file[key] for key in file.files}
    climate = reference["z500_climatology"]
    if not np.isfinite(climate).all() or not np.array_equal(climate[59], (climate[58] + climate[60]) / 2):
        raise ValueError("Invalid height climatology or leap-day reference")
    years = reference["reference_years"].tolist()
    counts = reference["sample_counts"]
    expected_counts = np.full(366, years[1] - years[0] + 1)
    expected_counts[59] = sum(calendar.isleap(year) for year in range(years[0], years[1] + 1))
    if not np.all(counts == expected_counts[:, None, None]):
        raise ValueError("Height climatology has incomplete reference-year sampling")
    report = {"status": "passed", "archive_start": str(dates[0]), "archive_end": str(dates[-1]),
              "days": len(dates), "grid_degrees": data["meta"]["grid_degrees"],
              "height_reference": years, "product_checksums": "passed", "coverage_and_masks": "passed",
              "retained_bytes": sum(p["bytes"] for p in manifest["products"].values())}
    if cache:
        checks = []
        if dates[0] <= np.datetime64("2020-06-01") and dates[-1] >= np.datetime64("2020-08-31"):
            checks.append(cross_check(data, reference, cache, "2020-06-01", "2020-08-31"))
        checks.append(cross_check(data, reference, cache, str(dates[-1] - 13), str(dates[-1])))
        report["independent_raw_checks"] = checks
    (directory / "era5-verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path(__file__).parents[1] / "data")
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.data, args.cache), indent=2))
