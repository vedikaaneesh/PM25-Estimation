# Station Audit Report

**Generated:** 2026-10-29
**Study period:** 2021-01-01 to 2024-12-31
**Completeness threshold:** ≥70% daily completeness

## Summary

| Metric | Count |
|--------|-------|
| Total stations (all sources) | 159 |
| Stations meeting completeness threshold | 73 |
| Kerala stations (total) | 24 |
| Kerala stations (usable) | 6 |

## Stations per State

| State | Total Stations | Usable (XKDR, >= 70%) |
|-------|-------|-------|
| Andhra Pradesh | 20 | 11 |
| Karnataka | 64 | 27 |
| Kerala | 24 | 6 |
| Tamil Nadu | 36 | 14 |
| Telangana | 15 | 15 |

## Stations per Source

| Source | Count |
|--------|-------|
| openaq | 80 |
| xkdr | 5 |
| xkdr+openaq | 74 |

## Scope Decision

**Recommendation: Use South India as the study area** with Kerala as the monsoon focus sub-region. Kerala has only 6 usable stations (< 15 threshold). South India has 73 usable stations.

## Seasonal Completeness

See `reports/tables/seasonal_completeness.csv` for the full table.

## Station Map

See `reports/figures/station_map.png`.

## Limitations

- Completeness was checked for 79 XKDR stations (CPCB CAAQM + US Embassy)
  using the XKDR API with full 2021-2024 data access.
- 80 OpenAQ-only stations have NOT been checked for completeness yet.
  These require separate OpenAQ measurements API queries.
- State assignment for OpenAQ-only stations uses approximate bounding boxes,
  not official state boundaries. Some edge stations may be misassigned.

## Open Decisions

- [ ] Final study area (Kerala-only vs South India)
- [ ] Study period confirmation
- [ ] Deduplication rule approval
- [ ] Whether to include OpenAQ-only stations (possible low-cost sensors)
- [ ] Completeness threshold (proposed: >= 70% daily over full period)
