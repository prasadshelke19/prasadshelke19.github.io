"""Refresh a compact blocking history using only a recent ERA5 raw cache.

The 1980-2014 height reference is fixed. Old blocking masks are preserved;
overlapping recent masks are re-diagnosed, including ERA5T revisions and runs
across the old endpoint. No historical raw-height archive is required.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
from blocking import detect
from build_data import MonthlyArchive
from bundle import save_bundle


def read_bundle(path):
    text = Path(path).read_text()
    if not text.startswith("window.BLOCKING_ERA5_GZIP="):
        raise ValueError("Expected an observed ERA5 bundle")
    data = json.loads(gzip.decompress(base64.b64decode(json.loads(text.split("=", 1)[1].strip().rstrip(";")))))
    dates = np.asarray(data["dates"], dtype="datetime64[D]")
    shape = (len(dates), len(data["grid"]["latitudes"]), len(data["grid"]["longitudes"]))
    for key, encoded in data["masks"].items():
        bits = np.unpackbits(np.frombuffer(base64.b64decode(encoded), dtype=np.uint8), bitorder="little")
        if len(bits) < np.prod(shape):
            raise ValueError("Truncated blocking mask")
        data["masks"][key] = bits[:np.prod(shape)].reshape(shape).astype(bool)
    if data.get("fields"):
        fields = data["fields"]
        fields["dates"] = np.asarray(fields["dates"], dtype="datetime64[D]")
        for key in ["z500", "anomaly"]:
            values = np.frombuffer(base64.b64decode(fields[key]), dtype="<i2").reshape((-1,) + shape[1:])
            if fields.get("encoding") == "delta-time-i16":
                values = np.cumsum(values.astype(np.int64), axis=0).astype(np.int16)
            fields[key] = np.where(values == -32768, np.nan, values).astype(np.float32)
    return data


def write_manifest(output, metadata):
    output = Path(output)
    provenance_path = output.parent / "era5-provenance.json"
    provenance_path.write_text(json.dumps(metadata, indent=2) + "\n")
    paths = [output, output.parent / "era5-height-reference.npz", provenance_path]
    manifest = {"schema": 1, "archive_start": metadata["display_start"],
                "archive_end": metadata["latest_date"], "days": metadata["archive_days"],
                "missing_dates": metadata["missing_dates"], "anomaly_reference": metadata["anomaly_reference"],
                "products": {p.name: {"bytes": p.stat().st_size,
                                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths}}
    (output.parent / "era5-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def update(cache, output, reference_path=None):
    output = Path(output)
    old = read_bundle(output)
    if old["meta"].get("reference_available") is not True:
        raise ValueError("A complete historical build is required before incremental updates")
    reference_path = Path(reference_path or output.parent / "era5-height-reference.npz")
    manifest = json.loads((output.parent / "era5-manifest.json").read_text())
    identity = manifest["products"]["era5-height-reference.npz"]
    if hashlib.sha256(reference_path.read_bytes()).hexdigest() != identity["sha256"]:
        raise ValueError("The retained height reference has changed; original history preserved")
    with np.load(reference_path, allow_pickle=False) as reference:
        climate = reference["z500_climatology"].copy()
        ref_lat, ref_lon = reference["latitude"], reference["longitude"]
        if reference["reference_years"].tolist() != old["meta"]["anomaly_reference"]:
            raise ValueError("The fixed height reference differs from the retained history")
    archive = MonthlyArchive(cache)
    if not (np.array_equal(ref_lat, archive.latitude) and np.array_equal(ref_lon, archive.longitude)):
        raise ValueError("Recent data and the retained height reference use different grids")
    raw_dates, height = archive.load(archive.first[0], archive.last[-1] + 1)
    if not np.isfinite(height).all():
        raise ValueError("Recent cache has missing dates or values; original history preserved")
    old_dates = np.asarray(old["dates"], dtype="datetime64[D]")
    replace_from = max(old_dates[0], raw_dates[0] + 10)
    if raw_dates[-1] < old_dates[-1] or replace_from > old_dates[-1] + 1 or replace_from > raw_dates[-1]:
        raise ValueError("Recent cache must overlap the old endpoint, include ten halo days and reach its latest date")
    result = detect(height, archive.latitude, raw_dates, climate)
    band = (archive.latitude >= -75) & (archive.latitude <= 75)
    if not (np.array_equal(archive.latitude[band], old["grid"]["latitudes"])
            and np.array_equal(archive.longitude, old["grid"]["longitudes"])):
        raise ValueError("Recent data use a different browser grid")
    keep, replace = old_dates < replace_from, raw_dates >= replace_from
    dates = np.concatenate([old_dates[keep], raw_dates[replace]])
    if np.any(np.diff(dates).astype(int) != 1):
        raise ValueError("The updated history would contain a date gap")
    masks = {key: np.concatenate([old["masks"][key][keep], result[key][replace][:, band]]) for key in old["masks"]}
    year_start = dates[-1].astype("datetime64[Y]").astype("datetime64[D]")
    previous_fields = old.get("fields")
    if previous_fields is None:
        raise ValueError("The retained archive has no current-year display fields")
    keep_fields = (previous_fields["dates"] >= year_start) & (previous_fields["dates"] < replace_from)
    new_fields = replace & (raw_dates >= year_start)
    fields = {"dates": np.concatenate([previous_fields["dates"][keep_fields], raw_dates[new_fields]])}
    for key, values in [("z500", height), ("anomaly", result["anomaly"])]:
        fields[key] = np.concatenate([previous_fields[key][keep_fields], values[new_fields][:, band]])
    if not np.array_equal(fields["dates"], np.arange(year_start, dates[-1] + 1)):
        raise ValueError("The updated current-year field record would have a gap")
    provenance = json.loads((Path(cache) / "source.json").read_text())
    metadata = dict(old["meta"])
    metadata.update({"generated_at": datetime.now(timezone.utc).isoformat(), "latest_date": str(dates[-1]),
                     "archive_days": len(dates), "source_last_updated": provenance["source_attributes"]["last_updated"],
                     "final_era5_through": provenance["final_era5_through"], "recent_reprocessed_from": str(replace_from),
                     "source_provider": provenance["provider"], "source_url": provenance["store"]})
    save_bundle(output, dates, archive.latitude[band], archive.longitude, masks, metadata, fields, variable="BLOCKING_ERA5_GZIP")
    return write_manifest(output, metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "data" / "era5.js")
    args = parser.parse_args()
    print(update(args.cache, args.output))
