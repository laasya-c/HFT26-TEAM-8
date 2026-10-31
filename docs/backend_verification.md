# WILDSCOPE Backend Verification Record (Phases 1–6)

**Auditor / Engineer:** Shravan (Analytics & Decision Intelligence Lead)  
**Date:** 2026-10-31  
**Scope:** Final correctness, verification, and audit across Phases 1–6 backend code.  
**Branch:** `shravan`  
**Base Commit:** `5c323bd`  
**Postponed:** Frontend UI/dashboard, external deployment, and integration bundle with Santosh/Laasya.

---

## 1. Executive Verdict & Readiness Statement

**Status: Ready for Local Backend Use with Explicitly Listed Limitations.**

All 6 backend phases, mathematical models, contract validations, and cross-phase analytical workflows are fully operational and verified by 281 automated tests (280 passed, 1 skipped due to real data file presence, 1 real dataset integration test passed).

The backend safely distinguishes raw reference annotations (`DATASET_REFERENCE`) from operational predictions (`OPERATIONAL_PREDICTION`), preserves source snapshot immutability, guards against concurrent modification via dataset revisions, enforces geometric and coordinate reference system (CRS) validity without silent data mutation, and maintains strict parity between unified `analyze()` and specialized entry points.

---

## 2. Genuine Defects Found and Fixed

During this final correctness audit, the following genuine defects and precision discrepancies were identified and resolved:

1. **Numerical Unit Conversion Discrepancy:**
   - *Issue:* Previous documentation erroneously converted $10^{-6}$ degrees to "0.1 millimetres".
   - *Fix:* Corrected to exact physical conversion: $10^{-6}$ degrees of latitude is $\approx 0.111\text{ metres}$ ($111\text{ mm}$), while longitude distance scales with latitude as $\approx 0.111 \cdot \cos(\text{lat})\text{ metres}$ ($\sim 0.092\text{ m}$ at $34^\circ$ lat). Clarified that IEEE 754 float64 forward/inverse LAEA projection achieves $\sim 10^{-14}$ degrees roundtrip error ($\approx 1.5\text{ nm}$).

2. **Densification Geodesic vs Coordinate-Line Semantics:**
   - *Issue:* Documentation and docstrings previously described parallel densification as "geodesic interpolation". Parallels of latitude other than the equator are small circles (rhumb lines), not great circles / geodesics.
   - *Fix:* Clarified that `densify_coords` performs linear interpolation in longitude/latitude coordinate space (degree space), sampling along coordinate lines (parallels and meridians). In LAEA projection, coordinate parallels map to curved arcs; intermediate vertex sampling prevents straight-chord clipping without misrepresenting parallels as geodesics.

3. **Authalic Sphere Benchmark Scoping:**
   - *Issue:* Verification reports previously framed the analytical spherical quad formula ($R^2 \Delta \lambda (\sin \phi_2 - \sin \phi_1)$) as independent proof of WGS84 measurement accuracy.
   - *Fix:* Explicitly clarified that this benchmark proves that the spherical LAEA projection mathematically preserves authalic surface area on the reference sphere ($R = 6,371,008.8\text{ m}$) within $1.24 \times 10^{-8}$ relative error, but is not independent proof of WGS84 ellipsoidal measurement accuracy (which carries up to $\sim 0.5\%$ scale discrepancy).

4. **Misleading "Statistically Significant" Phrasing in Anomaly Indicators:**
   - *Issue:* `wildscope_analytics/anomalies.py` generated notes describing rate changes as "Statistically significant rate increase/decrease".
   - *Fix:* Replaced with "Heuristic rate increase indicator" and "Heuristic rate decrease indicator". Anomaly scores (standardized deviation ratios against daily baseline MAD) are exploratory heuristics, not calibrated statistical significance levels or $p$-values.

5. **Reference Snapshot Dispatch on Operational Endpoints:**
   - *Issue:* Passing an empty request or generic `AnalysisRequest(metric=...)` for operational metrics on a `DATASET_REFERENCE` snapshot raised parameter validation errors before evaluating whether the dataset mode even supported the metric.
   - *Fix:* Reordered execution in `compute_activity_anomalies` to check `snapshot.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE` immediately after snapshot contract validation. Reference snapshots now cleanly return `ResponseStatus.UNAVAILABLE` with diagnostic warnings across all operational endpoints without requiring fictitious operational parameters.

6. **Raw Dict Request Normalization in `analyze()`:**
   - *Issue:* Calling unified `analyze(snapshot, {"metric": "..."})` with raw dict payloads raised `AttributeError` when inspecting `request.metric` or `_check_revision`.
   - *Fix:* Added typed request dispatching and dictionary normalization at the top of `analyze()`, gracefully converting dicts into their respective typed request models or returning `ResponseStatus.INVALID_REQUEST` with structured errors upon schema validation failure.

7. **Camera Coordinate Mutual Nullability Enforcement:**
   - *Issue:* Setting latitude on an existing Camera without simultaneously providing longitude violated Pydantic's model validator during in-place test updates.
   - *Fix:* Enforced that latitude and longitude must both be provided together or both omitted.

---

## 3. Exact Verification Results

### Test Suite Execution
- **Command:** `pytest tests/ -v -rs`
- **Total Collected:** 281 tests across 8 test suites.
- **Passed:** 280 passed in 2.63s.
- **Skipped:** 1 skipped (`tests/test_phase2_analytics.py:1777` skipped because the local real Caltech annotation file `data/caltech_images_20210113.json` exists; directs to `test_real_dataset_integration`).
- **Failures:** 0.

### Real Dataset Integration Test
- **Command:** `pytest tests/test_phase2_analytics.py -k test_real_dataset_integration -v -s -rs`
- **Outcome:** 1 passed in 1.18s.
- **Subset Policy:** Deterministic subset of first 1,000 images sorted by ID from `data/caltech_images_20210113.json` (full dataset contains 243,100 images).
- **Verified Behavior:** Successfully parsed categories, cameras, and reference annotations. Evaluated `OVERVIEW` and `REFERENCE_IMAGE_SPECIES_COUNTS`. Operational metrics correctly returned `ResponseStatus.UNAVAILABLE`.

### Tooling Availability
- `ruff`: Not installed in environment.
- `mypy`: Not installed in environment.
- `flake8`: Not installed in environment.
- Reported honestly per project instructions: no lint/type tool runs claimed.

---

## 4. Coverage Matrix

| Feature / Phase | Synthetic Correctness | Real Reference Data | Operational Predictions | Field Spatial / Telemetry |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1: Contracts & Validation** | Verified (Referential integrity, duplicate IDs, timestamp awareness, error paths) | Verified (1,000 Caltech image annotations) | N/A | N/A |
| **Phase 2: Activity Analytics (F10)** | Verified (Deduplication, multi-species encounters, effort-normalised rates) | Verified (`OVERVIEW`, `REFERENCE_IMAGE_SPECIES_COUNTS`) | Pending upstream model deployment | N/A |
| **Phase 3: Review Ranking (F18)** | Verified (Marginal ranking, counterfactual isolation, tie-breaking) | Verified (`UNAVAILABLE` on reference data) | Pending operational detection streams | N/A |
| **Phase 4: Associations (F06)** | Verified (Clock comparability, offset addition, gap extrema, Haversine) | Verified (`UNAVAILABLE` on reference data) | Pending operational encounter grouping | Pending camera GPS audit |
| **Phase 5: Anomaly Indicators (F12)** | Verified (Two-sided rules, zero-dispersion fallback, local calendar day DST) | Verified (`UNAVAILABLE` on reference data) | Pending operational encounter grouping | Pending physical telemetry logs |
| **Phase 6: Spatial Intelligence (F08, F09, F14, F16)** | Verified (LAEA authalic projection, gap analysis, candidate ranking, scenarios) | Verified (`UNAVAILABLE` on reference data) | N/A | Pending official reserve boundaries |
| **Cross-Phase Workflows (A, B, C, D)** | Verified (End-to-end multi-phase lifecycles and optimistic revision guards) | N/A | N/A | N/A |

---

## 5. Files Changed & Runnable Commands

### Modified & Created Files
- `wildscope_analytics/analytics.py`: Unified `analyze()` dict request normalization, dispatching, and revision checking.
- `wildscope_analytics/anomalies.py`: Early source mode checking for reference snapshots; exploratory heuristic wording for anomaly indicators.
- `wildscope_analytics/associations.py`: Dict request normalization for cross-camera associations.
- `wildscope_analytics/spatial.py`: LAEA documentation corrections (precision vs accuracy, degree-to-metre conversion, coordinate-line densification).
- `wildscope_analytics/contracts/requests.py`: CRS and cost weight validation.
- `wildscope_analytics/contracts/responses.py`: Explicit fields for candidate rankings, blind spots, and proximity uncertainty.
- `tests/test_phase6_spatial.py`: 30 spatial tests verifying geometry, extents, analytical benchmarks, and feature parity.
- `tests/test_cross_phase_workflows.py`: 4 end-to-end integration workflows covering lifecycles A, B, C, and D.
- `docs/team_handoff.md`: Updated Section 6 with spatial contracts and handoff notes.
- `docs/backend_verification.md`: This comprehensive backend verification record.
- `schemas/*.schema.json`: All 18 JSON schemas regenerated and verified.

### Verification Commands
```powershell
# 1. Run all 281 backend tests
pytest tests/ -v -rs

# 2. Run real Caltech dataset integration test
pytest tests/test_phase2_analytics.py -k test_real_dataset_integration -v -s -rs

# 3. Run cross-phase public workflows
pytest tests/test_cross_phase_workflows.py -v -rs

# 4. Regenerate and verify JSON Schemas
python -m wildscope_analytics.schema_generator
```

---

## 6. Remaining Limitations & Next Steps

1. **Hardware Telemetry & Provenance:**
   - Physical camera stationarity records and clock synchronization audit trails currently depend on upstream provider inputs (`camera.provenance`). In the absence of telemetry, stationarity remains `UNASSESSED`.
2. **Operational Predictions & Encounters:**
   - Raw reference datasets (Caltech Camera Traps) do not provide operational encounter grouping or detection confidence scores. Operational metrics correctly return `ResponseStatus.UNAVAILABLE` on reference data.
3. **Field Spatial Data:**
   - Genuine study area boundaries and feasible placement sites must be provided by field managers or GIS staff; no synthetic boundaries are fabricated in operational mode.
4. **Next Recommended Step:**
   - When instructed by Shravan, proceed with teammate contract handoff (Santosh for ingestion/telemetry and Laasya for UI visualization) using the generated schemas in `schemas/` and contracts documented in `docs/team_handoff.md`.
