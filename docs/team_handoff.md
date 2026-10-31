# WILDSCOPE Team Handoff — Phase 2, Phase 3, Phase 4 & Phase 5

> **Prepared by:** Shravan (Analytics & Decision Intelligence Lead)
> **Phase:** Phase 2 (Activity Analytics), Phase 3 (Review Prioritisation — F18), Phase 4 (Cross-Camera Observation Correlation — F06), and Phase 5 (Activity Anomaly Indicators — F12)
> **Status:** Complete. `analyze()`, `rank_review()`, `find_cross_camera_associations()`, and `detect_activity_anomalies()` are fully implemented and verified.
> **Schema version:** `1.3.0` (fully backward-compatible with `1.2.0`, `1.1.0` and `1.0.0`)
> **Branch:** `shravan`
> **Test Suite:** **246 passed, 1 skipped** (1 skipped case tests absent-file fallback; real 1,000-image dataset integration verified passing; all 27 Phase 5 tests passing)

---

## 0. Executive Summary of Implementation

| Capability | Phase 1 Baseline | Phase 2 Analytics | Phase 3 Decision Intelligence | Phase 4 Cross-Camera Correlation (F06) | Phase 5 Activity Anomaly Indicators (F12) |
|---|---|---|---|---|---|
| `analyze()` | `UNAVAILABLE` | **Fully implemented** (7 core metrics) | Extended with `reference_image_species_counts` and explicit encounter statuses | Extended with `cross_camera_associations` operation | Extended with `activity_anomaly` operation |
| `rank_review()` | `UNAVAILABLE` | `UNAVAILABLE` (deferred) | **Fully implemented** (Feature F18: marginal sensitivity ranking) | Stable parity preserved | Stable parity preserved |
| `find_cross_camera_associations()` | `UNAVAILABLE` | `UNAVAILABLE` | `UNAVAILABLE` | **Fully implemented** (Feature F06: sliding-window encounter correlation) | Stable parity preserved |
| `detect_activity_anomalies()` | `UNAVAILABLE` | `UNAVAILABLE` | `UNAVAILABLE` | `UNAVAILABLE` | **Fully implemented** (Feature F12: robust MAD dispersion anomaly indicators) |
| `normalize_snapshot_efforts()` | `UNAVAILABLE` | `UNAVAILABLE` | `UNAVAILABLE` | `UNAVAILABLE` | **Fully implemented** (Ingestion normalization for overlapping intervals) |
| Schema Version | `1.0.0` | `1.1.0` | `1.2.0` | `1.3.0` | **`1.3.0`** (additive, backward-compatible) |
| Data Source Modes | None | `operational_prediction` / `dataset_reference` | Enforced: operational only for `rank_review()` | Enforced: operational only for cross-camera correlation | Enforced: operational only (`UNAVAILABLE` on `dataset_reference`) |
| Encounter Capability | Implicit (`encounters == []`) | Inferred from presence | Explicit via `EncounterProcessingStatus` | Full lifecycle support (completed empty vs pending/unavailable) | Full lifecycle support; valid 0 sightings distinct from missing effort |
| Category Mapping | Broad mapping | Documented CCT categories | Mapped categories | Explicit non-animal for vehicles/people; unmapped wildlife visible | Same-species attribution with deduplication per encounter |
| Spatial Modes | None | None | None | `time_species_only`, `spatial_when_available`, `spatial_required` | Per-camera stationarity audit telemetry check |
| Clock / Timezone Policies | Implicit | Zone-aware | Zone-aware | `documented_sync`, `analyst_assumption`, `offsets_known`, `unknown` | Explicit calendar day binning under IANA timezone with DST physical duration accounting |
| Tests Passing | 38 | 117 passing | 166 passing (1 skipped) | 219 passing (1 skipped) | **246 passing, 1 skipped** |

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

## 5. Phase 5: Activity Anomaly Indicators Engine (Feature F12)

### 5.1 Purpose & Scientific Framing
Feature F12 detects reviewable statistical anomalies in recorded wildlife encounter activity relative to an adequate historical baseline at individual camera traps.

> [!IMPORTANT]
> **Critical Interpretation:** Outputs are reviewable statistical indicators—not proof of population change, migration, poaching, camera failure, or ecological causes. Unmonitored intervals, weather, seasonality, and detection probability variation must be evaluated before drawing operational conclusions.

### 5.2 Mathematical Formulation & Rules
1. **Independent Series Scoping:**
   - Multiple cameras and species are evaluated as independent, unpooled series $(cam_i, sp_j)$. Encounters are never merged across cameras.
   - Baseline window: $[T_{\text{base\_start}}, T_{\text{base\_end}})$ (start-inclusive, end-exclusive).
   - Evaluation window: $[T_{\text{eval\_start}}, T_{\text{eval\_end}})$ where $T_{\text{base\_end}} \le T_{\text{eval\_start}}$.
2. **Calendar Day Binning, Monitoring Effort & Mid-Day Windows:**
   - Evaluated under the declared `analysis_timezone` (IANA, e.g. `America/New_York` with physical UTC elapsed duration accounting).
   - **Local Day Duration & DST Transitions:** Actual calendar-day duration $T_{D_k}$ is used (e.g. 23 hours = 82,800s on spring-forward DST days; 25 hours = 90,000s on fall-back DST days). 50% coverage corresponds to 11.5 hours on 23h days, 12h on standard days, and 12.5h on 25h days (correcting any assumption that 50% is always 12h).
   - **Mid-Day Window Boundaries:** For windows starting or ending mid-day (e.g. 14:00), active monitoring seconds are measured within the window slice, but coverage ratio is evaluated relative to the **full local calendar day**. Boundary days with $<50\%$ of the full day monitored are excluded as unrepresentative.
   - **Missing Days vs Valid Zeroes:** Unmonitored days ($E_k = 0$) are excluded from baseline calculations (never zero-filled). Monitored days with 0 encounters are valid zeroes ($R_k = 0.0$). Excluded bins do not contribute encounters to the baseline rate numerator.
3. **Effort Overlap Reconciliation with Phase 1:**
   - **Contract Enforcement:** Snapshots with overlapping effort intervals violate Phase 1 referential integrity and are rejected at the public entrypoint with `INVALID_REQUEST` (`ValidationErrorCode.OVERLAPPING_EFFORT`).
   - **Documented Ingestion Normalization:** For raw logs, `normalize_snapshot_efforts(snapshot)` merges overlapping and contiguous intervals per camera into valid disjoint records prior to analysis.
   - **Contiguous Intervals:** Adjacent intervals across records (e.g. $[0, 12]$ and $[12, 18]$) pass public validation natively and are unified without double-counting.
4. **Robust Baseline Statistics:**
   - Valid days count $M \ge \text{min\_baseline\_days}$ (default 7) and total active effort $\sum E_k \ge \text{min\_baseline\_active\_effort\_days}$ (default 5.0).
   - Baseline Centre: $\tilde{R} = \text{median}(R_1, \dots, R_M)$.
   - Robust Dispersion: $\text{MAD} = \text{median}(|R_k - \tilde{R}|)$.
   - Normal-Consistent Scale: $\sigma_{\text{MAD}} = 1.4826 \times \text{MAD}$.
   - **Dispersion Interpretation:** $\text{MAD} = 0$ indicates that at least 50% of the baseline values equal the median (e.g. in $[0, 0, 0, 0, 1, 2, 3]$, $\text{median}=0$, $\text{MAD}=0$, but values are not all identical). It does *not* prove that all baseline values are identical.
5. **Two-Sided Anomaly Detection & Micro-Alert Prevention:**
   - Evaluation rate: $R_{\text{eval}} = N_{\text{eval}} / E_{\text{eval}}$ (requires both $E_{\text{eval}} \ge \text{min\_evaluation\_active\_effort\_days}$ and $C_{\text{eval}} \ge \text{min\_day\_coverage\_ratio}$).
   - Absolute rate change: $\Delta_{\text{abs}} = R_{\text{eval}} - \tilde{R}$.
   - Relative rate change: $\Delta_{\text{rel}} = \Delta_{\text{abs}} / \tilde{R}$ (only if $\tilde{R} > 0$, avoiding division by zero).
   - Anomaly score: $\text{score} = \Delta_{\text{abs}} / \sigma_{\text{MAD}}$ (only if $\sigma_{\text{MAD}} > 0$).
   - **Two-Sided Thresholds:**
     - `INCREASED`: $\text{score} \ge \theta_{\sigma}$ (default 3.0) AND $\Delta_{\text{abs}} \ge \delta_{\min}$ (default 0.2 encounters/day).
     - `DECREASED`: $\text{score} \le -\theta_{\sigma}$ (default -3.0) AND $\Delta_{\text{abs}} \le -\delta_{\min}$ (default -0.2 encounters/day).
     - `NO_INDICATOR`: Neither rule breached (does not prove ecological normalcy).
     - `NOT_EVALUABLE`: History, evaluation effort, or coverage insufficient.
   - **Two-Sided Zero Dispersion Fallback:** If $\text{MAD} = 0$, allows fallback classification using $\delta_{\min}$ in both directions:
     - Increase fallback: $\Delta_{\text{abs}} \ge \delta_{\min} \to \text{INCREASED}$.
     - Decrease fallback: $\Delta_{\text{abs}} \le -\delta_{\min} \to \text{DECREASED}$.
   - **Exploratory Heuristic Nature:** Comparing an aggregate evaluation rate with daily baseline MAD is an exploratory heuristic (standardized deviation ratio), **not** a calibrated significance level, $p$-value, or probability of true biological change.
6. **Comparability Assessment & Evaluability Policy:**
   - **Absence of records:** Telemetry absence remains `UNASSESSED`.
   - **Affirmative Scoped Provenance:** `VERIFIED_COMPARABLE` requires explicit telemetry (e.g. `camera.provenance` with `{"stationarity_verified": True, "verification_scope": "..."}`).
   - **Physical Stationarity vs Full Analytical Comparability:** Hardware/mount verification confirms physical stationarity of the device, but does not guarantee full analytical comparability because environmental factors (vegetation growth, seasonality, micro-topography, weather) and upstream model/pipeline updates can alter detection probabilities over time.
   - **Distinguishing Telemetry from Pipeline Provenance:** Separates physical camera changes (`repositioned`, `serviced`, `hardware_change`) from model version differences (`prediction_provenance:multiple_model_versions`) and grouping shifts.
   - **Evaluability Policy:** Known repositioning, model, or deployment shifts mark the series as `NOT_EVALUABLE` under default policy, preventing false alerts across non-comparable historical baselines. Setting `allow_suspect_comparability=True` allows analyst override with mandatory `QUALIFIED_INDICATOR` warnings.
7. **Phase 2 Parity:**
   - Active camera-days and in-effort encounter counts match Phase 2 `compute_effort_normalised_rates` exactly for identical cameras and time windows.

### 5.3 Team Handoff Notes
- **Harsh (Detection & Grouping):** Phase 5 reuses existing encounter records and effective labels. When encounter grouping is `PENDING` or `FAILED`, returns clean `UNAVAILABLE`.
- **Santosh (Backend & Telemetry):** Provide verified active effort records in `monitoring_efforts`. Source snapshots with overlapping intervals must be ingested via `normalize_snapshot_efforts(snapshot)`. Telemetry flags in `camera.provenance` (e.g. `{"repositioned": true}`) trigger `SUSPECT_OR_CHANGED` and mark the series `NOT_EVALUABLE` under default policy.
- **Laasya (Frontend):** Use `detect_activity_anomalies()` or `analyze(snapshot, request)`. Render `BaselineDailyBin` for historical audit graphs, display anomaly scores alongside mandatory ecological caveats, and flag `QUALIFIED_INDICATOR` or `NOT_EVALUABLE` series with comparability badges.

---

## 6. Phase 6: Spatial Intelligence Engine (Features F08, F09, F14, F16)

### 6.1 Purpose & Scientific Framing
Phase 6 adds deterministic geometric spatial intelligence for camera trap arrays, protected reserves, and infrastructure corridors.

> [!CRITICAL]
> **Scientific & Interpretive Guardrails:**
> 1. **No Animal Positions from Camera Sites:** Camera coordinates reflect physical mounting locations, NOT animal locations. Camera proximity indicators must NEVER be labeled as "animal geofence crossing".
> 2. **No Wildlife Absence Claims:** Gap polygons reflect areas outside declared or assumed camera coverage, NOT field-validated wildlife absence or animal avoidance.
> 3. **Non-Additivity of Candidate Placements:** Candidate ranks reflect single-site marginal coverage gain over the baseline. Marginal gains are NOT additive; placing multiple candidates simultaneously requires joint combinatorial evaluation.
> 4. **Non-Causal Scenarios:** Infrastructure scenarios model geometric changes in viewsheds and proximity; they do NOT predict ecological impacts, movement route displacement, or population viability.
> 5. **Missing Prerequisite Truthfulness:** Raw reference datasets (e.g. Caltech Camera Traps) do not provide GPS coordinates or study area boundaries. In their absence, operations return `ResponseStatus.UNAVAILABLE` with clear diagnostic warnings, without inventing synthetic coordinates.

### 6.2 Coordinate Representation, Extents & Planar Projection
- **Coordinate Conventions:** GeoJSON coordinate ordering is strictly `[longitude, latitude]` for Points, `[[lon, lat], ...]` for LineStrings, and `[[[lon, lat], ...], ...]` for Polygons.
- **Strict Validation & Extents:**
  - Rejects out-of-bounds coordinates ($lon \notin [-180, 180]$ or $lat \notin [-90, 90]$), non-finite floats (NaN, inf), unclosed rings, and self-intersecting bowtie polygons without silent repair.
  - Rejects antimeridian crossings ($|\Delta \text{lon}| > 180^\circ$ between consecutive vertices); geometries must be pre-split.
  - Rejects polar regions ($|\text{lat}| > 85^\circ$) due to extreme azimuthal distortion.
  - Limits maximum study area extent span to $10.0^\circ$ ($\sim 1,110\text{ km}$), suitable for local reserve deployments.
- **CRS Contracts:** Strictly accepts WGS84 (`"EPSG:4326"`, `"WGS84"`, `"urn:ogc:def:crs:OGC:1.3:CRS84"`). Unsupported CRS values are rejected with `ValidationErrorCode.UNSUPPORTED_CRS`. Projected metric coordinates are never validated against angular degree bounds.
- **Planar Area & Distance Measurement:**
  - Angular degrees are NEVER treated as linear meters or square meters.
  - **Mathematical Model:** Uses spherical Lambert Azimuthal Equal-Area (LAEA) projection centered at the study area or target centroid ($R = 6,371,008.8\text{ m}$).
  - **Edge Densification:** Long polygon or linestring edges in degree space exceeding $0.05^\circ$ ($\sim 5.5\text{ km}$) are automatically densified prior to projection via linear interpolation in longitude/latitude coordinate space. This samples intermediate vertices along coordinate lines (parallels and meridians). Because parallels (lines of constant latitude other than the equator) are small circles that project as curved arcs in LAEA, inserting intermediate points along coordinate lines prevents chord clipping without erroneously treating parallels as geodesics.
  - **Accuracy & Numerical Precision Distinction:**
    - *Numerical Roundtrip Error:* Double-precision IEEE 754 forward and inverse LAEA projection yields roundtrip floating-point error of $\sim 10^{-14}$ degrees (test guards $< 10^{-6}$ deg).
    - *Conversion Units:* In geographic coordinates, $10^{-6}$ degrees latitude is $\approx 0.111\text{ metres}$ ($111\text{ mm}$), while longitude distance varies with latitude as $\approx 0.111 \cdot \cos(\text{lat})\text{ metres}$. It must never be confused with $0.1\text{ millimetres}$.
    - *Spherical-Model Approximation:* The authalic reference sphere introduces $\le 0.5\%$ scale/area discrepancy relative to the WGS84 ellipsoid for local mid-latitude extents.
    - *Benchmark Scoping:* Analytical spherical quad verification proves mathematical correctness on the reference sphere within $1.24 \times 10^{-8}$ relative error, but is not independent proof of WGS84 ellipsoidal measurement accuracy.
    - *Field Measurement Accuracy:* Physical accuracy is bounded by GPS receiver field uncertainty ($3\text{--}15\text{ m}$) and declared sensor detection zones, not projection equation floating-point precision.

### 6.3 Feature Specifications
1. **Feature F08: Possible Monitoring Blind Spots:**
   - Unified metric: `AnalysisMetric.MONITORING_BLIND_SPOTS`.
   - Dedicated helper: `compute_monitoring_blind_spots(snapshot, request)`.
   - Computes: `study_area_sq_meters`, `covered_area_sq_meters`, `uncovered_area_sq_meters`, `coverage_fraction`, and GeoJSON `gap_polygons`.
   - Merges overlapping camera viewsheds without double-counting and clips coverage to study area boundary.
   - **Coverage Inventory Completeness:**
     - Absent coverage records without explicit completeness assertion $\to$ `ResponseStatus.INSUFFICIENT_DATA` (`result = None`).
     - Partial inventory (some cameras missing coordinates) $\to$ `ResponseStatus.PARTIAL` (`is_coverage_complete = False`).
     - Complete inventory confirming zero active cameras (`coverage_inventory_complete=True`) $\to$ `ResponseStatus.OK` (100% gap).
     - Complete active inventory $\to$ `ResponseStatus.OK`.
   - **Dated Geometry Applicability:** Camera coverages with `valid_from` / `valid_to` outside requested evaluation window are excluded with explicit reasons.
2. **Feature F09: Candidate Camera Placement Ranking:**
   - Unified metric: `AnalysisMetric.CANDIDATE_PLACEMENT`.
   - Dedicated helper: `rank_candidate_placements(snapshot, request)`.
   - Evaluates single-site marginal coverage gain $\Delta \text{Area}_k = \text{Area}((\text{Candidate}_k \cap \text{Study Area} \setminus \text{Exclusions}) \setminus \text{Baseline Coverage})$.
   - **Separation of Excluded Candidates:**
     - `ranked_candidates`: contains ONLY eligible candidates (`FEASIBLE` and `REDUNDANT`), ranked sequentially $1, 2, \dots$
     - `excluded_candidates`: contains excluded candidates (e.g. falling inside exclusion zones) with `rank = None`.
   - **Feasibility Semantics:** Zero-gain sites are classified as `REDUNDANT` (physically feasible to deploy, but redundant with existing baseline viewsheds).
   - **Efficiency Scoring:** $\text{score} = \Delta \text{Area}_k / \text{cost}^{\text{cost\_weight}}$ (validating finite $\text{cost} > 0$ and $\text{cost\_weight} \ge 0$).
   - Deterministic tie-breaking: `(status_priority, -score, -marginal_gain, cost, candidate_id)`.
3. **Feature F14: Geofencing & Proximity Indicators:**
   - Unified metric: `AnalysisMetric.PROXIMITY_INDICATORS`.
   - Dedicated helper: `compute_proximity_indicators(snapshot, request)`.
   - **Topological Relations & Uncertainty Propagation:**
     - Zero uncertainty on boundary: point on boundary perimeter with $u = 0$ remains `BOUNDARY`.
     - Positive uncertainty crossing boundary: uncertainty radius $u \ge \text{boundary\_distance}$ produces `INDETERMINATE`.
     - Uncertainty crossing proximity threshold: when possible distance range $[\max(0, d-u), d+u]$ straddles threshold, `threshold_status = "uncertain"`.
     - Polygon holes (interior rings): points inside donut holes are strictly `OUTSIDE` the region, with distance measured to the hole boundary.
     - Uncertainty status: tracks whether uncertainty was `"assessed"` or `"unassessed"`.
   - Descriptive labeling: Explicitly labels camera sites as physical mounting proximity indicators, never animal crossings.
4. **Feature F16: Wildlife-Infrastructure Scenarios:**
   - Unified metric: `AnalysisMetric.INFRASTRUCTURE_SCENARIO`.
   - Dedicated helper: `evaluate_infrastructure_scenario(snapshot, request)`.
   - Compares baseline camera coverage with hypothetical scenario features in an isolated, non-mutating manner.
   - Computes before/after covered areas, coverage fractions, absolute delta ($m^2$), and relative change.
   - Output flagged as `SpatialSourceType.HYPOTHETICAL` with non-causal caveats.

### 6.4 Team Handoff Notes for Phase 6
- **Harsh (Clustering & Observation Intelligence):** When providing modeled or estimated animal positions, populate `TargetLocation` with `position_type = PositionType.ESTIMATED_ANIMAL_POSITION` and explicit `uncertainty_radius_meters`. Never assign camera coordinates as exact animal locations.
- **Santosh (Backend, GIS & Storage):**
  - Use GeoJSON coordinate order `[longitude, latitude]` for all spatial zones, study boundaries, and candidate sites in `Snapshot.spatial_context`.
  - Store exclusion zones with `zone_type = "exclusion_zone"` or `"inaccessible"`.
  - Ensure all coordinates are finite numbers within WGS84 bounds.
- **Laasya (Frontend & Map Visualizations):**
  - Use `compute_monitoring_blind_spots()` to render unmonitored gap polygons on the map.
  - Display the mandatory non-additivity warning on candidate placement queues:
    *"Candidate ranks reflect single-site marginal coverage gain over baseline. Marginal gains are NOT additive."*
  - For camera proximity cards, display the device placement indicator:
    *"Reflects physical device placement; not an animal geofence crossing."*

---

## 7. Runnable Verification Commands

```powershell
# 1. Run complete test suite (277 tests: 276 passed, 1 skipped)
python -m pytest tests/ -v -rs

# 2. Run Phase 6 spatial test suite specifically (30 tests)
python -m pytest tests/test_phase6_spatial.py -v

# 3. Run Phase 5 anomaly indicators test suite (27 tests)
python -m pytest tests/test_phase5_anomalies.py -v

# 4. Run Phase 4 association test suite (24 tests)
python -m pytest tests/test_phase4_associations.py -v

# 5. Run Caltech real dataset integration test
python -m pytest tests/test_phase2_analytics.py -k real_dataset_integration -v -s -rs

# 6. Regenerate all 18 JSON Schemas in schemas/
python -m wildscope_analytics.schema_generator

# 5. Run Caltech real dataset integration test
python -m pytest tests/test_phase2_analytics.py -k real_dataset_integration -v -s -rs

# 6. Regenerate all 18 JSON Schemas in schemas/
python -m wildscope_analytics.schema_generator

# 7. Verify unified analyze() with MONITORING_BLIND_SPOTS in interactive Python
python -c "
from pathlib import Path
from wildscope_analytics import Snapshot, load_and_validate_snapshot, analyze, AnalysisRequest, AnalysisMetric
snap, _ = load_and_validate_snapshot(Path('examples/valid_snapshot.json'))
study_area = {
    'type': 'Polygon',
    'coordinates': [[[-118.0, 34.0], [-118.0, 34.02], [-117.98, 34.02], [-117.98, 34.0], [-118.0, 34.0]]]
}
req = AnalysisRequest(
    metric=AnalysisMetric.MONITORING_BLIND_SPOTS,
    parameters={'study_area_polygon': study_area}
)
resp = analyze(snap, req)
print('Unified Blind Spots Status:', resp.status)
if resp.result:
    print('Study Area (m^2):', resp.result.study_area_sq_meters)
    print('Coverage Fraction:', resp.result.coverage_fraction)
"
```

---

## 8. Complete Artifact & Schema Inventory

### Schemas Generated (`schemas/`, 18 total):
- `snapshot.schema.json` (Schema v1.3.0)
- `analysis_request.schema.json`
- `cross_camera_association_request.schema.json`
- `review_ranking_request.schema.json`
- `activity_anomaly_request.schema.json`
- `activity_anomalies_result.schema.json`
- `analysis_response.schema.json`
- `cross_camera_associations_result.schema.json`
- `dataset_reference_annotation.schema.json`
- `review_ranking_result.schema.json`
- `blind_spot_analysis_request.schema.json`
- `blind_spot_result.schema.json`
- `candidate_placement_request.schema.json`
- `candidate_placement_result.schema.json`
- `proximity_analysis_request.schema.json`
- `proximity_result.schema.json`
- `infrastructure_scenario_request.schema.json`
- `infrastructure_scenario_result.schema.json`

### Code Modules:
- `wildscope_analytics/contracts/`: Data contracts, Pydantic models, spatial entity contracts, request/response models.
- `wildscope_analytics/spatial.py`: Geospatial geometry engine, LAEA projection, blind spots (F08), candidate placement (F09), geofencing (F14), infrastructure scenarios (F16).
- `wildscope_analytics/analytics.py`: Unified `analyze()` dispatcher, dedicated helper entry points, 13 activity & spatial metrics.
- `wildscope_analytics/anomalies.py`: Activity anomaly detection engine (Feature F12).
- `wildscope_analytics/ranking.py`: Conclusion-sensitive review ranking engine (Feature F18).
- `wildscope_analytics/associations.py`: Cross-camera observation correlation engine (Feature F06).
- `wildscope_analytics/caltech_adapter.py`: Ground-truth dataset importer.
- `wildscope_analytics/validation.py`: Snapshot referential integrity and schema validator.
