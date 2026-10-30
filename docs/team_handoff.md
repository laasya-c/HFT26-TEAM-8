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
| Tests | 38 passing | **108 passing, 1 skipped** |

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

### Status semantics (same 5 values, Phase 1 contract)

| Status | Meaning |
|---|---|
| `ok` | Computation completed cleanly |
| `partial` | Usable results; check `excluded_records_count` and `exclusion_reasons` |
| `insufficient_data` | Inputs exist but inadequate (e.g. no encounters, no effort) |
| `unavailable` | Prerequisite absent (e.g. `rank_review` before Phase 3) |
| `invalid_request` | Bad request or revision mismatch; check `errors[]` |

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

No outbound network access from the development sandbox. **You must run the download yourself:**

```bash
# Option 1: Azure blob (HTTP, no auth needed)
curl -L "https://lilawildlife.blob.core.windows.net/lila-wildlife/caltechcameratraps/labels/caltech_camera_traps.json.zip" \
     -o caltech_camera_traps.json.zip
unzip caltech_camera_traps.json.zip

# Option 2: GCP (requires gsutil)
gsutil cp gs://public-datasets-lila/caltechcameratraps/labels/caltech_camera_traps.json.zip .
unzip caltech_camera_traps.json.zip
```

License: Community Data License Agreement - Permissive 1.0 (see lila.science for terms).

### Running the adapter locally

```bash
# Import all images, no timezone (captured_at = null)
python -c "
from wildscope_analytics.caltech_adapter import import_caltech_snapshot
snap, report = import_caltech_snapshot('caltech_camera_traps.json')
print(f'Cameras: {len(snap.cameras)}, Images: {len(snap.observations)}, Annotations: {len(snap.reference_annotations)}')
print(f'Unmapped categories: {report.categories_unmapped}')
"

# Import with timezone and subset
python -c "
from wildscope_analytics.caltech_adapter import import_caltech_snapshot
from wildscope_analytics import analyze, AnalysisRequest, AnalysisMetric
snap, report = import_caltech_snapshot(
    'caltech_camera_traps.json',
    max_images=500,
    timezone_policy='US/Pacific',   # analyst-supplied; not in dataset
)
req = AnalysisRequest(metric=AnalysisMetric.OVERVIEW)
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
