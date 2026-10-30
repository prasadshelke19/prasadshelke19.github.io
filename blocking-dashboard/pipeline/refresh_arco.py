"""One bounded recent-only refresh of the saved historical dashboard.

No scheduler or deployment is enabled by this script. The recent raw cache
is temporary and removed only after retained-product verification succeeds.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np
from download_arco import retrieve, get_json
from update_compact import read_bundle, update
from verify_retained import verify


def refresh(output, max_transfer_mb=500, max_days=180):
    output = Path(output).resolve()
    # Check the durable products before using their reference and date history.
    verify(output.parent)
    data = read_bundle(output)
    old_end = np.datetime64(data["dates"][-1])
    attributes = get_json(".zattrs")
    end = np.datetime64(attributes.get("valid_time_stop_era5t", attributes["valid_time_stop"])[:10])
    if end < old_end:
        raise ValueError("The mirror is older than the saved archive; no update performed")
    # Refresh all previously preliminary observations, plus a rolling window.
    # A ten-day halo lets persistence be diagnosed before replacing old masks.
    first_preliminary = np.datetime64(data["meta"]["final_era5_through"][:10]) + 1
    start = min(old_end - 100, first_preliminary) - 10
    if int((end - start).astype(int)) + 1 > max_days:
        raise ValueError("The archive is too stale for the bounded recent-only refresh; extend the explicit limits for a manual catch-up")
    cache = Path(tempfile.mkdtemp(prefix="blocking-era5-refresh-"))
    try:
        retrieve(cache, str(start), str(end), grid=data["meta"]["grid_degrees"], workers=2,
                 refresh_days=max_days, max_transfer_mb=max_transfer_mb, max_days=max_days)
        # Diagnose and validate a complete staged copy before replacing any
        # working product. Publish the browser bundle last.
        with tempfile.TemporaryDirectory(prefix=".era5-stage-", dir=output.parent) as directory:
            stage = Path(directory)
            for name in [output.name, "era5-height-reference.npz", "era5-provenance.json", "era5-manifest.json"]:
                shutil.copy2(output.parent / name, stage / name)
            update(cache, stage / output.name)
            report = verify(stage)
            for name in ["era5-provenance.json", "era5-manifest.json", "era5-verification.json", output.name]:
                (stage / name).replace(output.parent / name)
    except Exception:
        print(f"Refresh stopped. Complete temporary cache months remain at {cache}", flush=True)
        raise
    shutil.rmtree(cache)
    print(json.dumps({"updated_through": str(end), "days": report["days"],
                      "retained_bytes": report["retained_bytes"], "temporary_raw_cache_removed": True}, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "data" / "era5.js")
    parser.add_argument("--max-transfer-mb", type=float, default=500)
    parser.add_argument("--max-days", type=int, default=180)
    args = parser.parse_args()
    refresh(args.output, args.max_transfer_mb, args.max_days)
