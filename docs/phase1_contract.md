# WILDSCOPE Phase 1: Shared Data Contracts & Validation Specification

> **Module:** Analytics & Decision Intelligence (`wildscope_analytics`)  
> **Author / Lead:** Shravan (Integration Architect & Analytics Lead)  
> **Schema Version:** `1.0.0`  
> **Status:** Proposed v1 Shared Team Contract (Pending Team Consensus)

---

## 1. Architectural Purpose & Scope

WILDSCOPE converts raw camera-trap imagery and videos into traceable, reviewable wildlife evidence. 
The core philosophy is **sound data integrity before analytical claims**:
- We never invent missing data (e.g. no fake GPS coordinates, no invented animal trajectories, no assumed camera uptime).
- Original model predictions remain immutable; human reviews are recorded as append-only audit events.
- An encounter represents an operational grouping of observations within a temporal session; it does **not** assert unique individual animal identity or population size.
- Machine learning scores are model outputs with documented calibration status, not guaranteed posterior probabilities.

Phase 1 establishes strongly-typed Pydantic v2 data models, strict relational validation, JSON Schema definitions, and standardized response envelopes. Machine learning inference, UI dashboards, and mathematical analytics algorithms are intentionally deferred to subsequent phases.

---

## 2. Shared Data Models & Field Specifications

### 2.1 Snapshot Metadata (`SnapshotMetadata`)

| Field | Type | Required / Nullable | Description & Semantics |
| :--- | :--- | :--- | :--- |
| `schema_version` | `str` | Required | Contract structure version (e.g. `"1.0.0"`). Governed by semantic versioning. |
| `dataset_revision` | `int` | Required | Transactional counter representing underlying data state in backend storage. |
| `created_at` | `datetime` | Required (TZ-aware) | Point-in-time timestamp when the snapshot was extracted. |
| `source_system` | `str` | Required | Origin identifier (default: `"WILDSCOPE_BACKEND"`). |
| `provenance` | `dict \| str` | Nullable | Audit information detailing data origin and export context. |
| `has_spatial_context` | `bool` | Required | Flag indicating whether GIS reserve layers are populated. |
| `has_monitoring_effort`| `bool` | Required | Flag indicating whether verified camera active intervals are supplied. |

> **Critical Rule:** `schema_version` describes the structural shape of the data contracts; `dataset_revision` describes the state of the underlying records. They are strictly decoupled.

---

### 2.2 Camera (`Camera`)

| Field | Type | Nullable | Description & Validation |
| :--- | :--- | :--- | :--- |
| `id` | `str` | No | Stable unique identifier for the camera trap (e.g. `"cam_core_01"`). |
| `site_id` | `str` | Yes | Station/site cluster identifier for non-geographic hierarchical grouping. |
| `latitude` | `float` | Yes | WGS84 latitude in decimal degrees `[-90.0, 90.0]`. Must be finite. |
| `longitude` | `float` | Yes | WGS84 longitude in decimal degrees `[-180.0, 180.0]`. Must be finite. |
| `timezone` | `str` | Yes | Declared IANA timezone (e.g. `"Asia/Kolkata"`). |
| `provenance` | `dict \| str` | Yes | Camera setup or deployment provenance. |

* **Coordinate Pairing Rule:** Both `latitude` and `longitude` must be provided together, or both omitted. Missing coordinates do not invalidate species counts, but disable spatial GIS features.
* **No Invented Map:** Non-geographic camera groupings use `site_id` or `id`. Synthetic coordinates must never be generated for operational analytics.

---

### 2.3 Media Asset & Observation (`MediaAsset`, `Observation`)

* **MediaAsset:** Represents the uploaded file in object storage (`id`, `media_type` (`image` or `video`), `camera_id` FK, `storage_key`, `raw_timestamp`, `captured_at`, `timezone_source`).
* **Observation:** Represents an individual evaluatable unit (a still photograph or a sampled video frame).

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `str` | No | Stable observation identifier (e.g. `"obs_001"`). |
| `camera_id` | `str` | No | Foreign key referencing valid `Camera.id`. |
| `source_media_id` | `str` | No | Foreign key referencing `MediaAsset.id`. |
| `frame_offset_ms` | `int` | Yes | Video frame presentation offset in milliseconds (null for still images). |
| `captured_at` | `datetime` | Yes | Resolved timezone-aware timestamp. If timezone is unknown, kept `null`. |
| `raw_timestamp` | `str` | Yes | Unmodified EXIF/filename timestamp string preserved for audit. |
| `timezone_source` | `str` | Yes | Source of timezone resolution (e.g. `"camera_profile"`, `"exif_offset"`). |
| `width_px`, `height_px`| `int` | Yes | Resolution in pixels. |
| `detection_ids` | `list[str]` | No | List of Detection IDs detected within this observation. |

---

### 2.4 Animal Detection & Bounding Box (`Detection`, `NormalizedBBox`)

* **NormalizedBBox:** Defined by normalized coordinates `[0.0, 1.0]` relative to frame dimensions.
  * `(x_min, y_min)`: Top-left corner.
  * `(x_max, y_max)`: Bottom-right corner.
  * Enforced: `0.0 <= x_min <= x_max <= 1.0` and `0.0 <= y_min <= y_max <= 1.0`.

* **Detection:**
| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `str` | No | Stable unique detection identifier (e.g. `"det_001"`). |
| `observation_id` | `str` | No | Foreign key referencing `Observation.id`. |
| `run_id` | `str` | Yes | Foreign key referencing `PredictionRun.id`. |
| `triage_state` | `TriageState` | No | `likely_empty`, `animal_detected`, `processing_failure`, or `unsupported_taxon`. |
| `animal_detection_confidence` | `float` | No | Objectness confidence in `[0.0, 1.0]`. Must be finite. |
| `predicted_taxon_id` | `str` | Yes | Standardized species taxon (e.g. `"panthera_tigris"`). Null if empty/unclassified. |
| `raw_label` | `str` | Yes | Unmodified string emitted by model (e.g. `"tiger"`). |
| `classification_confidence` | `float` | Yes | Species classification score in `[0.0, 1.0]`. |
| `score_type` | `ScoreType` | No | `raw`, `softmax`, `calibrated`, or `probability`. |
| `calibration_status` | `CalibrationStatus` | No | `uncalibrated`, `calibrated`, or `not_applicable`. |
| `bbox` | `NormalizedBBox` | Yes | Spatial bounding box if localized. |
| `alternatives` | `list[TaxonAlternative]` | No | Top-k alternative species hypotheses and scores. |

> **Uncertainty & Score Integrity:** Model output scores are **not** assumed to sum to 1.0 across arbitrary top-k classes unless explicitly calibrated as a complete multinomial distribution. Unknown or unsupported species are explicitly tracked and never conflated with empty frames or processing failures.

---

### 2.5 Encounter Record (`Encounter`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `str` | No | Stable unique encounter identifier (e.g. `"enc_001"`). |
| `camera_id` | `str` | No | Foreign key referencing `Camera.id`. |
| `member_observation_ids` | `list[str]` | No | Member observation IDs. Must contain at least one observation or detection. |
| `member_detection_ids` | `list[str]` | No | Member detection IDs. |
| `start_time` | `datetime` | Yes | Timezone-aware encounter start. |
| `end_time` | `datetime` | Yes | Timezone-aware encounter end. Must satisfy `start_time <= end_time`. |
| `rule_version` | `str` | No | Grouping heuristic version (e.g. `"v1_time_gap_30min"`). |
| `provenance` | `dict \| str` | Yes | Audit metadata. |

* **Encounter Rule:** An encounter groups related observations from a single camera trap. All member observations must belong to the encounter's declared `camera_id`. Cross-camera encounters are rejected.

---

### 2.6 Human Review Event (`ReviewEvent`)

| Field | Type | Nullable | Description |
| :--- | :--- | :--- | :--- |
| `id` | `str` | No | Stable unique review event identifier (e.g. `"rev_001"`). |
| `target_id` | `str` | No | Foreign key referencing target `Detection.id`. |
| `decision` | `ReviewDecision` | No | `confirm_species`, `correct_species`, `mark_unknown`, `reject_detection`, `flag_for_expert`. |
| `corrected_taxon_id` | `str` | Conditional | **Required** when decision is `correct_species`; **forbidden** (`null`) when `reject_detection`. |
| `reviewer` | `str` | No | Identifier/username of reviewer (e.g. `"shravan_expert"`). |
| `reason` | `str` | Yes | Reviewer notes or justification. |
| `created_at` | `datetime` | No | Timezone-aware review timestamp. |
| `expected_revision` | `int` | Yes | Snapshot revision counter checked for optimistic concurrency. |

* **Immutability Contract:** Original model outputs in `detections` are **never overwritten**. Reviews are append-only. The effective dataset state is resolved by Santosh's backend during snapshot assembly.

---

### 2.7 Monitoring Effort & Spatial Context (`MonitoringEffort`, `SpatialContext`)

* **MonitoringEffort:** Documented operational intervals `[start, end]` during which a camera was verified active.
  * Uptime is **never** inferred from image frequency or elapsed time between the first and last picture.
  * Overlapping active intervals for the same camera are strictly rejected as ambiguous double-counting.
* **SpatialContext:** CRS (e.g. `EPSG:4326`), reserve zones (GeoJSON polygons), candidate camera deployment sites, and documented viewshed assumptions.
  * Camera coordinates are sensor positions, **not** animal locations.

---

## 3. Required Fields by Future Analytical Feature

| Feature ID | Feature Name | Minimum Required Contract Fields | Fallback / Behavior if Missing |
| :--- | :--- | :--- | :--- |
| **F05 / F10** | Species Encounter Counts | `cameras.id`, `encounters.member_detection_ids`, `detections.predicted_taxon_id` | Baseline raw encounter count. |
| **F10** | Effort-Normalized Activity Rates | `encounters`, `monitoring_efforts.active_intervals` | Returns status `insufficient_data` or `unavailable` with explicit warning; never fabricates zero. |
| **F10 / F12** | Diurnal / Time Distribution | `observations.captured_at` (TZ-aware), `cameras.timezone` or `request.analysis_timezone` | Excludes records with missing timestamps; returns `partial` status. |
| **F06** | Cross-Camera Associations | `cameras.latitude`, `cameras.longitude`, `encounters.start_time`, `encounters.end_time` | Returns `unavailable`; non-geographic topological network fallback. |
| **F08 / F09** | Blind Spots & Placement | `spatial_context.zones`, `cameras.latitude`, `cameras.longitude`, candidate sites | Returns `insufficient_data`; no fabricated geographic map. |
| **F14** | Risk & Virtual Geofencing | `spatial_context.zones`, `cameras.latitude`, `cameras.longitude` | Returns `unavailable` if camera coordinates or reserve zones missing. |
| **F18** | Conclusion-Sensitive Review | `detections.alternatives`, `detections.classification_confidence`, `reviews` | Returns unranked queue if alternatives absent. |

---

## 4. Response Envelope Semantics (`AnalysisResponseEnvelope`)

Laasya (frontend) and Santosh (backend) consume the unified response envelope:

```json
{
  "status": "unavailable",
  "schema_version": "1.0.0",
  "dataset_revision": 4,
  "metric": "species_encounter_counts",
  "applied_filters": {
    "metric": "species_encounter_counts",
    "inclusion_policy": "provisional_and_reviewed"
  },
  "result": null,
  "metric_units": "encounters/camera-day",
  "evidence_references": ["enc_synth_001"],
  "excluded_records_count": 0,
  "exclusion_reasons": [],
  "warnings": [
    "Camera 'cam_02' lacks GPS coordinates; geographical spatial mapping will be unavailable."
  ],
  "limitations": [
    "Analytical algorithm implementations are deferred to Phase 2.",
    "Phase 1 establishes shared data contracts, referential integrity, and validation only."
  ],
  "errors": []
}
```

### Response Status Definitions:
- **`ok`**: Computation executed cleanly on valid, sufficient data.
- **`partial`**: Valid results computed, but specific records were excluded (e.g. missing timestamps excluded from time histograms).
- **`insufficient_data`**: The entity types exist, but quantity or quality is inadequate (e.g. zero effort hours recorded).
- **`unavailable`**: A necessary prerequisite is absent (e.g. spatial polygons missing, model not executed).
- **`invalid_request`**: The request failed validation or encountered an optimistic revision conflict (HTTP 409).
