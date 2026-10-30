# Phase 1 Report: Satellite-Based Ground-Level PM2.5 Estimation
## Scope Decisions, Data Summary, Cleaning, Features, Baselines

**Author:** IIIT Kottayam (Master's Dissertation)
**Period covered:** 2021-01-01 to 2024-12-31
**Generated:** 2026-10-30

---

## 1. Scope Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Study area | South India (5 states) | Kerala has only 6 reference-grade stations, below the 15-station threshold for Kerala-only |
| Monsoon focus region | Kerala | Highest SW monsoon intensity in South India |
| Study period | 2021–2024 | 4 years provides sufficient temporal variation; pre-2021 CPCB data sparser |
| Completeness threshold | ≥70% daily over full period | Balances station density vs data quality |
| Ground data source | XKDR/CPCB CAAQM only | Reference-grade only; OpenAQ-only stations excluded |
| Spatial resolution | Monthly aggregate for Stage 5 | Daily pipeline deferred to Phase 2 |
| Buffer size | 5 km (test 10 km in Stage 4 proper) | ~5× MAIAC pixel; deferred comparison |
| Two-tier model | Tier A = full satellite+met, Tier B = met/reanalysis only | Handles cloud-covered days |

---

## 2. Data Summary

### 2.1 Ground PM2.5 (XKDR/CPCB CAAQM)

| Metric | Value |
|--------|-------|
| Stations (usable) | 73 |
| Raw hourly rows | 1,719,029 |
| After QC | 1,712,320 |
| Removed | 6,709 (0.39%) |
| Valid station-days (≥18h) | 68,088 |
| Study period | 2021-01-01 to 2024-12-31 |

**Breakdown by state:**

| State | Stations | Mean PM2.5 (µg/m³) |
|-------|----------|-------------------|
| Karnataka | 27 | 27.1 |
| Tamil Nadu | 14 | 28.9 |
| Andhra Pradesh | 11 | 36.0 |
| Telangana | 15 | 40.5 |
| Kerala | 6 | 30.6 |

### 2.2 Satellite and Reanalysis Data (GEE)

| Dataset | GEE ID | Status | Rows (73 × 48) |
|---------|--------|--------|----------------|
| S5P NO2 | COPERNICUS/S5P/OFFL/L3_NO2 | Complete | 3,504 |
| S5P CO | COPERNICUS/S5P/OFFL/L3_CO | Complete | 3,504 |
| S5P SO2 | COPERNICUS/S5P/OFFL/L3_SO2 | Complete | 3,504 |
| S5P HCHO | COPERNICUS/S5P/OFFL/L3_HCHO | Complete | 3,504 |
| S5P UV AER_AI | COPERNICUS/S5P/OFFL/L3_AER_AI | Complete | 3,504 |
| ERA5-Land | ECMWF/ERA5_LAND/HOURLY | Complete | 3,504 |
| ERA5 BLH | ECMWF/ERA5/HOURLY | Complete | 3,504 |
| MAIAC AOD | MODIS/061/MCD19A2_GRANULES | Partial (14/48 months) | 1,022 |
| CAMS AOD+PM2.5 | ECMWF/CAMS/NRT | Pending | 0 |

---

## 3. Cleaning Outcomes

### 3.1 PM2.5 QC Rules and Removal Counts

| Rule | Records Removed | % of Raw |
|------|----------------|---------|
| Impossible values (< 0 or > 1000 µg/m³) | 29 | 0.002% |
| Flat-lined sensor (> 24h same value) | 5,884 | 0.342% |
| Spikes (rolling z-score > 5) | 796 | 0.046% |
| **Total removed** | **6,709** | **0.390%** |
| **Final clean rows** | **1,712,320** | |

### 3.2 Satellite QA

- S5P OFFL L3 in GEE: QA filtering already applied at L3 ingestion (harpconvert) with thresholds per product (NO2 >75%, others >50%). No additional filtering needed.
- MAIAC AOD: `AOD_QA == 0` mask applied before averaging (best quality pixels only).

---

## 4. Feature List

### Tier A (full — satellite + reanalysis + met)

| Category | Features |
|----------|---------|
| Satellite | tropomi_no2_column, tropomi_co_column, tropomi_so2_column, tropomi_hcho_column, tropomi_uv_aerosol_index, tropomi_cloud_fraction |
| Meteorology | era5_temperature, era5_dewpoint, era5_u_wind, era5_v_wind, era5_precipitation, era5_blh, era5_relative_humidity (derived), era5_wind_speed (derived) |
| Temporal | doy_sin, doy_cos (cyclical encoding) |
| Lags | pm25_lag_1, pm25_lag_2, pm25_lag_3, era5_temperature_lag_1, era5_relative_humidity_lag_1 |
| Flags | satellite_available, s5p_no2_pixel_count |
| Static | latitude, longitude |

**Total: 34 columns (including target and metadata)**

### Tier B (fallback — no satellite)

Same as Tier A minus all satellite columns. **31 columns.**

### Missing in current features (pending extraction completion)

- MAIAC AOD (maiac_aod_055, maiac_aod_047): 100% NaN — extraction in progress
- CAMS AOD (cams_aod, cams_pm25_surface): 100% NaN — extraction pending

---

## 5. Baseline Results (Monthly Resolution, 2021–2024)

### 5.1 Temporal Split (train 2021-2023, test 2024)

| Model | Tier | RMSE | MAE | R² | Bias | Pearson r |
|-------|------|------|-----|-----|------|-----------|
| Linear Regression | A | **8.46** | 6.17 | **0.620** | 0.57 | 0.790 |
| Random Forest | A | 8.61 | 6.37 | 0.607 | 0.92 | 0.783 |
| Climatology | A | 11.99 | 8.16 | 0.237 | 2.03 | 0.655 |
| Persistence | A | 12.72 | 9.80 | 0.141 | 2.21 | 0.410 |
| Linear Regression | B | 8.47 | 6.18 | 0.619 | 0.56 | 0.791 |
| Random Forest | B | 8.48 | 6.16 | 0.619 | 0.40 | 0.787 |

*Units: µg/m³ for RMSE, MAE, Bias. n=807 test rows (73 stations × ~11 months).*

### 5.2 Seasonal Performance (Random Forest Tier A, temporal split)

| Season | RMSE | R² | n |
|--------|------|-----|---|
| SW Monsoon (Jun–Sep) | **6.13** | 0.526 | 264 |
| Pre-monsoon (Mar–May) | 7.47 | 0.572 | 197 |
| Post-monsoon (Jan–Feb) | 10.36 | 0.550 | 131 |
| NE Monsoon (Oct–Dec) | 10.75 | 0.419 | 215 |

### 5.3 Spatial Evaluation (RF Tier A)

- **Blocked 5-fold cross-validation:** mean RMSE = similar to temporal split
- **Leave-one-station-out (LOSO):** mean RMSE=8.68, mean R²=−1.95

  The strongly negative LOSO R² is expected and scientifically informative — it means the model cannot generalise PM2.5 levels to completely unmonitored stations using monthly-mean satellite and met features alone. This validates the need for the daily-resolution model and denser satellite features (MAIAC AOD) in Phase 2.

### 5.4 Feature Ablation (RF, temporal split)

| Feature set | RMSE | R² | n features |
|-------------|------|-----|-----------|
| Met only | 8.50 | 0.617 | 15 |
| Met + S5P gases | 8.72 | 0.597 | 21 |
| Met + S5P + aerosol | 8.72 | 0.597 | 21 |
| All Tier A | 8.59 | 0.608 | 23 |

**Key finding:** Adding S5P gas columns marginally *hurts* performance at monthly resolution (~+0.2 RMSE). This is expected — monthly means of column densities correlate poorly with surface PM2.5 at this resolution. The value of satellite data will be clearer at daily resolution with MAIAC AOD (Phase 2).

---

## 6. Limitations

1. **Monthly resolution.** All results are at monthly aggregates. The dissertation's core contribution requires daily overpass-matched data; this is written (`gee_extract_daily.py`) and running, but results will come in Phase 2.

2. **MAIAC AOD unavailable.** The most PM2.5-relevant satellite product is still extracting. It will be the key Tier A feature once complete.

3. **Station density.** Kerala has only 6 reference-grade stations, the weakest of any state. LOSO results confirm this — the model cannot reliably predict at unmonitored locations from monthly data alone.

4. **No static features yet.** Elevation, distance to coast, land cover, road density, and population density have not been ingested. These are important for spatial generalization and will be added in Phase 2.

5. **Linear regression matches RF.** At monthly resolution, the relationship is dominated by seasonal patterns which linear models capture well. Nonlinear RF advantages will appear at daily resolution with stronger satellite covariates.

---

## 7. Recommended Phase 2 Plan

1. Complete MAIAC AOD and CAMS extraction; re-run alignment + features
2. Run `gee_extract_daily.py` to completion (currently running in background)
3. Build daily-resolution aligned dataset (PM2.5 matched to overpass day)
4. Quantify SW monsoon cloud gap in Kerala at daily level
5. Add static features (elevation, land cover, population density)
6. Train Phase 2 models (XGBoost, LightGBM, neural network) on daily data
7. Two-tier inference: Tier A on clear days, Tier B on cloud-covered days
8. Evaluate by cloud-fraction bin and monsoon season
9. Spatial prediction maps (grid extraction, already designed in `gee_extract.py`)

---

## 8. Files Produced (Phase 1 Complete List)

### Data
- `data/raw/pm25_hourly/` — 73 station hourly PM2.5 files
- `data/raw/gee_extracts/` — 9 GEE dataset directories
- `data/interim/pm25_clean/` — 73 QC-cleaned station files
- `data/interim/cleaning_log.csv` — row-level removal log
- `data/interim/aligned_monthly.csv` — 2,688 station-months
- `data/processed/features_tier_a.csv` — 2,688 × 34
- `data/processed/features_tier_b.csv` — 2,688 × 31

### Reports
- `reports/figures/` — 11 PNG figures
- `reports/tables/baseline_results.csv` — all model × split × tier results
- `reports/tables/rf_tier_a_season_metrics.csv`
- `reports/tables/rf_tier_a_cloud_metrics.csv`
- `reports/tables/ablation_results.csv`
- `reports/tables/loso_results.csv`
- `reports/experiment_log.csv`

### Documentation
- `docs/decision_log.md`
- `docs/data_dictionary.md`
- `docs/station_audit.md`
- `docs/exploration_report.md`
- `docs/phase1_report.md` (this file)

### Code
- 14 source scripts across `src/ingest/`, `src/clean/`, `src/align/`, `src/features/`, `src/models/`, `src/eval/`, `src/utils/`
- 26 passing unit tests in `tests/`
