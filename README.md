# Satellite-Based Ground-Level PM2.5 Estimation Using Multi-Source Data

Master's dissertation project at IIIT Kottayam. Phase 1 covers data audit,
acquisition, cleaning, spatiotemporal alignment, feature engineering, baseline
models, and an evaluation framework.

## Structure

| Directory | Purpose |
|-----------|---------|
| `configs/` | YAML configs for study area, dates, features, thresholds, GEE |
| `data/raw/` | Raw downloads, never edited by hand |
| `data/interim/` | Intermediate processing outputs |
| `data/processed/` | Analysis-ready datasets |
| `src/ingest/` | Data ingestion scripts |
| `src/clean/` | Cleaning and QC |
| `src/align/` | Spatiotemporal alignment |
| `src/features/` | Feature engineering |
| `src/models/` | Model training |
| `src/eval/` | Evaluation framework |
| `src/utils/` | Shared utilities (logging, experiment tracking) |
| `notebooks/` | Exploratory analysis only |
| `reports/figures/` | PNG figures |
| `reports/tables/` | CSV tables |
| `docs/` | Documentation and decision log |
| `tests/` | Unit tests for cleaning and alignment |

## Setup

```bash
conda env create -f environment.yml
conda activate pm25
```

## GEE Authentication

1. Place the service account key JSON at
   `~/.config/earthengine/pm25-service-account-key.json`
2. Project ID and service account email are in `configs/gee.yaml`
3. Never commit the key file. It is covered by `.gitignore`.

## Running

```bash
make help      # list available targets
make test      # run tests
make audit     # run station audit (Stage 1)
```

## Workflow

Each stage ends with a checkpoint. Read the report in `docs/` before approving
the next stage. All decisions are logged in `docs/decision_log.md`.
