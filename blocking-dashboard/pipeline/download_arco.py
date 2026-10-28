"""Read real ERA5 Z500 from Google Research's public ARCO mirror, without a key.

The mirror's geopotential chunks contain 37 complete pressure-level maps.
HTTP byte ranges select just the Blosc blocks intersecting 500 hPa. The public
Blosc decoder reconstructs that slice losslessly; no atmospheric values are
approximated by the byte reader. The resulting 0.25-degree field is sampled
on the configured display/detection grid and saved as monthly NetCDFs.

Source: https://github.com/google-research/arco-era5
Format: https://blosc.org/c-blosc2/format/chunk_format.html
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import threading
import time

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from numcodecs import Blosc
import xarray as xr

STORE = "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
_local = threading.local()


class TransferBudget:
    def __init__(self, megabytes=80):
        self.limit = int(megabytes * 1_000_000)
        self.reserved = 0
        self.lock = threading.Lock()

    def reserve(self, size):
        with self.lock:
            if size < 0 or self.reserved + size > self.limit:
                raise ValueError(f"Transfer budget reached ({self.limit / 1e6:g} MB); previous complete cache files retained")
            self.reserved += size


def session():
    if not hasattr(_local, "http"):
        http = requests.Session()
        http.headers.update({"User-Agent": "BlockingObservatory/1.0 (public ERA5 scientific data reader)"})
        retry = Retry(total=5, backoff_factor=.7, status_forcelist=[429, 500, 502, 503, 504])
        http.mount("https://", HTTPAdapter(max_retries=retry))
        _local.http = http
    return _local.http


def get_json(path):
    r = session().get(STORE + "/" + path, timeout=(10, 60))
    r.raise_for_status()
    return r.json()


def get_range(url, start, stop, etag=None, budget=None):
    size = stop - start + 1
    if size <= 0 or size > 8_000_000:
        raise ValueError("Refusing a field byte range larger than 8 MB")
    if budget:
        budget.reserve(size)
    headers = {"Range": f"bytes={start}-{stop}", "Accept-Encoding": "identity"}
    if etag:
        headers["If-Match"] = etag
    with session().get(url, headers=headers, timeout=(10, 90), stream=True) as r:
        r.raise_for_status()
        if r.status_code != 206 or not r.headers.get("Content-Range", "").startswith(f"bytes {start}-{stop}/"):
            raise ValueError("Server did not honour the requested public-data byte range")
        if etag and r.headers.get("ETag") != etag:
            raise ValueError("ERA5 object changed during retrieval; retry this day")
        value = r.raw.read(size + 1, decode_content=False)
        if len(value) != size:
            raise ValueError("Incomplete byte range")
        return value, r.headers.get("ETag")


def blosc_slice(read_range, expected_nbytes, offset, length):
    """Losslessly decode one byte interval from a Blosc1 chunk.

    A small valid Blosc chunk is re-framed around the selected whole blocks,
    then decoded by numcodecs. The scientific slice is copied out afterwards.
    Block physical order is not assumed to match logical order.
    """
    header = read_range(0, 15)
    if len(header) != 16 or header[0] != 2:
        raise ValueError("Expected a Blosc1 version-2 header")
    nbytes, blocksize, cbytes = struct.unpack("<III", header[4:16])
    if nbytes != expected_nbytes or blocksize <= 0 or not (0 <= offset < offset + length <= nbytes):
        raise ValueError("Unexpected chunk shape or slice extent")
    if header[2] & 2:  # BLOSC_MEMCPYED: data follows the fixed header.
        if cbytes != nbytes + 16:
            raise ValueError("Invalid uncompressed Blosc chunk length")
        return read_range(16 + offset, 16 + offset + length - 1)
    nblocks = (nbytes + blocksize - 1) // blocksize
    index_size = 16 + 4 * nblocks
    if cbytes <= index_size:
        raise ValueError("Invalid compressed Blosc size")
    index = np.frombuffer(read_range(16, index_size - 1), dtype="<u4")
    if len(index) != nblocks or len(np.unique(index)) != nblocks or np.any(index < index_size) or np.any(index >= cbytes):
        raise ValueError("Invalid Blosc block offset table")
    physical = sorted(int(v) for v in index)
    ends = dict(zip(physical, physical[1:] + [cbytes]))
    first, last = offset // blocksize, (offset + length - 1) // blocksize
    selected = [int(index[i]) for i in range(first, last + 1)]
    begin, stop = min(selected), max(ends[v] for v in selected)
    body = read_range(begin, stop - 1)
    new_index_size = 16 + 4 * len(selected)
    pieces, starts, cursor = [], [], new_index_size
    for start in selected:
        piece = body[start - begin:ends[start] - begin]
        starts.append(cursor)
        pieces.append(piece)
        cursor += len(piece)
    new_nbytes = min((last + 1) * blocksize, nbytes) - first * blocksize
    new_header = header[:4] + struct.pack("<III", new_nbytes, blocksize, cursor)
    packed = new_header + struct.pack("<" + "I" * len(starts), *starts) + b"".join(pieces)
    decoded = Blosc().decode(packed)
    if len(decoded) != new_nbytes:
        raise ValueError("Unexpected decoded byte count")
    start = offset - first * blocksize
    return decoded[start:start + length]


class ArcoReader:
    def __init__(self, grid=5.0, max_transfer_mb=80):
        self.budget = TransferBudget(max_transfer_mb)
        self.attributes = get_json(".zattrs")
        self.meta = get_json("geopotential/.zarray")
        self.var_attrs = get_json("geopotential/.zattrs")
        self.time_attrs = get_json("time/.zattrs")
        if self.meta["chunks"] != [1, 37, 721, 1440] or self.meta["dtype"] != "<f4" or self.meta["order"] != "C":
            raise ValueError("ARCO layout changed; inspect metadata before using this reader")
        if self.var_attrs.get("_ARRAY_DIMENSIONS") != ["time", "level", "latitude", "longitude"]:
            raise ValueError("Unexpected geopotential dimensions")
        if self.time_attrs.get("units") != "hours since 1900-01-01 00:00:00":
            raise ValueError("Unexpected time origin")
        self.levels = self.coordinate("level")
        latitude, longitude = self.coordinate("latitude"), self.coordinate("longitude")
        if not (np.array_equal(latitude, np.arange(90, -90.01, -.25))
                and np.array_equal(longitude, np.arange(0, 360, .25))):
            raise ValueError("Unexpected ARCO latitude/longitude coordinates")
        self.level_index = int(np.where(self.levels == 500)[0][0])
        stride = round(grid / .25)
        if grid <= 0 or not np.isclose(stride * .25, grid) or not np.isclose(round(180 / grid) * grid, 180):
            raise ValueError("Requested grid must be a positive multiple of 0.25 degrees and divide 180")
        self.stride, self.grid = stride, grid
        self.latitude, self.longitude = latitude[::stride], longitude[::stride]
        self.downloaded = 0
        self.lock = threading.Lock()

    @staticmethod
    def coordinate(name):
        meta = get_json(name + "/.zarray")
        attrs = get_json(name + "/.zattrs")
        if meta["shape"] != meta["chunks"]:
            raise ValueError("Coordinate is no longer stored in one chunk")
        r = session().get(STORE + "/" + name + "/0", timeout=(10, 60))
        r.raise_for_status()
        raw = Blosc().decode(r.content) if meta["compressor"] else r.content
        arr = np.frombuffer(raw, dtype=meta["dtype"])
        if list(arr.shape) != meta["shape"]:
            raise ValueError("Invalid coordinate length")
        return arr

    def read_day(self, date, verify_full=False):
        date = np.datetime64(date, "D")
        hours = int((date - np.datetime64("1900-01-01")).astype(int)) * 24
        url = STORE + "/geopotential/" + str(hours) + ".0.0.0"
        prefix, etag = get_range(url, 0, 4095, budget=self.budget)
        received = len(prefix)
        def read_range(start, stop):
            nonlocal received
            if stop < len(prefix):
                return prefix[start:stop + 1]
            value, _ = get_range(url, start, stop, etag, self.budget)
            received += len(value)
            return value
        plane_bytes = 721 * 1440 * 4
        raw = blosc_slice(read_range, 37 * plane_bytes, self.level_index * plane_bytes, plane_bytes)
        field = np.frombuffer(raw, dtype="<f4").reshape(721, 1440)
        if not np.isfinite(field).all() or not 2500 < field.min() / 9.80665 < field.max() / 9.80665 < 7000:
            raise ValueError(f"Invalid 500 hPa field on {date}")
        if verify_full:
            self.budget.reserve(struct.unpack("<I", prefix[12:16])[0])
            r = session().get(url, headers={"If-Match": etag}, timeout=(10, 180))
            r.raise_for_status()
            decoded = np.frombuffer(Blosc().decode(r.content), dtype="<f4").reshape(37, 721, 1440)
            if not np.array_equal(field, decoded[self.level_index]):
                raise ValueError("Byte-range slice differs from independently decoded full chunk")
            print(f"Verified {date}: selective Z500 is bit-for-bit identical to the full 37-level decode", flush=True)
        with self.lock:
            self.downloaded += received
        return date, field[::self.stride, ::self.stride].copy()


def retrieve(cache, start=None, end=None, grid=5.0, workers=2, refresh_days=100, verify=False, max_transfer_mb=80, max_days=31):
    reader = ArcoReader(grid, max_transfer_mb)
    latest = np.datetime64(reader.attributes.get("valid_time_stop_era5t", reader.attributes["valid_time_stop"])[:10])
    stop = latest if end is None else np.datetime64(end)
    begin = stop - 18 if start is None else np.datetime64(start)
    if int((stop - begin).astype(int)) + 1 > max_days:
        raise ValueError(f"Date range exceeds the explicit {max_days}-day limit")
    if begin < np.datetime64(reader.attributes["valid_time_start"]) or stop > latest or begin > stop:
        raise ValueError(f"Date range is outside verified mirror coverage through {latest}")
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    provenance = {"provider": "Google Research ARCO-ERA5 public mirror", "store": STORE,
                  "retrieved_at": datetime.now(timezone.utc).isoformat(), "source_attributes": reader.attributes,
                  "variable": "geopotential", "pressure_level_hpa": 500, "sample_time": "00:00 UTC",
                  "native_grid_degrees": .25, "output_grid_degrees": grid,
                  "resampling": "regular grid-point sampling of the 0.25 degree analysis-ready field",
                  "byte_reader": "lossless Blosc block ranges; verified against a full-chunk decode" if verify else "lossless Blosc block ranges",
                  "final_era5_through": reader.attributes["valid_time_stop"], "era5t_through": str(latest)}
    (cache / "source.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"Public ERA5 source: 500 hPa, 00:00 UTC, {grid}° sampled grid; ERA5T through {latest}", flush=True)
    if verify:
        reader.read_day(stop, verify_full=True)
    months = np.arange(begin.astype("datetime64[M]"), stop.astype("datetime64[M]") + 1)
    started, n = time.monotonic(), 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for month in months:
            dates = np.arange(max(begin, month.astype("datetime64[D]")), min(stop + 1, (month + 1).astype("datetime64[D]")))
            path = cache / f"era5-z500-{month}.nc"
            if path.exists():
                with xr.open_dataset(path) as prior:
                    prior_dates = prior.time.values.astype("datetime64[D]")
                    matches = (np.array_equal(prior_dates, dates) and np.isclose(prior.attrs.get("grid_degrees", -1), grid)
                               and prior.attrs.get("source_store") == STORE)
                if matches and dates[-1] < stop - refresh_days:
                    continue
            values = np.empty((len(dates), len(reader.latitude), len(reader.longitude)), dtype=np.float32)
            positions = {date: i for i, date in enumerate(dates)}
            futures = [pool.submit(reader.read_day, date) for date in dates]
            for future in as_completed(futures):
                date, field = future.result()
                values[positions[date]] = field
                n += 1
            ds = xr.Dataset({"z": (("time", "latitude", "longitude"), values,
                                   {"units": "m**2 s**-2", "long_name": "Geopotential at 500 hPa", "pressure_level_hpa": 500})},
                            coords={"time": dates, "latitude": reader.latitude, "longitude": reader.longitude},
                            attrs={"source_store": STORE, "grid_degrees": grid, "source_provider": "Google Research ARCO-ERA5",
                                   "source_last_updated": reader.attributes["last_updated"]})
            temporary = path.with_suffix(".download.nc")
            ds.to_netcdf(temporary, encoding={"z": {"zlib": True, "complevel": 3}})
            from build_data import read_month
            checked, _, _, _ = read_month(temporary)
            if not np.array_equal(checked, dates):
                raise ValueError("Cached daily samples differ from the requested dates")
            temporary.replace(path)
            elapsed = time.monotonic() - started
            print(f"Saved {month}: {len(dates)} days; {n} retrieved; {reader.downloaded / 1e9:.2f} GB transferred; {elapsed:.0f}s elapsed", flush=True)
    print("Public ERA5 retrieval complete.", flush=True)
    return provenance


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("working-data/era5-arco-5deg"))
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--grid", type=float, default=5.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--max-transfer-mb", type=float, default=80)
    parser.add_argument("--max-days", type=int, default=31)
    parser.add_argument("--refresh-days", type=int, default=100)
    parser.add_argument("--verify-full-chunk", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 24:
        parser.error("Use between 1 and 24 download workers")
    retrieve(args.cache, args.start, args.end, args.grid, args.workers, args.refresh_days, args.verify_full_chunk, args.max_transfer_mb, args.max_days)
