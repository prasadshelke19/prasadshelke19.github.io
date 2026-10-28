"""Export a verified recent ERA5 sample without pretending a baseline is loaded.

Real Z500 and TR are available. PPA and climatology remain explicitly
unavailable until a complete historical reference/archive has been ingested.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import numpy as np
from blocking import METHODS, instantaneous_tr, persist
from build_data import MonthlyArchive
from bundle import save_bundle


def build_recent(cache, output, start=None):
    archive = MonthlyArchive(cache)
    end = archive.last[-1]
    start = end - 9 if start is None else np.datetime64(start)
    dates, height = archive.load(start - 10, end + 1)
    raw, valid = instantaneous_tr(height, archive.latitude)
    tr, pending = persist(raw, dates, 4, valid)
    choose = (dates >= start) & (dates <= end)
    latitude = (archive.latitude >= -75) & (archive.latitude <= 75)
    cut = lambda field: field[choose][:, latitude, :]
    empty = np.zeros_like(cut(tr))
    masks = {"tr": cut(tr), "valid_tr": cut(valid), "pending_tr": cut(pending),
             "ppa": empty, "valid_ppa": empty, "pending_ppa": empty}
    provenance = json.loads((Path(cache) / "source.json").read_text())
    metadata = {"source": "ERA5/ERA5T", "title": "Recent observed ERA5 sample",
                "source_provider": provenance["provider"], "source_url": provenance["store"],
                "source_last_updated": provenance["source_attributes"]["last_updated"],
                "dataset": "reanalysis-era5-pressure-levels", "dataset_doi": "10.24381/cds.bd0915c6",
                "generated_at": datetime.now(timezone.utc).isoformat(), "latest_date": str(end),
                "display_start": str(start), "retrieved_start": str(archive.first[0]),
                "anomaly_reference": [1980, 2014], "reference_available": False,
                "available_methods": ["tr"], "available_fields": ["z500"],
                "coverage_note": "Recent observed sample only. Historical reference not loaded; PPA and climatology are unavailable.",
                "sample_time": "00:00 UTC", "grid_degrees": float(archive.longitude[1] - archive.longitude[0]),
                "native_grid_degrees": .25, "resampling": provenance["resampling"],
                "final_era5_through": provenance["final_era5_through"], "methods": METHODS,
                "nh_status": "mirrored extension; author validation pending",
                "regional_bounds_status": "editable illustrative boxes; author review pending"}
    fields = {"dates": dates[choose], "z500": cut(height), "anomaly": np.full_like(cut(height), np.nan)}
    result = save_bundle(output, dates[choose], archive.latitude[latitude], archive.longitude,
                         masks, metadata, fields, variable="BLOCKING_ERA5_GZIP")
    (Path(output).parent / "era5-provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print({"start": str(start), "end": str(end), "days": int(choose.sum()), **result})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("working-data/era5-arco-recent"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "data" / "era5.js")
    parser.add_argument("--start")
    args = parser.parse_args()
    build_recent(args.cache, args.output, args.start)
