from pathlib import Path
import sys
import numpy as np
import pytest
sys.path.insert(0, str(Path(__file__).parents[1] / "pipeline"))
from blocking import (G0, geopotential_to_height, day_key, daily_climatology,
                      instantaneous_tr, persist, detect)
from download_era5 import request_for_month


def dates(start, n):
    return np.arange(np.datetime64(start), np.datetime64(start) + n)


def test_geopotential_conversion_and_unit_guard():
    assert geopotential_to_height([5500 * G0], "m**2 s**-2")[0] == pytest.approx(5500)
    assert geopotential_to_height([5500], "m")[0] == 5500
    with pytest.raises(ValueError):
        geopotential_to_height([5500], "hPa")


def test_persistence_is_retroactive_and_short_completed_run_is_excluded():
    raw = np.array([1, 1, 1, 1, 1, 0, 1, 1, 1, 0, 1, 1], dtype=bool)[:, None]
    confirmed, pending = persist(raw, dates("2026-01-01", 12), 5)
    assert confirmed[:, 0].tolist() == [True] * 5 + [False] * 7
    assert np.where(pending[:, 0])[0].tolist() == [10, 11]


def test_four_day_reversal_threshold_and_pending_promotion():
    c, p = persist(np.ones((3, 1)), dates("2026-02-01", 3), 4)
    assert not c.any() and p.all()
    c, p = persist(np.ones((4, 1)), dates("2026-02-01", 4), 4)
    assert c.all() and not p.any()


def test_missing_date_and_missing_cell_break_persistence():
    d = np.array(["2026-01-01", "2026-01-02", "2026-01-04", "2026-01-05"], dtype="datetime64[D]")
    c, p = persist(np.ones((4, 1)), d, 4)
    assert not c.any() and p[:, 0].tolist() == [False, False, True, True]
    c, _ = persist(np.ones((5, 1)), dates("2026-01-01", 5), 5,
                   valid=np.array([1, 1, 0, 1, 1])[:, None])
    assert not c.any()


def test_runs_cross_new_year_without_reset():
    c, _ = persist(np.ones((5, 1)), dates("2025-12-29", 5), 5)
    assert c.all()


def test_calendar_day_keys_and_february_29_reference():
    assert day_key(["2023-03-01", "2024-03-01"]).tolist() == [60, 60]
    assert day_key(["2024-02-29"])[0] == 59
    d = np.array(["2023-02-28", "2023-03-01", "2024-02-28", "2024-02-29", "2024-03-01"])
    z = np.array([0, 10, 0, 999, 10], dtype=float)[:, None, None]
    ref = daily_climatology(z, d, 2023, 2024)
    assert ref[59, 0, 0] == 5  # Explicit adjacent-day interpolation policy.


def symmetric_blocking_field(n=6):
    lat = np.arange(-90, 91, 15)
    q = np.array([0, 15, 30, 45, 60, 75, 90])
    h = np.array([6000, 5700, 5400, 5500, 5200, 4900, 4600])
    field = np.broadcast_to(np.interp(abs(lat), q, h)[None, :, None], (n, len(lat), 1)).copy()
    return field, lat


def test_tr_signs_are_symmetric_between_hemispheres():
    field, lat = symmetric_blocking_field()
    raw, valid = instantaneous_tr(field, lat)
    assert raw[:, lat == 45, :].all()
    assert raw[:, lat == -45, :].all()
    assert np.array_equal(raw, raw[:, ::-1])
    assert valid[:, (abs(lat) < 30), :].sum() == 0


def test_normal_westerly_profile_is_not_blocked():
    lat = np.arange(-90, 91, 5)
    field = np.broadcast_to((6000 - 10 * abs(lat))[None, :, None], (5, len(lat), 2))
    raw, _ = instantaneous_tr(field, lat)
    assert not raw.any()


@pytest.mark.parametrize("he,h,hp,he2", [(5500, 5500, 5200, 5800),
                                                   (5400, 5500, 5350, 5700),
                                                   (5400, 5500, 5200, 5475)])
def test_tr_gradient_thresholds_are_strict(he, h, hp, he2):
    field, lat = symmetric_blocking_field()
    for q, value in [(15, he2), (30, he), (45, h), (60, hp)]:
        field[:, lat == q, :] = value
    raw, _ = instantaneous_tr(field, lat)
    assert not raw[:, lat == 45, :].any()


def test_ppa_includes_exactly_100_metres_and_invalid_cells_stay_missing():
    lat = np.array([90, 75, 60, 45, 30, 15, 0, -15, -30, -45, -60, -75, -90])
    z = np.full((5, len(lat), 1), 5500., dtype=np.float32)
    reference = np.full((366, len(lat), 1), 5400., dtype=np.float32)
    z[:, lat == -45] = np.nan
    result = detect(z, lat, dates("2026-01-01", 5), reference)
    assert result["ppa"][:, lat == 45].all()
    assert not result["valid_ppa"][:, lat == -45].any()
    assert not result["ppa"][:, abs(lat) < 30].any()


def test_cds_request_selects_500_hpa_and_00_utc_instantaneous_samples():
    request = request_for_month(2024, 2, 29, 2.5)
    assert request["pressure_level"] == ["500"]
    assert request["time"] == ["00:00"]
    assert request["variable"] == ["geopotential"]
    assert len(request["day"]) == 29
    assert request["grid"] == [2.5, 2.5]


def test_read_month_normalizes_real_cds_shape(tmp_path):
    import xarray as xr
    from build_data import read_month
    latitude = np.arange(90, -91, -15)
    longitude = np.arange(0, 360, 15)
    shape = (4, 1, len(latitude), len(longitude))
    ds = xr.Dataset({"z": (("valid_time", "pressure_level", "latitude", "longitude"),
                          np.full(shape, 5500 * G0, dtype=np.float32), {"units": "m**2 s**-2"})},
                    coords={"valid_time": dates("2026-01-01", 4), "pressure_level": [500],
                            "latitude": latitude, "longitude": longitude})
    path = tmp_path / "sample.nc"
    ds.to_netcdf(path)
    d, z, lat, lon = read_month(path)
    assert z.shape == (4, 13, 24)
    assert z[0, 0, 0] == pytest.approx(5500)
    assert lon[0] == -180 and lat[0] == 90


def test_dataset_with_hourly_mean_or_wrong_time_is_rejected(tmp_path):
    import xarray as xr
    from build_data import read_month
    ds = xr.Dataset({"z": (("time", "lat", "lon"), np.full((1, 13, 24), 5500), {"units": "m"})},
                    coords={"time": [np.datetime64("2026-01-01T12:00")], "lat": np.arange(90, -91, -15), "lon": np.arange(-180, 180, 15)})
    path = tmp_path / "bad.nc"
    ds.to_netcdf(path)
    with pytest.raises(ValueError, match="00:00"):
        read_month(path)
