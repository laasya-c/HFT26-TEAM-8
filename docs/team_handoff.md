# WILDSCOPE Team Handoff — Phase 2, Phase 3 & Phase 4

> **Prepared by:** Shravan (Analytics & Decision Intelligence Lead)
> **Phase:** Phase 2 (Activity Analytics), Phase 3 (Review Prioritisation — F18), and Phase 4 (Cross-Camera Observation Correlation — F06)
> **Status:** Complete. `analyze()`, `rank_review()`, and `find_cross_camera_associations()` are fully implemented and verified.
> **Schema version:** `1.3.0` (fully backward-compatible with `1.2.0`, `1.1.0` and `1.0.0`)
> **Branch:** `shravan`
> **Test Suite:** **202 passed, 1 skipped** (1 skipped case tests absent-file fallback; real 1,000-image dataset integration verified passing)

---

## 0. Executive Summary of Implementation

| Capability | Phase 1 Baseline | Phase 2 Analytics | Phase 3 Decision Intelligence | Phase 4 Cross-Camera Correlation (F06) |
|---|---|---|---|---|
| `analyze()` | `UNAVAILABLE` | **Fully implemented** (7 core metrics) | Extended with `reference_image_species_counts` and explicit encounter statuses | Extended with `cross_camera_associations` operation |
| `rank_review()` | `UNAVAILABLE` | `UNAVAILABLE` (deferred) | **Fully implemented** (Feature F18: marginal sensitivity ranking) | Stable parity preserved |
| `find_cross_camera_associations()` | `UNAVAILABLE` | `UNAVAILABLE` | `UNAVAILABLE` | **Fully implemented** (Feature F06: sliding-window encounter correlation) |
| Schema Version | `1.0.0` | `1.1.0` | `1.2.0` | **`1.3.0`** (additive, backward-compatible) |
| Data Source Modes | None | `operational_prediction` / `dataset_reference` | Enforced: operational only for `rank_review()` | Enforced: operational only for cross-camera correlation |
| Encounter Capability | Implicit (`encounters == []`) | Inferred from presence | Explicit via `EncounterProcessingStatus` | Full lifecycle support (completed empty vs pending/unavailable) |
| Category Mapping | Broad mapping | Documented CCT categories | Mapped categories | **Part B fix:** explicit non-animal for vehicles/people; unmapped wildlife visible |
| Spatial Modes | None | None | None | `time_species_only`, `spatial_when_available`, `spatial_required` |
| Clock Policies | Implicit | Zone-aware | Zone-aware | `documented_sync`, `analyst_assumption`, `offsets_known`, `unknown` |
| Tests Passing | 38 | 117 passing | 166 passing (1 skipped) | **202 passing, 1 skipped** |

---

## 1. Public Analytics & Decision Intelligence Interfaces

WildScope exports two primary public entrypoints from `wildscope_analytics`:

### 1.1 `analyze(snapshot, request) -> AnalysisResponseEnvelope`
Computes wildlife activity analytics across cameras, encounters, dates, and hours.

Supported `AnalysisMetric` values:
1. `overview`: Global snapshot summary (cameras, encounters, time span, detection and review triage breakdown).
2. `species_encounter_counts`: Deduplicated encounter/species pairs across cameras.
3. `camera_comparison`: Multi-camera or pairwise encounter/species breakdown.
4. `daily_activity`: Encounter counts binned by calendar day in target timezone.
5. `hourly_activity`: Diel 24-hour encounter distribution in target timezone.
6. `species_camera_matrix`: Species × camera encounter contingency matrix.
7. `effort_normalised_rates`: Encounters per active camera-day (requires monitoring effort records).
8. `reference_image_species_counts`: Explicit image-level species counts for ground-truth reference datasets (e.g. Caltech Camera Traps).

### 1.2 `rank_review(snapshot, request) -> AnalysisResponseEnvelope`
Computes conclusion-sensitive review prioritisation (Feature F18). Evaluates candidate detections one at a time and ranks them by how much a reviewer's decision could alter key management conclusions:
$$\text{Marginal Impact} = \max_{\text{alt}} |\text{Metric}(\text{Candidate} \to \text{alt}) - \text{Baseline Metric}|$$

Supported `target_metric` values:
1. `AnalysisMetric.SPECIES_ENCOUNTER_COUNTS`: Evaluates marginal impact on focal `target_species_id` encounter count.
2. `AnalysisMetric.CAMERA_COMPARISON`: Evaluates marginal impact on pairwise camera difference $\text{Count}(cam_A) - \text{Count}(cam_B)$ for focal `target_species_id`.

---

## 2. Phase 2 Backend Gap Closures & Precise Semantics

### 2.1 Encounter Capability vs Empty Results (`EncounterProcessingStatus`)
In earlier revisions, `snapshot.encounters == []` ambiguously represented either "pipeline failed to group" or "grouping completed with 0 encounters".

In Schema `1.2.0`, `SnapshotMetadata.encounter_processing_status` explicitly distinguishes these states:
- `COMPLETED`: Encounter grouping pipeline ran to completion. If `snapshot.encounters == []`, operations return valid **zero counts** (`total_encounters: 0`, `species_entries: []`) with `status = ResponseStatus.OK`.
- `PENDING`: Grouping is currently running in background jobs. Encounter-dependent metrics return `ResponseStatus.UNAVAILABLE` with explanation.
- `FAILED`: Grouping failed in upstream pipeline. Returns `ResponseStatus.UNAVAILABLE`.
- `UNAVAILABLE` or `None` (legacy compatibility): If encounters list is empty and status is absent or unavailable, analytics safely and conservatively returns `ResponseStatus.UNAVAILABLE`.

### 2.2 Response Status Semantics Matrix
| Status | Exact Meaning | Conditions / Behavior |
|---|---|---|
| `ok` | Flawless computation | All records in scope have valid timestamps, resolved labels, effort intervals, and 0 exclusions. |
| `partial` | Usable results with exclusions | Some encounters lack timestamps for diel bins, detections below confidence threshold, ambiguous review conflicts present, or candidate list truncated by `max_records_to_rank`. |
| `insufficient_data` | Prerequisite exists but lacks required data | Monitoring effort exists but covers 0 active camera-days in the requested window; encounters exist but all lack timestamps for hourly binning. |
| `unavailable` | Entirely absent capability or prerequisite | Effort rates requested on snapshot with no effort records; operational encounter metrics requested when grouping is pending/unavailable; `rank_review()` called on `dataset_reference` snapshots. |
| `invalid_request` | Precondition or contract error | Target species omitted for ranking; identical cameras supplied to pairwise comparison; optimistic concurrency conflict (`expected_revision != snapshot.metadata.dataset_revision`). |

### 2.3 Reference-Mode Naming & Units
- When evaluating `dataset_reference` snapshots, image-level annotations must never masquerade as encounter counts.
- **New Metric:** `AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS` is the official operation for reference datasets. Units are strictly `"annotated images"`.
- **Deprecation Policy:** Calling `SPECIES_ENCOUNTER_COUNTS` on reference snapshots is supported for backward-compatibility but returns image-level counts with `metric_units = "annotated images (reference mode)"` and emits an explicit deprecation warning in `AnalysisResponseEnvelope.warnings`.

---

## 3. Phase 3: Conclusion-Sensitive Review Engine (Feature F18)

### 3.1 Core Workflow & Architecture
```
ReviewRankingRequest
        │
        ▼
Validation & Revision Lock ──(Mismatch)──► INVALID_REQUEST
        │
        ▼
Baseline Metric Calculation (analyze engine)
        │
        ▼
Candidate Discovery & Filtering
  ├── Must be operational prediction
  ├── Within requested camera_ids and time window
  ├── Member of at least one encounter in scope
  ├── Exclude finally resolved (confirm, correct, mark_unknown)
  ├── Exclude rejected / empty frame detections
  ├── Exclude ambiguous review conflicts (reported in partial status)
  └── Confidence margin <= threshold OR FLAG_FOR_EXPERT
        │
        ▼
Isolated Counterfactual Simulation (One candidate at a time)
  ├── For each documented model alternative (or allow_unknown / allow_rejection)
  ├── Recompute encounter-level species presence with candidate substituted
  ├── Delta = Counterfactual Value - Baseline Value
  └── Record signed_delta, absolute_delta, and dynamic explanation
        │
        ▼
Ranking & Deduplication
  ├── Filter zero impact (unless include_zero_impact=True)
  ├── Sort by max_absolute_impact descending
  ├── Stable tie-break by detection_id ascending
  └── Return top-k by result_limit (complete response, status=ok)
        │
        ▼
AnalysisResponseEnvelope (Typed ReviewRankingResult payload)
```

### 3.2 Candidate Eligibility & Score Space Rules
A Detection is eligible for conclusion-sensitive review ranking if and only if:
1. **Operational Inference:** Snapshot mode is `operational_prediction`.
2. **In-Scope Encounter:** Belongs to an encounter matching the requested cameras and time window.
3. **Unresolved Triage State:** Not previously resolved by human review (`CONFIRM_SPECIES`, `CORRECT_SPECIES`, `MARK_UNKNOWN`, or `REJECT_DETECTION`).
4. **Honest Documented Alternatives:** Possesses alternative candidate taxa from the vision classifier (`alternatives` list). If parameters `allow_unknown_alternative` or `allow_rejection_alternative` are enabled, synthetic review outcomes `__unknown__` and `__rejected__` are also evaluated.
5. **Score Space & Ambiguity Margin Threshold:**
   - **Default Threshold:** `score_margin_threshold = 0.25` in $[0.0, 1.0]$.
   - **Score Space Integrity:** Margin is computed strictly between species classification confidence (`classification_confidence`) and alternative species scores from the same classifier score space. It **never** compares animal detection confidence (`animal_detection_confidence`) with species scores.
   - **Missing or Incomparable Scores:** If `classification_confidence` is missing (`None`) or `score_type` is uncalibrated raw logits (`ScoreType.RAW`), a probability margin cannot be computed. Rather than inventing an artificial margin, the candidate is handled explicitly as uncertain and **remains eligible** for review.
   - **Unambiguous Exclusion:** When comparable probability scores exist and candidate is not flagged for expert (`FLAG_FOR_EXPERT`), candidates with $\text{classification\_confidence} - \text{top\_alt\_score} > \text{score\_margin\_threshold}$ are excluded as unambiguous.

### 3.3 Result Limit vs Evaluation Limit Separation
- **`result_limit` (or `max_records_to_rank`, default: 50):** The engine evaluates all eligible candidates in scope, then returns the top-k highest-impact results. Requesting fewer results does **NOT** mark an otherwise complete response as `partial`.
- **`evaluation_limit` (default: None):** Bounding parameter to cap simulation cost (e.g. evaluating only the first $N$ candidates). When applied, the engine reports incomplete ranking coverage and `evaluation_policy` in limitations, and marks the response status as `partial`.

### 3.4 Encounter Deduplication & Baseline Parity with analyze()
- **Baseline Parity:** `rank_review()` computes baseline values using the exact same filtering, encounter timestamps, detection eligibility, and `min_confidence` rules as `analyze()`. For identical parameters, `rank_review().baseline_value` is verified to match `analyze()` counts to the exact integer.
- **Encounter Deduplication Preservation:** If an encounter already contains Detection 1 (confirmed Bobcat), relabelling Detection 2 to Bobcat does **not** increase encounter count. Its marginal impact is evaluated as `0.0` and filtered out by default (unless `include_zero_impact=True`).

### 3.5 Non-Additive Marginal Sensitivity Disclaimer & Counterexample
> [!IMPORTANT]
> Marginal sensitivity is computed **one candidate at a time**. Marginal changes from individual candidates **CANNOT be summed** to predict the effect of reviewing multiple detections jointly.

#### Mathematical Counterexample:
- **Scenario:** Single encounter containing Detection A (predicted Coyote) and Detection B (predicted Coyote). Both have alternative Lynx. Target metric: Lynx encounter count.
- **Baseline Lynx encounters:** $0$.
- **Marginal evaluation of Candidate A:**
  If A is corrected to Lynx, the encounter becomes a Lynx encounter. $\Delta_A = +1$.
- **Marginal evaluation of Candidate B:**
  If B is corrected to Lynx, the encounter becomes a Lynx encounter. $\Delta_B = +1$.
- **Naive Sum of Marginals:** $\Delta_A + \Delta_B = +2$.
- **Actual Joint Review:**
  If a reviewer resolves **both** A and B to Lynx, the encounter contains Lynx.
  The actual encounter count becomes $1$.
  $$\Delta_{\text{joint}} = 1 \ne \Delta_A + \Delta_B$$
- **Contract Guarantee:** Every `rank_review()` response envelope includes this explicit warning in `limitations` and `ReviewRankingResult.marginal_analysis_disclaimer`.

---

## 4. Instructions for Team Roles

### 4.1 For Harsh (Detection, Classification & Encounter Grouping)
1. **Documented Alternatives:** Vision models should populate `alternatives: list[TaxonAlternative]` on Detection records when classification confidence is below 0.85. Provide realistic candidate species from model softmax distribution. Do not fabricate alternatives if none exist.
2. **Encounter Grouping Status:** Always populate `SnapshotMetadata.encounter_processing_status`:
   - Set to `COMPLETED` when `group_encounters()` has completed (even if 0 encounters resulted).
   - Set to `PENDING` when encounter grouping job is queued or in-flight.
3. **Preserve Immutability:** Detections output from the vision pipeline are immutable ground observations. Never overwrite `predicted_taxon_id` or `classification_confidence`.

### 4.2 For Santosh (Backend, APIs & Persistence)
1. **Schema Version 1.2.0:** Use `schema_version = "1.2.0"` for all new snapshot exports.
2. **Review Event Sequencing:** Continue storing monotone `sequence_number` per target detection:
   ```sql
   INSERT INTO reviews (id, target_id, decision, corrected_taxon_id, sequence_number, reviewer, created_at)
   VALUES ($1, $2, $3, $4, nextval('review_seq_' || $2), $5, NOW());
   ```
   If duplicate or tied sequence numbers occur with conflicting decisions, the analytics engine flags them as unresolvable conflicts and excludes them with an explicit data defect warning.
3. **Optimistic Revision Guarding:** Pass `request.expected_revision` to both `analyze()` and `rank_review()`. If `expected_revision != snapshot.metadata.dataset_revision`, the call immediately returns `INVALID_REQUEST` without running expensive computations.
4. **Append-Only Reviews:** Never modify historical review events. Post-review changes must be committed as new review events with incremented sequence numbers.

### 4.3 For Laasya (Frontend & Review Interface)
1. **Review Priority Queue Display:**
   - Consume `response.result.candidates` from `rank_review()`.
   - Render in order of `rank` (1 = highest priority).
   - Display `explanation` directly in the UI as the justification for why this candidate was queued.
   - Show `max_absolute_impact` as the metric sensitivity score.
2. **Non-Additivity Warning:** Display the `marginal_analysis_disclaimer` above the review queue:
   *"Priority reflects single-candidate marginal sensitivity. Reviewing multiple detections in the same encounter will have deduplicated joint effects."*
3. **Handling Statuses:**
   - If `status == "partial"`: Show warning banner with `exclusion_reasons` and `limitations` (e.g. truncated list or ambiguous review records).
   - If `status == "invalid_request"` with revision error: Prompt the reviewer that the dataset was updated and trigger a background refresh.

---

## 4. Phase 4: Cross-Camera Observation Correlation (Feature F06)

### 4.1 Purpose and Critical Scientific Interpretation
Cross-camera correlation finds pairs of recorded encounters from different cameras that satisfy explicit species and temporal rules, optionally applying spatial rules when genuine spatial coordinates exist.

> [!CRITICAL]
> A match means: **"Possible association between recorded sightings under the configured rules."**
> It does **NOT** establish:
> - The same individual animal.
> - A confirmed movement between cameras.
> - A migration route or wildlife corridor.
> - A known travel speed.
> - A probability of individual identity.
>
> Same-species sightings close in time can be coincidental. Every result strictly preserves this limitation.

### 4.2 Architectural Design & Rules
- **Entry Points:**
  - Unified entry point: `analyze(snapshot, request)` with `AnalysisMetric.CROSS_CAMERA_ASSOCIATIONS` and explicit parameters (e.g. `clock_comparability_policy`).
  - Dedicated entry point: `find_cross_camera_associations(snapshot, request)` accepting either `CrossCameraAssociationRequest` or `AnalysisRequest`.
  - Both entry points have identical analytical semantics and verified parity.
- **Primary Inputs & Prerequisites:**
  - Operational encounters from Harsh/Santosh with timezone-aware start and end timestamps.
  - GPS coordinates are **optional** for `time_species_only` mode (and optional for `spatial_when_available`). Missing GPS coordinates do NOT prevent valid time/species analysis.
  - Calibrated probabilities are **not required** for rule-based association; the engine operates on categorical species decisions (effective labels) and configurable classification confidence cutoffs (`min_confidence`).
  - Detection terminology is strictly maintained: `animal_detection_confidence` (presence of an animal, detector output) is kept distinct from `classification_confidence` (species classification score, classifier output).
- **Species Resolution:** Evaluates member detection effective labels using Phase 2 rules. Excludes rejected detections, empty frames, non-animal triggers, unreviewed predictions (under `REVIEWED_ONLY`), and ambiguous review conflicts. Deduplicates repeated detections within an encounter.
- **Exact Taxon Matching:** Encounters associate only when their eligible species sets share at least one concrete taxon. `unknown` animal taxa never match one another.
- **Camera Separation:** Compares only encounters from different cameras (`camera_id_a != camera_id_b`). Excludes same-camera pairs and self-pairs.
- **Temporal Interval Gap & Uncertainty Propagation:**
  $$\text{nominal\_gap} = \max(0.0, (B.\text{start} - A.\text{end}).\text{total\_seconds}(), (A.\text{start} - B.\text{end}).\text{total\_seconds}())$$
  - `clock_uncertainty_seconds` represents the **combined pairwise clock-offset uncertainty bound** $U_{\text{pair}} \ge 0$ between cameras ($U_{\text{pair}} = u_A + u_B$).
  - **Possible Gap Range & Exact Extrema:**
    - While $[\max(0, G - U_{\text{pair}}), G + U_{\text{pair}}]$ provides a conservative enclosure, the upper endpoint $G + U_{\text{pair}}$ is not always attainable for overlapping intervals (e.g. an interval nested within a longer interval remains overlapping under all shifts $|u| \le U$, so its true maximum gap is 0.0s).
    - The engine calculates the **exact attainable extrema** from relative interval positions:
      $$\text{min\_possible\_gap\_seconds} = \max(0.0, G - U_{\text{pair}})$$
      $$\text{max\_possible\_gap\_seconds} = \max\Big(0.0,\; (s_B - e_A) + U_{\text{pair}},\; (s_A - e_B) + U_{\text{pair}}\Big)$$
  - $\text{effective\_gap\_seconds} = \text{min\_possible\_gap\_seconds}$ is the conservative lower bound of this range, **NOT a definitive corrected gap**.
  - **Threshold Eligibility:** Encounters satisfy the temporal rule if $\text{min\_possible\_gap\_seconds} \le \text{max\_temporal\_separation\_seconds}$ (**possibly within the temporal window**).
  - Pairs where $\text{max\_possible\_gap\_seconds} \le \text{max\_temporal\_separation\_seconds}$ are classified as `definitely_within_threshold`, whereas others are classified as `possibly_within_threshold`.
  - Overlapping intervals: nominal gap is 0.0s; described as overlapping recorded intervals without asserting movement direction.
  - Disjoint intervals: reports observed interval order (`A_before_B` or `B_before_A`) without equating this to animal travel.
- **Clock Comparability Policies:**
  - `DOCUMENTED_SYNC`: Verified physical clock synchronization across deployment (NTP, GPS, or calibration audit).
  - `ANALYST_ASSUMPTION`: Explicit analyst policy assuming synchronization within stated limits.
  - `OFFSETS_KNOWN`:
    - **Uncertainty bounds alone do NOT satisfy `OFFSETS_KNOWN`** (`clock_uncertainty_seconds > 0` and clock-offset corrections are distinct concepts).
    - Requires either:
      1. **Valid per-camera `clock_offsets` dict** in `parameters`: mapping `camera_id -> float (seconds)`.
         - *Sign convention:* $t_{\text{corrected}} = t_{\text{raw}} + \text{offset\_seconds}$. A positive offset advances a slow clock; a negative offset delays a fast clock.
         - *Non-mutation:* Applied to encounter start and end times for sorting, sliding-window pruning, and gap calculations without mutating the source snapshot.
         - *Missing offsets:* Scoped cameras missing from `clock_offsets` return `INSUFFICIENT_DATA`.
         - *Non-finite values:* Non-finite offset values (NaN, inf) return `INVALID_REQUEST`.
         - *Chronological ordering:* Chronological order is established *after* offset application, ensuring encounters are ordered and pruned correctly.
      2. **Pre-corrected timestamps:** `parameters['timestamps_pre_corrected'] = True` with mandatory `parameters['correction_provenance']`. Omitting provenance returns `INSUFFICIENT_DATA`.
    - *Ambiguous double correction:* Supplying both `clock_offsets` and `timestamps_pre_corrected = True` returns `INVALID_REQUEST`.
  - `UNKNOWN`: Inter-camera clock alignment is unverified; returns `INSUFFICIENT_DATA`.
- **Spatial Modes:**
  1. `time_species_only`: GPS coordinates optional; `spatial_check_status = "not_evaluated"`.
  2. `spatial_when_available`: Computes approximate spherical great-circle camera separation using WGS84 Haversine distance when coordinates exist; checks `max_spatial_distance_meters` if set. For cameras lacking GPS, retains eligible time/species candidate with `spatial_check_status = "unavailable"`.
  3. `spatial_required`: Evaluates only pairs with valid coordinates. If no cameras have GPS, returns `UNAVAILABLE`.
  - *Mandatory Spatial Limitation:* Approximate spherical great-circle camera separation is strictly distinct from animal travel distance; biological movement feasibility is not validated.
- **Pair Deduplication & Non-Greedy Retention:**
  - Canonical order: `association_id = f"assoc:{min(id_a, id_b)}::{max(id_a, id_b)}"`. No mirrored duplicates.
  - All plausible candidates are retained within declared scope (no greedy 1-1 winner-take-all matching).
  - No transitive identity: $A \leftrightarrow B$ and $B \leftrightarrow C$ do not imply $A \leftrightarrow C$ or merge encounters.
- **Limits & Performance:**
  - `result_limit`: Evaluates declared scope, returns top-k. Response status remains `OK`.
  - `evaluation_limit`: Bounds pair simulation; reports `evaluation_policy`, sets `is_coverage_complete = False`, and sets status to `PARTIAL`.
  - Performance: Sliding-window indexing by species and sorted start times verified for exact parity against an exhaustive $O(N^2)$ reference implementation, including edge cases with non-zero uncertainty and long overlapping encounters.

### 4.3 Category Mapping Corrections (Part B)
- **Verified Official Caltech Category IDs & Names (`caltech_images_20210113.json`):**
  - **Category ID 30 (`name = "empty"`):** Mapped to `is_animal = False, is_empty = True`.
  - **Category ID 33 (`name = "car"`):** Mapped to `is_animal = False, is_empty = False`.
  - **Category IDs 1, 3, 5, 6, 7, 8, 9, 10, 11, 14, 16, 21, 34, 37, 39, 40, 51, 66, 97, 99:** All 20 wildlife categories mapped to `is_animal = True, is_empty = False` with corresponding WildScope taxon IDs (e.g. ID 9 `canis_latrans`, ID 6 `lynx_rufus`, ID 40 `puma_concolor`).
- Explicit vehicle and person categories (`car`, `vehicle`, `truck`, `motorcycle`, `person`, `human`, `pedestrian`) are classified as `is_animal = False, is_empty = False`.
- `empty` remains distinct as `is_animal = False, is_empty = True`.
- Unmapped wildlife remains visible as unresolved animal taxa in `categories_unmapped`.
- Truly unknown categories without clear indicators are flagged with warnings and not silently assumed to be animals.

---

## 5. Team Handoff Requirements for Phase 4

### For Harsh (Vision & Clustering):
1. **Valid Encounter Groupings:** Cross-camera correlation requires encounters with timezone-aware `start_time` and `end_time` intervals. Missing timestamps result in records being excluded.
2. **Member Detections & Taxa:** Encounters must reference valid `member_detection_ids`. Operational predictions must include `classification_confidence` for cutoff filtering.
3. **No Reference Masquerading:** Caltech CCT reference datasets contain image annotations, not temporal encounter groupings. Do not fabricate encounter memberships on reference snapshots.

### For Santosh (Backend & Persistence):
1. **Clock Metadata:** Populate `clock_comparability_policy` and `clock_uncertainty_seconds` based on camera trap deployment records (e.g. NTP sync status, field clock drift audits).
2. **Camera Coordinates:** When GPS coordinates are recorded in deployments, populate `Camera.latitude` and `Camera.longitude` (WGS84 decimal degrees).
3. **Immutable Snapshots & Revisions:** Enforce optimistic locking via `SnapshotMetadata.dataset_revision`. Any review event or grouping change must increment the revision.

### For Laasya (Frontend & Presentation):
1. **Mandatory Scientific Disclaimer:** Every association card or visualization must prominently state:
   *"Possible association only; individual animal identity and movement are not established."*
2. **Spatial Status Labeling:**
   - If `spatial_check_status == "not_evaluated"` or `"unavailable"`: Display *"Camera distance is unknown or not evaluated; spatial feasibility was not evaluated."*
   - If `spatial_check_status == "passed"` or `"measured"`: Display measured camera separation in meters with the note: *"Camera separation is not animal travel distance; biological movement feasibility is not validated."*
3. **Overlapping vs Disjoint Intervals:** Clearly distinguish overlapping intervals (simultaneous recorded sightings, no travel order) from disjoint intervals (earlier vs later encounter). Do not draw directional arrows for overlapping intervals.
4. **All Plausible Candidates:** Present all candidate associations for a given encounter without artificially picking a single "best match".

---

## 5. Caltech Camera Traps Real Dataset Integration

### 5.1 Sandbox Blocker Details
In standard development sandbox mode, outbound network requests to Azure Blob storage fail:
```
socket.gaierror: [Errno 11001] getaddrinfo failed
```
As per integration instructions, synthetic benchmarks and mocks verified all logic; the real dataset test remains safely skipped in the automated harness without fabricating results.

### 5.2 Commands to Download and Run Caltech Integration
To execute the real dataset import and analytics on Windows PowerShell outside sandbox restrictions:

```powershell
# 1. Download official Caltech Camera Traps annotations archive (verified Lila Wildlife URL)
Invoke-WebRequest -Uri "https://lilawildlife.blob.core.windows.net/lila-wildlife/caltechcameratraps/labels/caltech_camera_traps.json.zip" -OutFile "caltech_camera_traps.json.zip"

# 2. Extract archive
Expand-Archive -Path "caltech_camera_traps.json.zip" -DestinationPath "." -Force

# 3. Run reference analytics via adapter CLI
python -m wildscope_analytics.caltech_adapter caltech_camera_traps.json --max-images 1000 --timezone US/Pacific --metric reference_image_species_counts

# 4. Run the integration test suite against the local file
$env:CCT_ANNOTATION_FILE = "caltech_camera_traps.json"
python -m pytest tests/test_phase2_analytics.py::TestCaltechRealDatasetIntegration -v -s
```

---

## 6. Runnable Verification Commands

```powershell
# 1. Run complete test suite (203 tests)
python -m pytest tests/ -v

# 2. Run Phase 4 association test suite specifically
python -m pytest tests/test_phase4_associations.py -v

# 3. Regenerate all JSON Schemas in schemas/
python -m wildscope_analytics.schema_generator

# 4. Verify unified analyze() with explicit clock_comparability_policy in interactive Python
python -c "
from wildscope_analytics import Snapshot, load_and_validate_snapshot, analyze, AnalysisRequest, AnalysisMetric
snap, _ = load_and_validate_snapshot('examples/valid_snapshot.json')
req = AnalysisRequest(
    metric=AnalysisMetric.CROSS_CAMERA_ASSOCIATIONS,
    parameters={
        'clock_comparability_policy': 'analyst_assumption',
        'max_temporal_separation_seconds': 3600.0,
        'spatial_mode': 'time_species_only',
    }
)
resp = analyze(snap, req)
print('Unified Status:', resp.status)
print('Matching pairs:', resp.result['total_matching_pairs_found'])
"

# 5. Verify dedicated find_cross_camera_associations() in interactive Python
python -c "
from wildscope_analytics import load_and_validate_snapshot, find_cross_camera_associations, CrossCameraAssociationRequest
snap, _ = load_and_validate_snapshot('examples/valid_snapshot.json')
req = CrossCameraAssociationRequest()
resp = find_cross_camera_associations(snap, req)
print('Dedicated Status:', resp.status)
print('Matching pairs:', resp.result['total_matching_pairs_found'])
"
```

---

## 7. Complete Artifact & Schema Inventory

### Schemas Generated (`schemas/`):
- `snapshot.schema.json` (Schema v1.3.0)
- `analysis_request.schema.json`
- `cross_camera_association_request.schema.json`
- `review_ranking_request.schema.json`
- `analysis_response.schema.json`
- `cross_camera_associations_result.schema.json`
- `dataset_reference_annotation.schema.json`
- `review_ranking_result.schema.json`

### Code Modules:
- `wildscope_analytics/contracts/`: Data contracts, Pydantic models, request/response models.
- `wildscope_analytics/analytics.py`: Effective-label resolver, encounter capability dispatcher, 8 activity metrics.
- `wildscope_analytics/ranking.py`: Conclusion-sensitive review ranking engine (Feature F18).
- `wildscope_analytics/associations.py`: Cross-camera observation correlation engine (Feature F06).
- `wildscope_analytics/caltech_adapter.py`: Ground-truth dataset importer.
- `wildscope_analytics/validation.py`: Snapshot referential integrity and schema validator.
- `wildscope_analytics/analytics.py`: Effective-label resolver, encounter capability dispatcher, 8 activity metrics.
- `wildscope_analytics/ranking.py`: Conclusion-sensitive review ranking engine (isolated counterfactual simulation, encounter deduplication, dynamic explanations).
- `wildscope_analytics/caltech_adapter.py`: Ground-truth dataset importer.
- `wildscope_analytics/validation.py`: Snapshot referential integrity and schema validator.
