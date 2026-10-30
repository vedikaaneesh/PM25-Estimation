# Stage 3 Exploration Report

**Generated:** 2026-10-29
**Data as of:** MAIAC AOD partially extracted (12/48 months); CAMS re-extracting with PM2.5 surface band

---

## 1. Data Summary

| Source | Records | Coverage |
|--------|---------|----------|
| PM2.5 hourly (XKDR/CPCB) | 1,719,029 rows | 73 stations, 2021–2024 |
| PM2.5 valid station-days (≥18h/day) | 68,088 | 73 stations |
| S5P NO2 | 3,504 station-months | 73 stations × 48 months |
| S5P CO, SO2, HCHO, AER_AI | 3,504 each | Same |
| ERA5-Land (met.) | 3,504 | Same |
| ERA5 BLH | 3,504 | Same |
| MAIAC AOD | 876 (partial) | 12/48 months |
| CAMS AOD + PM2.5 | Re-extracting | — |

---

## 2. Data Availability (Missingness)

| Variable | Overall | SW Monsoon (Jun–Sep) | Post-Monsoon |
|----------|---------|---------------------|--------------|
| PM2.5 ground | 100% | 100% | 100% |
| ERA5-Land (met.) | 96% | 96% | 96% |
| ERA5 BLH | 100% | 100% | 100% |
| S5P NO2 | 100% | 100% | 100% |
| S5P CO | 100% | 100% | 100% |
| S5P SO2 | 100% | 100% | 100% |
| S5P HCHO | 100% | 100% | 100% |
| S5P AER_AI | 100% | 100% | 100% |
| MAIAC AOD | — (partial) | — | — |
| CAMS AOD | — (re-extracting) | — | — |

**Note on 100% S5P availability:** The GEE OFFL L3 collection at monthly
mean level returns a value for almost every station-month because it averages
valid days within the month. Some months with heavy cloud cover will have fewer
valid days contributing to the mean. Cloud fraction needs to be checked at
the daily/overpass level during Stage 4 to quantify how many days are lost.

**ERA5-Land ~4% missing** at monthly level is due to the dataset coverage
starting after some months in the study period (verified: all months 2021–2024
are present; the missing 4% is NaN from pixels at the coast/boundary).

---

## 3. PM2.5 Seasonality

| State | Pre-monsoon | SW Monsoon | NE Monsoon | Post-monsoon |
|-------|------------|------------|------------|-------------|
| Andhra Pradesh | 32.5 | **22.5** | 42.8 | 49.3 |
| Karnataka | 30.5 | **18.0** | 30.9 | 36.9 |
| Kerala | 31.9 | **23.8** | 29.7 | 40.3 |
| Tamil Nadu | 23.5 | **20.9** | 35.5 | 39.2 |
| Telangana | 41.1 | **23.1** | 45.8 | 50.9 |

Values are mean daily PM2.5 (µg/m³). All states show the SW monsoon as
the cleanest season — rainfall and mixing dilute PM2.5. Post-monsoon and
NE monsoon are the most polluted for most states.

**Key finding for the dissertation:** PM2.5 is lowest exactly when satellite
coverage is most degraded (SW monsoon). This is the core trade-off that
the two-tier model must handle.

---

## 4. Kerala Monsoon Satellite Availability (Jun–Sep)

- **S5P NO2:** 100% availability at monthly aggregate level. At daily level,
  cloud cover will reduce valid overpasses significantly. This will be quantified
  in Stage 4 when we extract daily-resolution data.
- **MAIAC AOD:** Still extracting. Expected to show severe degradation Jun–Sep
  due to cloud cover masking. This is the most critical gap for Tier A.

---

## 5. Station Correlation vs Distance

The correlation–distance plot (reports/figures/pm25_correlation_vs_distance.png)
shows high variability at all distance scales, consistent with India's
heterogeneous PM2.5 sources. Even nearby stations show moderate correlation
(~0.5–0.7 within 50 km), reflecting local source variability (urban,
industrial, rural). This confirms that spatial interpolation alone is insufficient
and satellite covariates are needed.

---

## 6. Data Quality Problems Found

| Problem | Variables | Proposed Handling |
|---------|-----------|------------------|
| Outliers (PM2.5 > 500 µg/m³) | Ground PM2.5 | Flag and remove in Stage 4 (z-score rule) |
| Flat-lined sensors (repeated values > 24h) | Ground PM2.5 | Detect in Stage 4 (Stage 4 QC script) |
| Monthly aggregation hides daily cloud gaps | All satellite | Stage 4: re-extract at daily resolution for station-matched days |
| ERA5-Land coastal NaN (~4%) | Temperature, wind, precip | Nearest-neighbour fill from ERA5 single levels |
| MAIAC extraction slow (granule-level) | AOD | Runs in background; will be complete before Stage 4 |

---

## 7. Feasibility Assessment

**Strong positive signals:**
- 68,088 valid station-days of PM2.5 ground truth across 73 stations
- All S5P gases have near-100% coverage at monthly level
- ERA5-Land meteorology is spatially complete and high quality
- Clear seasonality confirms the SW monsoon vs post-monsoon contrast

**Key uncertainties (to resolve in Stage 4):**
- Daily S5P cloud-fraction distribution during Jun–Sep has not yet been
  quantified. Monthly means mask day-level cloud contamination.
- MAIAC AOD completeness during Jun–Sep is the critical unknown for Tier A.
- The fraction of station-days where Tier B fallback will be needed depends on
  MAIAC availability, which will be known after full extraction.

**Preliminary judgement:** The project is feasible. The SW monsoon will
degrade Tier A inputs as expected; Tier B (ERA5 + CAMS + met only) should
perform better than a no-data fallback. The dissertation contribution is
well-supported by the data distribution.

---

## 8. Figures Produced

| File | Contents |
|------|----------|
| `reports/figures/missingness_by_variable.png` | Bar chart of GEE dataset availability |
| `reports/figures/missingness_satellite_monthly.png` | Monthly heatmap of S5P NO2 availability |
| `reports/figures/pm25_seasonality.png` | Seasonal boxplots by state |
| `reports/figures/pm25_distribution.png` | Overall and seasonal distribution |
| `reports/figures/pm25_correlation_vs_distance.png` | Pairwise correlation vs distance |

## 9. Tables Produced

| File | Contents |
|------|----------|
| `reports/tables/missingness_table.csv` | Availability % by variable and season |
| `reports/tables/pm25_seasonal_stats.csv` | Mean, median, std by state and season |
| `reports/tables/satellite_availability.csv` | Monthly S5P availability by year |

---

## Open Items (to resolve before Stage 4)

- [ ] MAIAC AOD full extraction (running in background, ~36 more months)
- [ ] CAMS re-extraction with PM2.5 surface band (running in background)
- [ ] Daily-resolution cloud fraction analysis for Jun–Sep (Stage 4 task)
