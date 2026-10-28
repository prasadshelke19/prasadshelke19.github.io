"""Exercise the complete ERA5-format -> diagnosed browser bundle path offline."""
from pathlib import Path
import sys
import base64
import gzip
import json
import numpy as np
import xarray as xr
sys.path.insert(0, str(Path(__file__).parents[1] / "pipeline"))
from build_data import build


def test_real_format_pipeline_end_to_end(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    lat, lon = np.arange(90, -91, -15), np.arange(0, 360, 15)
    for month in np.arange(np.datetime64("2024-01"), np.datetime64("2026-02")):
        start = month.astype("datetime64[D]")
        stop = (month + 1).astype("datetime64[D]") if str(month) != "2026-01" else np.datetime64("2026-01-06")
        dates = np.arange(start, stop)
        field = np.broadcast_to((6000 - .1 * lat ** 2)[None, :, None], (len(dates), len(lat), len(lon))).copy()
        if str(month) == "2026-01":
            field[:, lat == 45, :] += 100
        ds = xr.Dataset({"z": (("valid_time", "pressure_level", "latitude", "longitude"), field[:, None], {"units": "m"})},
                        coords={"valid_time": dates, "pressure_level": [500], "latitude": lat, "longitude": lon})
        ds.to_netcdf(cache / f"era5-z500-{month}.nc")
    output = tmp_path / "era5.js"
    build(cache, output, (2024, 2025))
    text = output.read_text()
    assert text.startswith("window.BLOCKING_ERA5_GZIP=")
    encoded = json.loads(text.split("=", 1)[1].strip().rstrip(";"))
    data = json.loads(gzip.decompress(base64.b64decode(encoded)))
    assert data["meta"]["source"] == "ERA5/ERA5T"
    assert data["meta"]["latest_date"] == "2026-01-05"
    assert data["meta"]["missing_dates"] == []
    assert len(data["dates"]) == 366 + 365 + 5
    bits = np.unpackbits(np.frombuffer(base64.b64decode(data["masks"]["ppa"]), dtype=np.uint8), bitorder="little")
    ny, nx = len(data["grid"]["latitudes"]), len(data["grid"]["longitudes"])
    mask = bits[:len(data["dates"]) * ny * nx].reshape(-1, ny, nx)
    j = data["grid"]["latitudes"].index(45)
    assert mask[-5:, j, :].all()
    assert not mask[:-5].any()
    assert len(data["fields"]["dates"]) == 5
    assert data["fields"]["encoding"] == "delta-time-i16"
    encoded = np.frombuffer(base64.b64decode(data["fields"]["z500"]), dtype="<i2").reshape(5, ny, nx)
    decoded = np.cumsum(encoded.astype(np.int32), axis=0).astype(np.int16)
    assert (decoded[:, j, :] == 5898).all()  # rounded 6000 - .1*45² + 100
