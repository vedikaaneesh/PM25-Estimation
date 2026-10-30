# Decision Log

All scientific and engineering decisions recorded with date and reason.

| Date | Decision | Context | Chosen Option | Reason |
|------|----------|---------|---------------|--------|
| 2026-10-29 | Repo structure | Project scaffolding | Layout per spec | Matches dissertation requirements |
| 2026-10-29 | Environment | Dependency management | conda + environment.yml | Reproducibility with pinned versions |
| 2026-10-29 | Experiment tracking | Run logging | CSV in reports/ | Simple, version-controllable |
| 2026-10-29 | GEE auth | Earth Engine access | Service account | Project: kochi-pm25-research |

## 2026-10-29 — Stage 4/5 Transition Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Proceed with partial MAIAC/CAMS | Yes — treat as NaN | Tree models handle NaN natively; ablation will show contribution later |
| Daily S5P extraction | Start in background | Needed for dissertation cloud analysis; runs overnight |
| Monthly vs daily baseline | Monthly for Stage 5 | Daily is Phase 2; monthly baselines validate the framework |

| Decision | Choice | Reason |
|----------|--------|--------|
| Proceed with partial MAIAC/CAMS | Yes | Still extracting; Stage 4 handles missing months gracefully |
| Daily S5P extraction | Yes | Critical for quantifying Jun-Sep cloud gap |
| WHO/NAAQS reference lines | Add to figures | WHO annual=5 µg/m³, 24h=15 µg/m³; India NAAQS 24h=60 µg/m³ |

| Decision | Choice | Reason |
|----------|--------|--------|
| Buffer size comparison | Defer to Stage 4 | Avoid doubling extraction time |
| S5P Cloud separate extraction | Skip | cloud_fraction already in s5p_no2 output |
| CAMS PM2.5 surface variable | Add to CAMS extraction | Extra variable for gap-filling/comparison |

| Decision | Choice | Reason |
|----------|--------|--------|
| Study area | South India (5 states), Kerala as monsoon focus | Kerala has only 6 reference-grade stations (< 15 threshold) |
| OpenAQ-only stations | Exclude | User decision; keep reference-grade CPCB stations only |
| Study period | 2021-01-01 to 2024-12-31 | Confirmed |
| Completeness threshold | ≥70% daily over full period | 73 of 79 XKDR stations pass |
| Deduplication rule | Coordinate match within 0.005 deg (~500m) | Approved |
| Feature list | Tier A / Tier B as in configs/features.yaml | Approved |

**Stage 1 frozen scope:** 73 usable XKDR stations across South India, 2021–2024.
