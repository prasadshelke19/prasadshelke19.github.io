"""Portable compressed data contract shared by real and synthetic datasets."""
import base64
import gzip
import json
from pathlib import Path
import numpy as np

REGIONS = [
    {"id": "europe", "name": "Europe", "hemisphere": "nh", "bounds": [-15, 35, 40, 75], "center": [13, 56]},
    {"id": "greenland", "name": "Greenland", "hemisphere": "nh", "bounds": [-65, 50, -20, 75], "center": [-43, 64]},
    {"id": "north-pacific", "name": "North Pacific", "hemisphere": "nh", "bounds": [160, 35, -120, 70], "center": [-160, 50]},
    {"id": "ural", "name": "Ural–Siberia", "hemisphere": "nh", "bounds": [40, 40, 90, 75], "center": [65, 58]},
    {"id": "south-pacific", "name": "South Pacific", "hemisphere": "sh", "bounds": [-160, -70, -90, -35], "center": [-126, -52]},
    {"id": "antarctic-peninsula", "name": "Antarctic Peninsula", "hemisphere": "sh", "bounds": [-85, -75, -35, -50], "center": [-60, -63]},
    {"id": "new-zealand", "name": "New Zealand", "hemisphere": "sh", "bounds": [150, -65, -160, -35], "center": [177, -48]},
    {"id": "east-antarctica", "name": "East Antarctica", "hemisphere": "sh", "bounds": [15, -75, 100, -50], "center": [56, -63]},
]


def bits(values):
    return base64.b64encode(np.packbits(np.asarray(values).ravel(), bitorder="little").tobytes()).decode()


def int16(values):
    quantized = np.where(np.isfinite(values), np.rint(values), -32768).astype("<i2")
    # Temporal deltas compress slowly changing height fields well. Modular
    # int16 addition reconstructs the exact quantized values, including NaNs.
    quantized = np.concatenate((quantized[:1], np.diff(quantized, axis=0)), axis=0).astype("<i2")
    return base64.b64encode(quantized.tobytes()).decode()


def save_bundle(path, dates, latitude, longitude, masks, metadata, fields=None, variable="BLOCKING_PAYLOAD_GZIP"):
    payload = {"schema": 1, "meta": metadata,
               "grid": {"latitudes": np.asarray(latitude).tolist(), "longitudes": np.asarray(longitude).tolist()},
               "dates": [str(d)[:10] for d in dates], "regions": REGIONS,
               "masks": {k: bits(v) for k, v in masks.items()}}
    if fields:
        payload["fields"] = {"dates": [str(d)[:10] for d in fields["dates"]], "encoding": "delta-time-i16",
                             "z500": int16(fields["z500"]), "anomaly": int16(fields["anomaly"])}
    raw = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode()
    packed = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    if variable not in {"BLOCKING_PAYLOAD_GZIP", "BLOCKING_ERA5_GZIP"}:
        raise ValueError("Unsupported browser data variable")
    temporary.write_text("window." + variable + "=" + json.dumps(packed) + ";\n")
    temporary.replace(target)
    return {"json_bytes": len(raw), "file_bytes": target.stat().st_size}

