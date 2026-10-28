from pathlib import Path
import sys
import base64
import gzip
import json
import numpy as np
import xarray as xr
sys.path.insert(0, str(Path(__file__).parents[1] / "pipeline"))
from build_recent import build_recent
from blocking import G0


def test_recent_export_never_represents_an_unloaded_ppa_reference_as_unblocked(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    lat, lon = np.arange(90, -91, -15), np.arange(0, 360, 15)
    dates = np.arange(np.datetime64("2026-10-01"), np.datetime64("2026-10-20"))
    q = [0, 15, 30, 45, 60, 75, 90]
    h = [6000, 5700, 5400, 5500, 5200, 4900, 4600]
    height = np.broadcast_to(np.interp(abs(lat), q, h)[None, :, None], (19, len(lat), len(lon)))
    ds = xr.Dataset({"z": (("time", "latitude", "longitude"), height * G0, {"units": "m**2 s**-2"})},
                    coords={"time": dates, "latitude": lat, "longitude": lon})
    ds.to_netcdf(cache / "era5-z500-2026-10.nc")
    (cache / "source.json").write_text(json.dumps({"provider": "Test fixture", "store": "fixture", "source_attributes": {"last_updated": "2026-10-25"}, "resampling": "test grid", "final_era5_through": "2026-06-30"}))
    output = tmp_path / "era5.js"
    build_recent(cache, output, "2026-10-10")
    encoded = json.loads(output.read_text().split("=", 1)[1].strip().rstrip(";"))
    data = json.loads(gzip.decompress(base64.b64decode(encoded)))
    assert data["dates"] == [str(d) for d in dates[-10:]]
    assert data["meta"]["reference_available"] is False
    assert data["meta"]["available_methods"] == ["tr"]
    assert data["meta"]["available_fields"] == ["z500"]
    valid_ppa = base64.b64decode(data["masks"]["valid_ppa"])
    assert not any(valid_ppa)
    n = len(data["dates"]) * len(data["grid"]["latitudes"]) * len(data["grid"]["longitudes"])
    tr = np.unpackbits(np.frombuffer(base64.b64decode(data["masks"]["tr"]), dtype=np.uint8), bitorder="little")[:n]
    assert tr.any()
