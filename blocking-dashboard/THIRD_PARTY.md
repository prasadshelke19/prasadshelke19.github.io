# Third-party sources

**D3 7.9.0**, copyright Mike Bostock and contributors, ISC licence.
The complete licence is in `assets/d3-LICENSE`.
Bundle source: https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js
Project: https://github.com/d3/d3

**Natural Earth**, public-domain 1:110m land polygons.
`assets/land.js` is an unmodified geometry dataset serialized as a local script
assignment for offline loading.
Source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_land.geojson
Terms: https://www.naturalearthdata.com/about/terms-of-use/

**ERA5 / ERA5T** (when the real pipeline is configured): Copernicus Climate
Change Service (C3S), ECMWF. Pressure-level dataset:
https://doi.org/10.24381/cds.bd0915c6
The current preview includes real ERA5 / preliminary ERA5T geopotential from Google Research’s public ARCO-ERA5 mirror: https://github.com/google-research/arco-era5 . The original synthetic development fixture is retained but is not loaded by the dashboard.

**Research method:** Shelke & Renwick (2026), GRL,
https://doi.org/10.1029/2025GL120428
The formulas are implemented with an explicit hemispheric coordinate
convention and need author validation before scientific release.

**Interaction inspiration:** Extreme Weather Data and Visualization Hub,
https://extremewx.org/ . No source code, text, branding, or data from that
website are copied into this application.
