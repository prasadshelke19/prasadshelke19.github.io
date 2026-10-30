"""A recent-only refresh must match a full raw-archive rebuild exactly."""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np
import pytest
import xarray as xr
sys.path.insert(0, str(Path(__file__).parents[1] / "pipeline"))
from build_data import build
from update_compact import read_bundle, update
from verify_retained import verify


def cache_fixture(root, start, end):
    root.mkdir(parents=True)
    lat, lon = np.arange(90, -91, -15), np.arange(0, 360, 15)
    dates = np.arange(np.datetime64(start), np.datetime64(end) + 1)
    for month in np.unique(dates.astype("datetime64[M]")):
        days = dates[dates.astype("datetime64[M]") == month]
        heights = np.broadcast_to((6000 - .1 * lat ** 2)[None, :, None], (len(days), len(lat), len(lon))).copy()
        # This run is pending at the old Jan 5 endpoint and confirmed later.
        event = (days >= np.datetime64("2026-01-03")) & (days <= np.datetime64("2026-01-10"))
        heights[np.ix_(event, lat == 45, np.ones(len(lon), dtype=bool))] += 140
        xr.Dataset({"z": (("time", "latitude", "longitude"), heights, {"units": "m"})},
                   coords={"time": days, "latitude": lat, "longitude": lon}).to_netcdf(root / f"era5-z500-{month}.nc")
    (root / "source.json").write_text(json.dumps({"provider": "Fixture", "store": "fixture",
        "source_attributes": {"last_updated": "2026-01-12"}, "final_era5_through": "2025-09-30",
        "resampling": "regular fixture grid", "native_grid_degrees": 15}))


@pytest.mark.parametrize("old_end", ["2025-12-28", "2026-01-05"])
def test_recent_only_refresh_matches_full_rebuild_across_year_boundary(tmp_path, old_end):
    old_cache, full_cache, recent_cache = [tmp_path / name for name in ["old", "full", "recent"]]
    cache_fixture(old_cache, "2024-01-01", old_end)
    cache_fixture(full_cache, "2024-01-01", "2026-01-10")
    cache_fixture(recent_cache, "2025-12-15", "2026-01-10")
    old_file, full_file = tmp_path / "derived" / "era5.js", tmp_path / "independent" / "era5.js"
    build(old_cache, old_file, (2024, 2024))
    old = read_bundle(old_file)
    reference = old_file.parent / "era5-height-reference.npz"
    reference_sha = hashlib.sha256(reference.read_bytes()).hexdigest()
    manifest = update(recent_cache, old_file)
    build(full_cache, full_file, (2024, 2024))
    actual, expected = read_bundle(old_file), read_bundle(full_file)
    assert actual["dates"] == expected["dates"]
    assert manifest["days"] == 366 + 365 + 10
    for key in actual["masks"]:
        assert np.array_equal(actual["masks"][key], expected["masks"][key]), key
    for key in ["dates", "z500", "anomaly"]:
        assert np.array_equal(actual["fields"][key], expected["fields"][key], equal_nan=True), key
    assert hashlib.sha256(reference.read_bytes()).hexdigest() == reference_sha
    assert actual["meta"]["anomaly_reference"] == [2024, 2024]
    assert actual["meta"]["reference_available"] is True
    assert verify(old_file.parent)["status"] == "passed"
    raw_report = verify(full_file.parent, full_cache)
    assert raw_report["status"] == "passed"
    assert len(raw_report["independent_raw_checks"]) == 1
    if old_end == "2026-01-05":
        assert old["masks"]["pending_ppa"][-1].any()
        assert actual["masks"]["ppa"][-8:].any()
        assert not actual["masks"]["pending_ppa"].any()


def test_missing_recent_month_preserves_existing_archive(tmp_path):
    old_cache, recent = tmp_path / "old", tmp_path / "recent"
    cache_fixture(old_cache, "2024-01-01", "2026-01-05")
    cache_fixture(recent, "2025-11-15", "2026-01-10")
    (recent / "era5-z500-2025-12.nc").unlink()
    output = tmp_path / "data" / "era5.js"
    build(old_cache, output, (2024, 2024))
    before = output.read_bytes()
    with pytest.raises(ValueError, match="missing dates"):
        update(recent, output)
    assert output.read_bytes() == before


def test_bounded_refresh_uses_retained_reference_and_removes_only_its_temporary_cache(tmp_path, monkeypatch):
    import refresh_arco
    old_cache = tmp_path / "old"
    cache_fixture(old_cache, "2024-01-01", "2026-01-05")
    output = tmp_path / "data" / "era5.js"
    build(old_cache, output, (2024, 2024))
    downloaded = []
    monkeypatch.setattr(refresh_arco, "get_json", lambda _: {"valid_time_stop": "2025-09-30", "valid_time_stop_era5t": "2026-01-10"})
    def fake_retrieve(cache, start, end, **kwargs):
        assert kwargs["workers"] == 2
        assert kwargs["max_transfer_mb"] == 500
        cache.rmdir()  # fixture creates its own directory
        cache_fixture(cache, start, end)
        downloaded.append(cache)
    monkeypatch.setattr(refresh_arco, "retrieve", fake_retrieve)
    report = refresh_arco.refresh(output)
    assert report["archive_end"] == "2026-01-10"
    assert not downloaded[0].exists()
    assert (old_cache / "era5-z500-2024-01.nc").exists()
    assert verify(output.parent)["status"] == "passed"
