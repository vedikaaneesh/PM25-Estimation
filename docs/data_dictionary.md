# Data Dictionary

All dataset IDs, band names, scale factors, and QA conventions verified
against the Google Earth Engine Data Catalog (developers.google.com/earth-engine)
and source documentation. Last verified: 2026-10-29.

## Ground PM2.5

| Variable | Source | Unit | Resolution | Temporal Coverage |
|----------|--------|------|------------|-------------------|
| pm25 | XKDR (CPCB CAAQM) | µg/m³ | hourly | 2019–2025 (per station) |
| pm25 | XKDR (US Embassy) | µg/m³ | hourly | 2019–2026 |

- XKDR API: https://airquality.xkdr.org/v1
- Timestamps are naive IST. Convert to UTC by subtracting 5h30m.
- Data is published as received: no gap-filling, no outlier removal.

## Sentinel-5P TROPOMI (Satellite Gases + Aerosol Index)

Source: COPERNICUS/S5P/OFFL/L3_* (Offline products)
Catalog: https://developers.google.com/earth-engine/datasets/catalog/sentinel-5p
Resolution: 0.01 arc degrees (~1.1 km), revisit ~2 days
Scale: values stored as-is (mol/m² for columns, dimensionless for AER_AI)

| Variable | Dataset ID | Band Name | QA Band | QA Threshold |
|----------|-----------|-----------|---------|--------------|
| NO2 (tropospheric) | COPERNICUS/S5P/OFFL/L3_NO2 | tropospheric_NO2_column_number_density | qa_value | >75 (0.75) |
| CO | COPERNICUS/S5P/OFFL/L3_CO | CO_column_number_density | qa_value | >50 (0.50) |
| SO2 | COPERNICUS/S5P/OFFL/L3_SO2 | SO2_column_number_density | qa_value | >50 (0.50) |
| HCHO (tropospheric) | COPERNICUS/S5P/OFFL/L3_HCHO | tropospheric_HCHO_column_number_density | qa_value | >50 (0.50) |
| UV Aerosol Index | COPERNICUS/S5P/OFFL/L3_AER_AI | absorbing_aerosol_index | qa_value | >80 (0.80) |
| Cloud fraction | COPERNICUS/S5P/OFFL/L3_CLOUD | cloud_fraction | qa_value | >50 (0.50) |

Note: GEE already applies QA filtering during L3 ingestion (harpconvert).
The qa_value band in GEE is 0–100; divide by 100 for the fraction.
TROPOMI overpass time for India: ~13:30 local time (ascending node).

## MODIS MAIAC AOD

| Variable | Dataset ID | Band Name | QA Band | Scale Factor |
|----------|-----------|-----------|---------|-------------|
| AOD 550nm | MODIS/061/MCD19A2_GRANULES | Optical_Depth_055 | AOD_QA | ÷1000 |
| AOD 470nm | MODIS/061/MCD19A2_GRANULES | Optical_Depth_047 | AOD_QA | ÷1000 |

Catalog: https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD19A2_GRANULES
Resolution: 1 km, daily
AOD_QA: 16-bit, bit 0=fill, bit 1=water mask, bits 2-3=AOD quality.
Best quality: AOD_QA == 0 (clear, best quality) or bit-check.
User guide: https://lpdaac.usgs.gov/documents/1500/MCD19_User_Guide_V61.pdf

## ERA5-Land (Meteorology)

Dataset ID: ECMWF/ERA5_LAND/HOURLY
Catalog: https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_LAND_HOURLY
Resolution: ~11 km, hourly

| Variable | Band Name | Unit | Notes |
|----------|-----------|------|-------|
| Temperature 2m | temperature_2m | K | Subtract 273.15 for °C |
| Dewpoint 2m | dewpoint_temperature_2m | K | Use for RH calculation |
| U-wind 10m | u_component_of_wind_10m | m/s | Eastward component |
| V-wind 10m | v_component_of_wind_10m | m/s | Northward component |
| Total precip | total_precipitation | m | Hourly accumulation |

## ERA5 Single Levels (Boundary-Layer Height)

Dataset ID: ECMWF/ERA5/HOURLY
Catalog: https://developers.google.com/earth-engine/datasets/catalog/ECMWF_ERA5_HOURLY
Resolution: ~31 km, hourly

| Variable | Band Name | Unit | Notes |
|----------|-----------|------|-------|
| BLH | boundary_layer_height | m | ERA5-Land does NOT have this |

## CAMS (Reanalysis Aerosol for Gap-Filling)

Dataset ID: ECMWF/CAMS/NRT
Catalog: https://developers.google.com/earth-engine/datasets/catalog/ECMWF_CAMS_NRT
Resolution: ~44 km, 3-hourly

| Variable | Band Name | Unit | Notes |
|----------|-----------|------|-------|
| Total AOD 550nm | total_aerosol_optical_depth_at_550nm_surface | dimensionless | Verified 2026-10-29 |
| PM2.5 surface | particulate_matter_d_less_than_25_um_surface | µg/m³ | Bonus variable — surface PM2.5 from CAMS |

Note: CAMS NRT covers from 2003 to near-real-time. For reanalysis,
consider ECMWF/CAMS/REANALYSIS (if available in GEE).

## Static Features (to be extracted in Stage 2)

| Variable | Source | Dataset ID | Notes |
|----------|--------|-----------|-------|
| Elevation | SRTM | USGS/SRTMGL1_003 | 30m, or COPERNICUS/DEM/GLO30 |
| Land cover | ESA WorldCover | ESA/WorldCover/v200 | 10m, 2021 vintage |
| Population | WorldPop | WorldPop/GP/100m/pop | To verify availability |
| Road density | OSM | Computed from OSM | Manual or GEE |
| Distance to coast | Computed | From coastline shapefile | Computed from station coords |

## Open Verification Items

- [ ] CAMS exact band name (verify on first GEE run)
- [ ] MAIAC AOD_QA bit interpretation (confirm against user guide)
- [ ] ERA5 band names (confirm on first GEE run)
- [ ] Static layer dataset IDs (verify availability in GEE)
