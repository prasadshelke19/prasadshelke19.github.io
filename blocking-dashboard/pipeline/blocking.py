"""Gridpoint PPA/TR diagnostics. All heights are geopotential metres.

Shelke & Renwick (2026), doi:10.1029/2025GL120428, section 2.2.
Latitude derivatives use a poleward-positive coordinate in BOTH hemispheres.
The NH implementation is an explicit, unvalidated extension of this SH paper.
"""
from __future__ import annotations

import numpy as np

G0 = 9.80665
METHODS = {
    "ppa": {"name": "Persistent positive anomaly", "threshold_m": 100, "persistence_days": 5},
    "tr": {"name": "True reversal", "delta_deg": 15, "persistence_days": 4,
           "equatorward_gradient_min": 0, "poleward_gradient_max": -10,
           "subtropical_gradient_max": -5},
}


def geopotential_to_height(values, units="m2 s-2"):
    """Do not silently divide data that already contain geopotential height."""
    u = units.lower().replace(" ", "").replace("**", "^")
    if u in {"m2s-2", "m^2s^-2", "m^2/s^2", "m2/s2", "m^2s-2"}:
        return np.asarray(values, dtype=np.float32) / G0
    if u in {"m", "gpm", "geopotentialmetres", "geopotentialmeters"}:
        return np.asarray(values, dtype=np.float32)
    raise ValueError(f"Unsupported geopotential/height units: {units!r}")


def day_key(dates):
    """Map month-day to a leap-year calendar: March never shifts in leap years."""
    dates = np.asarray(dates, dtype="datetime64[D]")
    mmdd = np.datetime_as_string(dates, unit="D")
    return np.array([(np.datetime64("2000" + str(d)[4:]) - np.datetime64("2000-01-01")).astype(int)
                     for d in mmdd], dtype=int)


def daily_climatology(z500, dates, start_year, end_year):
    dates = np.asarray(dates, dtype="datetime64[D]")
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    chosen = (years >= start_year) & (years <= end_year)
    if not chosen.any():
        raise ValueError("No input dates within requested anomaly reference period")
    source = np.asarray(z500)[chosen]
    keys = day_key(dates[chosen])
    climate = np.full((366,) + source.shape[1:], np.nan, dtype=np.float32)
    for k in np.unique(keys):
        vals = source[keys == k]
        total = np.nansum(vals, axis=0)
        count = np.isfinite(vals).sum(axis=0)
        climate[k] = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    # Leap-day reference is defined as adjacent-day interpolation, consistently.
    climate[59] = (climate[58] + climate[60]) / 2
    return climate


def sample_latitude(field, latitude, target):
    latitude = np.asarray(latitude)
    order = np.argsort(latitude)
    coords = latitude[order]
    if target < coords[0] or target > coords[-1]:
        return np.full((field.shape[0], field.shape[2]), np.nan)
    right = int(np.searchsorted(coords, target, side="left"))
    if right < len(coords) and np.isclose(coords[right], target):
        return field[:, order[right], :]
    left = right - 1
    fraction = (target - coords[left]) / (coords[right] - coords[left])
    return (1 - fraction) * field[:, order[left], :] + fraction * field[:, order[right], :]


def instantaneous_tr(z500, latitude, delta=15):
    """Return candidate and valid masks with shape (time, latitude, longitude).

    q=abs(latitude), H(q)=Z(sign(latitude)*q). This mirrors the gradients
    physically, avoiding a Northern-Hemisphere sign convention applied to SH.
    """
    field = np.asarray(z500)
    result = np.zeros(field.shape, dtype=bool)
    valid = np.zeros_like(result)
    for j, lat in enumerate(latitude):
        q, sign = abs(float(lat)), 1 if lat >= 0 else -1
        if not 30 <= q <= 75:
            continue
        h = field[:, j, :]
        he = sample_latitude(field, latitude, sign * (q - delta))
        hp = sample_latitude(field, latitude, sign * (q + delta))
        he2 = sample_latitude(field, latitude, sign * (q - 2 * delta))
        ge, gp, gee = (h - he) / delta, (hp - h) / delta, (he - he2) / delta
        good = np.isfinite(h) & np.isfinite(he) & np.isfinite(hp) & np.isfinite(he2)
        result[:, j, :] = good & (ge > 0) & (gp < -10) & (gee < -5)
        valid[:, j, :] = good
    return result, valid


def persist(raw, dates, minimum_days, valid=None):
    """Mark ALL days of qualifying runs; gaps/NaNs break runs.

    Pending = the last, still-observed qualifying run if it has not yet met
    duration. A short completed run is not pending, and is never blocked.
    """
    raw = np.asarray(raw, dtype=bool)
    dates = np.asarray(dates, dtype="datetime64[D]")
    if len(dates) != len(raw) or not len(dates):
        raise ValueError("Non-empty dates and mask must have the same time dimension")
    if minimum_days < 1 or np.any(np.diff(dates).astype(int) <= 0):
        raise ValueError("Persistence must be positive; dates must be unique and increasing")
    raw = raw & (np.asarray(valid, dtype=bool) if valid is not None else True)
    forward = np.zeros(raw.shape, dtype=np.uint16)
    backward = np.zeros(raw.shape, dtype=np.uint16)
    gaps = np.diff(dates).astype(int) != 1
    for i in range(len(raw)):
        prior = 0 if i == 0 or gaps[i - 1] else forward[i - 1]
        forward[i] = np.where(raw[i], prior + 1, 0)
    for i in range(len(raw) - 1, -1, -1):
        prior = 0 if i == len(raw) - 1 or gaps[i] else backward[i + 1]
        backward[i] = np.where(raw[i], prior + 1, 0)
    confirmed = raw & ((forward.astype(np.int32) + backward - 1) >= minimum_days)
    pending = np.zeros_like(raw)
    last = forward[-1]
    for offset in range(min(minimum_days - 1, len(raw))):
        pending[-1 - offset] = (last > offset) & (last < minimum_days)
    return confirmed, pending


def detect(z500, latitude, dates, climatology, tr_days=4):
    field = np.asarray(z500, dtype=np.float32)
    anomaly = field - climatology[day_key(dates)]
    band = ((np.abs(latitude) >= 30) & (np.abs(latitude) <= 75))[None, :, None]
    valid_ppa = np.isfinite(anomaly) & band
    raw_ppa = (anomaly >= 100) & valid_ppa
    raw_tr, valid_tr = instantaneous_tr(field, latitude)
    ppa, pending_ppa = persist(raw_ppa, dates, 5, valid_ppa)
    tr, pending_tr = persist(raw_tr, dates, tr_days, valid_tr)
    return {"ppa": ppa, "tr": tr, "pending_ppa": pending_ppa,
            "pending_tr": pending_tr, "valid_ppa": valid_ppa,
            "valid_tr": valid_tr, "anomaly": anomaly}

