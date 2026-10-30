# WILDSCOPE Team Handoff — Phase 2

> **Prepared by:** Shravan (Analytics & Decision Intelligence Lead)
> **Phase:** 2 — Cross-Camera Activity Analytics (`analyze()` implemented)
> **Status:** Complete. `rank_review()` remains UNAVAILABLE (Phase 3).
> **Schema version:** 1.1.0 (backward-compatible with 1.0.0)
> **Branch:** `shravan`

---

## 0. Quick Summary of What Changed

| Area | Phase 1 | Phase 2 |
|---|---|---|
| `analyze()` | Returns `UNAVAILABLE` | **Fully implemented** — 7 metrics |
| `rank_review()` | Returns `UNAVAILABLE` | Still `UNAVAILABLE` (Phase 3) |
| Schema version | 1.0.0 | **1.1.0** (additive, backward-compat) |
| Data source modes | — | `operational_prediction` / `dataset_reference` |
| Dataset reference annotations | — | `DatasetReferenceAnnotation` entity |
| Review ordering | Timestamp-only risk | `sequence_number` field on `ReviewEvent` |
| Caltech dataset | — | Adapter implemented; blocked by network |
| Tests | 38 passing | **117 passing, 1 skipped** |

---

## 1. New Metrics in `analyze()`

Call `analyze(snapshot, request)` with `request.metric` set to any of:

| `AnalysisMetric` value | Description |
|---|---|
| `overview` | Snapshot summary: encounter counts, cameras, time coverage, detection status |
| `species_encounter_counts` | Deduplicated encounter/species pairs |
| `camera_comparison` | Per-camera encounter and species breakdown |
| `daily_activity` | Encounter counts by calendar date (requires `analysis_timezone`) |
| `hourly_activity` | Encounter counts by hour-of-day 0–23 (requires `analysis_timezone`) |
| `species_camera_matrix` | Species × camera encounter count matrix |
| `effort_normalised_rates` | Encounters per active camera-day (requires effort records) |

**Legacy Phase 1 aliases still work** (mapped internally with a warning):

| Legacy value | Maps to |
|---|---|
| `activity_time_distribution` | `hourly_activity` |
| `cross_camera_association` | `camera_comparison` |
| `camera_activity_summary` | `overview` |
| `monitoring_coverage_summary` | `effort_normalised_rates` |

---

## 2. For Harsh (Vision & Model Inference)

### What is needed for operational analytics to work

1. **Encounter export via `group_encounters()`** — This is the primary input to all Phase 2 analytics. Encounters must be exported in the `Snapshot.encounters` list with:
   - `camera_id` — the physical camera where the encounter occurred
   - `member_detection_ids` — list of Detection IDs in this encounter
   - `member_observation_ids` — list of Observation IDs
   - `start_time` + `end_time` — **timezone-aware** timestamps. Without these, time-based analytics (daily/hourly activity) will exclude the encounter and report `status=partial`.
   - `rule_version` — e.g. `"v1_time_gap_30min"` to document the grouping policy

2. **Do not invent a second encounter grouper** — Shravan's module reuses Harsh's encounter records as-is; it does not re-group.

3. **Triage state must be set correctly** on each Detection:
   - `animal_detected` — animal present; species classification attempted
   - `likely_empty` — no animal; excluded from all species counts
   - `unsupported_taxon` — animal present but outside model's catalog
   - `processing_failure` — corrupt/failed frame

4. **Reference-mode note** — If you apply `group_encounters()` to Caltech Camera Traps images, pass the resulting encounters into a snapshot with `data_source_mode=dataset_reference` and use reference annotations instead of operational detections. Do **not** mix the two.

---

## 3. For Santosh (Backend, Persistence & Snapshot Assembly)

### Schema version 1.1.0 — additive changes only

Version 1.0.0 snapshots are still accepted. Version 1.1.0 adds three optional fields to `SnapshotMetadata`:

```json
{
  "metadata": {
    "schema_version": "1.1.0",
    "dataset_revision": 42,
    "data_source_mode": "operational_prediction",
    "review_ordering_mechanism": "backend_revision",
    ...
  }
}
```

- `data_source_mode`: `"operational_prediction"` (default) or `"dataset_reference"`
- `review_ordering_mechanism`: `"backend_revision"` (default), `"sequence_number"`, `"timestamp"`, or `"unresolvable"`

### Critical: ReviewEvent ordering — `sequence_number` field

Phase 2 adds `sequence_number: int | None` to `ReviewEvent`. This is the **authoritative ordering mechanism** when multiple reviews exist for the same detection.

**Problem Shravan's resolver must solve:** If a reviewer corrects species A → B, then a second reviewer corrects B → C, the resolver needs to know which review is most recent. `created_at` timestamps can be tied or arrive out of clock order. `expected_revision` is a concurrency *precondition*, not a sequencing mechanism.

**Required action from Santosh:**
```sql
-- On review INSERT, assign a monotone sequence number per target detection
INSERT INTO reviews (id, target_id, decision, ..., sequence_number)
VALUES (..., nextval('review_sequence_per_target'))
```

When exporting snapshots, populate `ReviewEvent.sequence_number` from this counter. Without it, the resolver will report `is_unresolved=True` for conflicting multi-review detections rather than guessing.

### Snapshot assembly checklist

- [ ] Set `metadata.schema_version = "1.1.0"`
- [ ] Set `metadata.dataset_revision` to current DB counter
- [ ] Set `metadata.data_source_mode` appropriately
- [ ] Populate `ReviewEvent.sequence_number` from backend monotone counter
- [ ] Export monitoring effort intervals as pre-merged, non-overlapping active periods
- [ ] Call `load_and_validate_snapshot()` before passing to `analyze()`

### Revision conflict handling (unchanged from Phase 1)

If `request.expected_revision != snapshot.metadata.dataset_revision`, `analyze()` returns `status=invalid_request`. The frontend (Laasya) should handle this and refresh the snapshot.

---

## 4. For Laasya (Frontend & Dashboard)

### Response envelope is unchanged in structure

Every `analyze()` call returns `AnalysisResponseEnvelope` with:

```json
{
  "status": "ok",
  "schema_version": "1.1.0",
  "dataset_revision": 42,
  "metric": "species_encounter_counts",
  "applied_filters": { ... },
  "result": { ... },
  "metric_units": "deduplicated encounter/species pairs",
  "evidence_references": ["enc_001", "enc_002"],
  "excluded_records_count": 0,
  "exclusion_reasons": [],
  "warnings": [],
  "limitations": []
}
```

### Status semantics (precise per-metric contract)

| Status | Exact Meaning & Trigger Condition | Example Scenarios |
|---|---|---|
| `ok` | Computation completed cleanly with zero record exclusions. | All records in scope have valid timestamps, confirmed labels, and complete metadata. |
| `partial` | Usable results produced, but some records were excluded. Always inspect `excluded_records_count` and `exclusion_reasons`. | Some encounters missing timestamps (excluded from daily/hourly bins); detections below `min_confidence`; unresolved review conflicts; cameras without effort records. |
| `insufficient_data` | Input records exist in the snapshot, but are inadequate/insufficient to compute the requested metric. | Encounters exist, but **all** scoped encounters lack timestamps (cannot bin by date/hour); monitoring effort records exist, but cover **zero active camera-days** in the requested analysis window. |
| `unavailable` | A prerequisite data type or capability is **entirely absent** from the snapshot or pipeline. | `rank_review()` called before Phase 3; encounter metrics called with `snapshot.encounters == []` (requires Harsh's `group_encounters()`); `effort_normalised_rates` called with `snapshot.monitoring_efforts == []`. |
| `invalid_request` | Contract or precondition violation; inspect `errors[]`. | Snapshot schema validation failed; `expected_revision` mismatch with `dataset_revision` (optimistic locking failure). |

### Encounter Dependency Matrix

Encounter grouping is externally owned by Harsh (`group_encounters()`). Shravan's analytics module consumes encounters; it never invents a competing grouping algorithm or infers encounters from image counts.

| Metric | Requires Encounters? | Behavior when Encounters Absent | Behavior when All Timestamps Missing | Behavior when Some Timestamps Missing |
|---|---|---|---|---|
| `overview` | Optional | Computes image/camera/detection counts; `total_encounters` is `null` with explanation | Reports time span if observations have timestamps | Reports time span from available timestamps |
| `species_encounter_counts` (operational) | **Required** | `unavailable` (limitation explains Harsh dependency) | Encounters counted without time-window filtering | Encounters outside window excluded (`partial`) |
| `species_encounter_counts` (reference) | No (uses images) | `ok` / `partial` (counts annotated images, clearly distinct from encounters) | Images without timestamp excluded from time filters | Images without timestamp excluded (`partial`) |
| `camera_comparison` | **Required** | `unavailable` | All encounters counted per camera | Excluded from time filters (`partial`) |
| `daily_activity` | **Required** | `unavailable` | `insufficient_data` (cannot group by date) | `partial` (valid binned, missing reported) |
| `hourly_activity` | **Required** | `unavailable` | `insufficient_data` (cannot group by hour) | `partial` (valid binned, missing reported) |
| `species_camera_matrix` | **Required** | `unavailable` | Matrix cells populated without time filter | Excluded from time filters (`partial`) |
| `effort_normalised_rates` | **Required** | `unavailable` | Encounters without timestamp counted in `encounters_outside_effort` | Encounters outside effort counted separately (`partial`) |

### ReviewEvent.sequence_number & Review Conflict Resolution

When multiple reviews exist for a single target detection, deterministic resolution is required.

#### Requirements for Santosh's Backend
1. **Field:** `ReviewEvent.sequence_number: int | None` (schema 1.1.0).
2. **Semantics:** Monotonically increasing positive integer assigned on review creation, unique per target detection.
3. **Ordering Authority:** The review with the highest `sequence_number` is authoritative (represents the latest backend review state).

#### Handling Ambiguous / Missing / Duplicate Sequences
- **All Reviews Agree:** If all reviews on a detection share the identical `decision` and `corrected_taxon_id`, the decision is applied even if `sequence_number` is absent.
- **Missing `sequence_number` with Conflicting Decisions:** Marked `is_unresolved=True`, `taxon_id="__unresolved__"`, and conflict note populated. The resolver **never guesses** or falls back to timestamps unless explicitly configured with `ReviewOrderingMechanism.TIMESTAMP`.
- **Duplicate / Tied `sequence_number`:** If multiple reviews share the highest `sequence_number` with conflicting decisions, this is flagged as a backend data integrity bug. The resolver marks `is_unresolved=True` and records an explicit conflict note (`Duplicate sequence_number X on ReviewEvents [...]`).
- **Analytics Safety Guarantee:** Unresolved detections (`is_unresolved=True`) are strictly blocked by `_is_detection_eligible()`. They **never** contribute to species encounter counts, camera breakdowns, or matrix cells. They are tracked and reported in `unresolved_detections_count` and trigger `status=partial`.

### Per-metric result shapes

**`overview`**
```json
{
  "data_source_mode": "operational_prediction",
  "counting_unit": "encounter",
  "total_encounters": 47,
  "total_cameras_in_scope": 12,
  "time_coverage_start": "2026-10-01T...",
  "time_coverage_end": "2026-10-30T...",
  "detections_classified": 120,
  "detections_rejected": 3,
  "detections_unknown_species": 8
}
```

**`species_encounter_counts`**
```json
{
  "counting_unit": "deduplicated encounter/species pairs",
  "species_entries": [
    { "taxon_id": "panthera_tigris", "encounter_count": 12, "evidence_encounter_ids": [...] },
    { "taxon_id": "axis_axis", "encounter_count": 8, "evidence_encounter_ids": [...] }
  ],
  "unknown_animal_encounters": 2,
  "multi_species_encounters": 3,
  "total_eligible_encounters": 47,
  "note": "Summed species counts may exceed total_eligible_encounters in multi-species encounters."
}
```

**`hourly_activity`**
```json
{
  "analysis_timezone": "Asia/Kolkata",
  "hour_counts": {
    "00": 0, "01": 0, ..., "06": 5, "07": 8, ..., "23": 1
  },
  "note": "Zero in a bin = zero recorded encounters, NOT absence of monitoring coverage."
}
```

**`effort_normalised_rates`**
```json
{
  "counting_unit": "encounters per active camera-day",
  "camera_rates": [
    {
      "camera_id": "cam_core_01",
      "active_camera_days_in_window": 5.0,
      "encounters_in_effort": 12,
      "rate_per_camera_day": 2.4
    }
  ],
  "total_active_camera_days": 35.0,
  "overall_rate_per_camera_day": 1.34
}
```

### Important display notes

- **Encounter ≠ individual animal.** Never display encounter count as population size.
- **Unknown species** (`unknown_animal_encounters`) must be displayed separately — do not distribute them into named species.
- **Unresolved detections** mean conflicting reviews with ambiguous ordering — show them explicitly, not as any species.
- **Dataset-reference results** are ground-truth annotation counts, not model accuracy. Do not label them as model performance.
- **Evidence references** are bounded samples (max 10); each entry shows `evidence_sample_note` when truncated.

---

## 5. Caltech Dataset Integration

### Status: BLOCKED (sandbox network isolation)

```
socket.gaierror: [Errno 11001] getaddrinfo failed
```

No outbound network access from the development sandbox. **Run these exact Windows PowerShell commands outside the sandbox:**

```powershell
# Step 1: Download official Caltech Camera Traps annotations archive (verified Lila Wildlife URL)
Invoke-WebRequest -Uri "https://lilawildlife.blob.core.windows.net/lila-wildlife/caltechcameratraps/labels/caltech_camera_traps.json.zip" -OutFile "caltech_camera_traps.json.zip"

# Step 2: Extract archive (expands to caltech_camera_traps.json)
Expand-Archive -Path "caltech_camera_traps.json.zip" -DestinationPath "." -Force

# Step 3: Run the CLI adapter to import snapshot and display overview metrics
python -m wildscope_analytics.caltech_adapter caltech_camera_traps.json --max-images 500 --timezone US/Pacific --metric overview

# Step 4: Run the real integration test suite pointing to the extracted file
$env:CCT_ANNOTATION_FILE = "caltech_camera_traps.json"
python -m pytest tests/test_phase2_analytics.py::TestCaltechRealDatasetBlocked::test_real_dataset_integration -v -s
```

License: Community Data License Agreement - Permissive 1.0 (see lila.science for terms).

### Running the adapter via Python CLI or API

```powershell
# Using the adapter CLI runner:
python -m wildscope_analytics.caltech_adapter caltech_camera_traps.json --max-images 500 --timezone US/Pacific --metric species_encounter_counts

# Or via Python script:
python -c "
from wildscope_analytics.caltech_adapter import import_caltech_snapshot
from wildscope_analytics import analyze, AnalysisRequest, AnalysisMetric
snap, report = import_caltech_snapshot(
    'caltech_camera_traps.json',
    max_images=500,
    timezone_policy='US/Pacific',   # analyst-supplied; not in dataset
)
print(f'Imported: {report.total_images_imported} images across {report.total_cameras} cameras')
req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
resp = analyze(snap, req)
print(resp.model_dump_json(indent=2))
"
```

### Important: dataset-reference analytics are not model accuracy

- These are official human-annotated ground-truth labels.
- Counts are **image-level** (not encounter-based; CCT has no encounter grouping).
- `encountered_animal_encounters` in reference mode means **annotated images**, not encounters.
- Never present these as WILDSCOPE model performance metrics.

---

## 6. Runnable Commands

```bash
# 1. Install dependencies
pip install -e ".[dev]"

# 2. Run all tests
python -m pytest tests/ -v

# 3. Regenerate JSON schemas
python wildscope_analytics/schema_generator.py

# 4. Import real Caltech annotations (after download)
python -c "from wildscope_analytics.caltech_adapter import import_caltech_snapshot; snap, r = import_caltech_snapshot('caltech_camera_traps.json'); print(r)"

# 5. Run analytics on the valid_snapshot.json example (operational)
python -c "
from wildscope_analytics import analyze, load_and_validate_snapshot, AnalysisRequest, AnalysisMetric
snap, _ = load_and_validate_snapshot('examples/valid_snapshot.json')
resp = analyze(snap, AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS))
print(resp.model_dump_json(indent=2))
"
```

---

## 7. Files Created / Modified in Phase 2

| File | Change |
|---|---|
| `wildscope_analytics/contracts/enums.py` | +`DataSourceMode`, `ReviewOrderingMechanism`, `AnnotationSource`; extended `AnalysisMetric`; extended `ValidationErrorCode` |
| `wildscope_analytics/contracts/entities.py` | +`DatasetReferenceAnnotation`; +`ReviewEvent.sequence_number` |
| `wildscope_analytics/contracts/snapshot.py` | Schema 1.1.0; +`data_source_mode`, `review_ordering_mechanism`, `reference_annotations` on Snapshot |
| `wildscope_analytics/contracts/__init__.py` | Exports new Phase 2 types |
| `wildscope_analytics/__init__.py` | Imports from `analytics.py`; exports new types |
| `wildscope_analytics/analytics.py` | **NEW** — effective-label resolver + 7 metric implementations + dispatcher |
| `wildscope_analytics/caltech_adapter.py` | **NEW** — Caltech CCT dataset adapter |
| `wildscope_analytics/schema_generator.py` | +`DatasetReferenceAnnotation` schema export |
| `schemas/dataset_reference_annotation.schema.json` | **NEW** generated schema |
| `schemas/*.schema.json` | Regenerated with 1.1.0 fields |
| `tests/test_phase2_analytics.py` | **NEW** — 71 Phase 2 tests |
| `tests/test_validation.py` | Updated `test_analyze_on_valid_snapshot` to validate Phase 2 behaviour |
| `docs/team_handoff.md` | This document |

---

## 8. Phase 3 Scope (Not Yet Implemented)

`rank_review()` returns `status=unavailable` with an explicit Phase 3 note.
Do not implement anomaly detection, cross-camera animal identity association, geofencing, or infrastructure scenarios in Phase 2.
