# WILDSCOPE — Inference Component Progress Log

**Repository:** HFT26-TEAM-8 (`harsh` branch)  
**Team:** ByteStrom  
**Last updated:** 2026-10-31 (Milestone 5)

---

## Milestone 1 — Repository Inspection ✅

- Repository was a blank starter (only `README.md` tracked).
- Branch `harsh` created.
- Python 3.12.10, NVIDIA RTX 4050 Laptop GPU (6 GB VRAM), CUDA 12.8.
- Driver 592.82.

---

## Milestone 2 — Environment Setup ✅

### Packages installed

| Package | Version |
|:--|:--|
| Python | 3.12.10 |
| torch | 2.11.0+cu128 |
| torchvision | 0.26.0+cu128 |
| speciesnet | 5.0.5 |
| yolov5 | 7.0.11 |
| numpy | 2.5.4 |
| pillow | 13.0.0 |
| pytest | 8.3.5 |

### Verification

- `torch.cuda.is_available()` → `True`
- GPU: NVIDIA GeForce RTX 4050 Laptop GPU
- VRAM: 6 140 MB total
- SpeciesNet import: successful
- `.gitignore` created (excludes `.venv/`, `data/`, `*.pt`, `*.pth`, `desktop.ini`)

---

## Milestone 2b — First Genuine Inference Test ✅

### Dataset

Three images downloaded from Caltech Camera Traps (LILA, CDLA-Permissive-1.0):

| Label | File | GT species | GT bbox count |
|:--|:--|:--|:--|
| Image A | `5998cfa4-…jpg` | opossum | 1 |
| Image B | `59610788-…jpg` | bird | 9 |
| Image C | `5971fa92-…jpg` | empty | 0 |

All images: 2048 × 1494 px, JPEG RGB.

### Results

| Image | Model dets | Top-1 species | Correct? |
|:--|:--|:--|:--|
| A — opossum | 1 @ conf=0.785 | *Didelphis virginiana* (99.6%) | ✅ |
| B — bird x9 | 13 detected | mostly blank (crops too small) | ⚠ over-detected |
| C — empty | 1 @ conf=0.813 | *Sylvilagus floridanus* (54.2%) | ❓ annotation ambiguous |

### Hardware

- Both detector and classifier confirmed on `cuda` (RTX 4050)
- Peak GPU: 1 023 MB allocated, 1 100 MB reserved (of 6 140 MB)
- Total wall time: ~4.7 s (including 1.8 s model load from cache)

---

## Milestone 2c — Investigation ✅

### Image B findings

- MegaDetector threshold is **0.01** — very permissive. 4 extra detections (#9–#12) at conf < 0.10 are background false positives.
- Det #4 and Det #12 are **probable duplicates** (IoU=0.421) of the same left-edge GT bird (GT#8). Standard NMS at IoU >= 0.4 would suppress #12.
- Most birds yield classifier output "blank" because crops are 37–132 px wide — too small for species-level identification. Expected behaviour.

### Image C findings

- CCT annotation conflict resolved: **both** files assign category_id=30 ("empty"). No conflict between annotation files.
- The CCT bbox file contains 186 "empty"-category bounding boxes out of 65 112 — a known anomaly where annotators drew a box but labelled the image non-countable.
- The model and the CCT annotator marked **the same pixel region within 2 px**.
- Classifier scores clarified: **softmax over all taxonomy classes** — scores at different hierarchy levels must not be summed.
- Visual inspection of 3x magnified crop generated for user review.

### NMS investigation (critical for Milestone 3)

SpeciesNet's `detector.predict()` calls `yolov5_non_max_suppression` internally:
- `conf_thres = 0.01` (class constant `DETECTION_THRESHOLD`)
- `iou_thres = 0.45` (yolov5 default)
- Applied **before** results are returned to callers.
- **Conclusion:** No additional NMS stage should be applied in our pipeline.

---

## Milestone 3 — Inference Abstraction ✅

### Architecture decisions

#### 1. `BaseDetector` abstract class (`src/inference/base_detector.py`)

- Defines `detect()` and `detect_batch()` public API.
- Returns `ImageDetectionResult` containing a list of `Detection` objects.
- `Detection` holds `detector_conf` and `SpeciesClassification` separately — never combined.
- `SpeciesClassification` stores `top_labels` / `top_scores` from softmax; hierarchical labels preserved verbatim.
- `is_blank` and `is_unknown` properties for explicit blank/unknown handling.
- `validate_bbox()` on `Detection` for coordinate sanity checking.
- `filter_by_conf()` on `ImageDetectionResult` returns a **new** result without mutating the original.
- `DetectionStatus` enum: `OK`, `LOAD_FAILURE`, `INFERENCE_ERROR`, `NOT_RUN`.

#### 2. `SpeciesNetAnimalDetector` (`src/inference/speciesnet_detector.py`)

- Concrete `BaseDetector` backed by SpeciesNet 5.0.5.
- Lazy imports — SpeciesNet does not load at module import time.
- NMS: SpeciesNet applies NMS internally. This class applies **none**.
- Classification failure: logged, detection still returned with `clf.attempted=True` and empty lists.
- `min_conf` filtering: applied post-inference as a simple list filter, not an NMS pass.

#### 3. Backward compatibility

- `src/inference/speciesnet_infer.py` retained as-is for the 3-image test runner.
- New architecture lives in `speciesnet_detector.py`. Future migration at user discretion.

#### 4. No double NMS

Confirmed from source (`speciesnet/detector.py` lines 188–191):
```python
results = yolov5_non_max_suppression(
    prediction=results,
    conf_thres=SpeciesNetDetector.DETECTION_THRESHOLD,  # 0.01
)
```
Our code never calls NMS. `filter_by_conf()` is a confidence threshold, not a duplicate suppressor.

---

## Test Results (Milestone 3)

```
pytest tests/inference/test_speciesnet_infer.py -v
platform win32 -- Python 3.12.10, pytest-8.3.5
collected 47 items

47 passed in 4.87 s
```

All 47 unit tests pass. No model weights loaded. No network access required.

### Test coverage by scenario

| Scenario | Tests |
|:--|:--|
| Single animal detection | 4 |
| Multiple detections | 3 |
| No detections | 2 |
| Unknown / blank species | 7 |
| Classification failure after detection | 2 |
| Invalid image input | 3 |
| Confidence filtering | 6 |
| Bounding-box validation | 7 |
| Device selection | 4 |
| Hierarchical taxonomy preserved | 3 |
| detect() wrapper delegation | 2 |
| succeeded / error_message | 4 |

---

## Milestone 3 — Bug Corrections ✅

Three correctness bugs identified in the Milestone 3 code audit were fixed.
No new features were added.

### C1 — `is_blank` exact segment match

**File:** `src/inference/base_detector.py` → `SpeciesClassification.is_blank`

**Problem:** Original implementation used substring matching (`"blank" in label`)
which produced false positives for labels such as `"animal;blanket"` or
`"animal;black-blank"`.

**Fix:** Changed to an exact, case-insensitive comparison of the final
semicolon-separated taxonomy segment:
```python
return lbl.split(";")[-1].strip().lower() == "blank"
```

**Verified behaviour:**
- `"blank"` → True
- `"BLANK"` → True
- `"animal;blank"` → True
- `"animal;blanket"` → False
- `"animal;black-blank"` → False
- `"animal;unknown"` → False

### C2 — `filter_by_conf()` deep copy

**File:** `src/inference/base_detector.py` → `ImageDetectionResult.filter_by_conf()`

**Problem:** The filtered result shared the original `Detection` and nested
`SpeciesClassification` objects.  Mutating a filtered detection also mutated
the original.

**Fix:** Each retained detection is now cloned with `copy.deepcopy(d)` before
being added to the filtered result.  The original result is never modified.

### C3 — `Detection.bbox_norm` defensive copy

**File:** `src/inference/base_detector.py` → `Detection.__post_init__()`

**Problem:** The `bbox_norm` list passed by the caller was stored by reference.
Mutating the caller's list silently changed the stored coordinates.

**Fix:** `__post_init__` immediately replaces the reference with a new list:
```python
self.bbox_norm = list(self.bbox_norm)
```

### C4 — `requirements.txt` BOM and typo

**File:** `requirements.txt`

**Problem:** The file was written with a UTF-16 BOM and the first package name
was truncated to `bsl-py` (should be `absl-py`).

**Fix:** File rewritten with `UTF8Encoding($false)` (no BOM) and `absl-py`
restored as the correct package name.

---

## Milestone 4A — Inference Reliability ✅

### R1 — Bounding-box validity

**File:** `src/inference/base_detector.py`

**Changes:**

1. **`validate_bbox()` enhanced** — added `try/except (TypeError, ValueError)`
   wrapper around the entire body so no malformed input (wrong list length, NaN,
   ±infinity, negative coordinates, zero/negative dimensions, out-of-range
   values, non-numeric element types such as `str` or `None`) ever raises an
   exception.  The method now always returns a bool and never propagates.

2. **`bbox_valid` converted from stored field to `@property`** — previously a
   `bool` field set once in `__post_init__`, which meant post-construction
   mutations to `bbox_norm` left `bbox_valid` stale.  Now a live property that
   calls `validate_bbox()` on every access, always reflecting the current state
   of `bbox_norm`.

3. **`bbox_pixels` raises `ValueError` when `bbox_valid` is False** — the raw
   (possibly invalid) coordinates remain accessible via `bbox_norm` for
   debugging.

4. **`SpeciesNetAnimalDetector` logs a warning for invalid bboxes** — after
   constructing each `Detection`, the detector checks `if not det.bbox_valid`
   and logs a `WARNING`.  The detection is kept and its species classification
   is preserved; only the pixel-coordinate accessor is blocked.

### R2 — Lazy `__init__.py` import

**File:** `src/inference/__init__.py`

**Problem:** `SpeciesNetAnimalDetector` was imported at module top level,
causing `torch`, `speciesnet`, and `yolov5` to be loaded on every
`import src.inference`, even in test or CLI contexts that do not use the
detector.  Import time: ~4 500 ms.

**Fix:** Replaced the eager import with a PEP 562 `__getattr__` lazy loader.
`import src.inference` now takes ~73 ms and does not load `torch`.

### R3 — Deferred `torch` imports in `speciesnet_infer.py`

**File:** `src/inference/speciesnet_infer.py`

**Problem:** `import torch` and three `from speciesnet.*` imports sat at module
top level, loading the GPU stack whenever the module was imported.

**Fix:** All four imports moved inside the `run_inference()` function body.
Module-level imports are now stdlib-only.  A misleading comment was also
corrected.

### R4 — `test_cct_3images.py` API migration

**File:** `tests/inference/test_cct_3images.py`

**Problem:** The integration test still used the old `run_inference()` +
`DetectionResult` API, which had been superseded by `SpeciesNetAnimalDetector`
and the new `Detection` / `ImageDetectionResult` API from Milestone 3.

**Fix:** Migrated to `SpeciesNetAnimalDetector.detect_batch()` and the new
field names (`det.detector_label`, `det.detector_conf`, `det.detector_category`,
`det.classification.top_labels/scores`, `det.classification.attempted`,
`result.status.name`, `DetectionStatus.OK`).  Added `det.bbox_valid` guard
before `det.bbox_pixels`.

### Milestone 4A — additional fixes during final audit

Two further bugs were discovered and fixed during the Milestone 4A code review:

**Stale `bbox_valid` stored field (pre-audit):**  
The original R1 implementation stored `bbox_valid` as a `bool` field set in
`__post_init__`.  A regression test showed that mutating `bbox_norm` after
construction left `bbox_valid` True while the coordinates had become invalid.
Fixed by converting `bbox_valid` to a live `@property` (described in R1 above).

**`validate_bbox()` raised `TypeError` on non-numeric elements (pre-audit):**  
Passing a list containing `str`, `None`, or other non-numeric types caused
`math.isfinite()` to raise `TypeError`, which was not caught, so `bbox_valid`
propagated an exception instead of returning `False`.
Fixed by wrapping the entire `validate_bbox()` body in
`try/except (TypeError, ValueError)`.

### Milestone 4A — test suite

49 new tests added (79 → 128 total):

| Test class | Tests | What is covered |
|:--|:--|:--|
| `TestBBoxValidityFlag` | 10 | bbox_valid auto-computed, invalid coords preserved, bbox_pixels raises, classification retained, survives deepcopy and filter_by_conf |
| `TestValidateBBoxEdgeCases` | 22 | Wrong lengths, NaN (all 4 positions), ±infinity, negative x/y, zero/negative w/h, boundary tolerance, valid cases |
| `TestMilestone4ALazyImports` | 3 | subprocess-based; import src.inference does not load torch; SpeciesNetAnimalDetector accessible via __getattr__; import speciesnet_infer does not load torch/speciesnet |
| `TestMilestone4AMigration` | 4 | AST lint; old field names absent; SpeciesNetAnimalDetector present; DetectionStatus used |
| `TestBBoxValidLiveProperty` | 3 | Mutation after construction updates bbox_valid; bbox_pixels raises after mutation; mutation back to valid restores bbox_valid |
| `TestValidateBBoxNeverRaises` | 4 | String element → False not TypeError; None element → False; non-numeric → bbox_valid returns False not raises; non-numeric → bbox_pixels raises ValueError not TypeError |

---

## Milestone 5 — Documentation Hygiene ✅

### M5-D1 — YOLOv5 licence confirmed

**File:** `docs/inference/LICENSING.md` Section 4

Inspected the installed `yolov5-7.0.11.dist-info/METADATA` and `LICENSE` files
on 2026-10-31.  Both declare **GPL-3.0**.  Section 4 updated to record this
evidence while preserving the outstanding provenance questions and the
GPL-3.0 vs AGPL-3.0 conflict with the upstream GitHub repository.

### M5-D2 — Legal disclaimer and qualification

**File:** `docs/inference/LICENSING.md`

Added a "not legal advice" disclaimer banner near the top of the document.
Revised Section 1, 2, 3, and 5 conclusions to describe declared licences and
conditions without providing blanket commercial clearance.  The CCT section in
particular no longer states that "CCT data usage raises no licensing concerns
for commercial work"; instead it describes the declared CDLA-Permissive-1.0
terms and recommends verifying directly with LILA Science for specific use cases.

### M5-D3 — Python version pin

**File:** `.python-version` (new)

Single-line file containing `3.12`.  Read by `pyenv`, `mise`, and compatible
version managers.  No `pyproject.toml` or `setup.cfg` introduced.

### M5-D4 — PROGRESS.md updated (this file)

Added Milestone 3 bug corrections (C1–C4), Milestone 4A (R1–R4 and
additional audit fixes), and this Milestone 5 section.

---

## Known Limitations

| Limitation | Detail |
|:--|:--|
| Small bird crops produce blank | Crops narrower than ~100 px lack sufficient visual detail for species ID |
| MegaDetector conf_thres=0.01 | Very permissive; use `filter_by_conf(0.1)` for downstream consumers |
| Duplicate detections at frame edge | IoU=0.45 NMS may not suppress all edge duplicates |
| Image C annotation ambiguity | 186 empty-category bboxes in CCT; not standard; visual review needed per image |
| No batch GPU utilisation | Inference is sequential per image; throughput not optimised |
| YOLOv5 licence | GPL-3.0 declared in installed dist-info; conflicts with upstream AGPL-3.0; legal review required before distribution |

---

## Licensing Status

See `docs/inference/LICENSING.md` for full detail.

`yolov5==7.0.11` (PyPI dist-info) declares **GPL-3.0**.  This conflicts with
the upstream Ultralytics repository which carries AGPL-3.0.  The current
hackathon-only use does not trigger copyleft obligations, but legal review is
required before any distribution or deployment.

---

## Files Created / Modified — Milestone 3

| File | Status |
|:--|:--|
| `src/inference/base_detector.py` | New |
| `src/inference/speciesnet_detector.py` | New |
| `src/inference/__init__.py` | Updated |
| `tests/inference/test_speciesnet_infer.py` | New |
| `docs/inference/LICENSING.md` | New |
| `docs/inference/requirements-inference.txt` | New |
| `requirements.txt` | Regenerated (full pip freeze) |
| `src/inference/speciesnet_infer.py` | Unchanged |
| `tests/inference/test_cct_3images.py` | Unchanged |

## Files Modified — Milestone 3 Bug Corrections

| File | Change |
|:--|:--|
| `src/inference/base_detector.py` | C1, C2, C3 fixes |
| `requirements.txt` | C4 BOM + absl-py typo fix |

## Files Modified — Milestone 4A

| File | Change |
|:--|:--|
| `src/inference/base_detector.py` | R1: validate_bbox(), bbox_valid @property, bbox_pixels guard |
| `src/inference/speciesnet_detector.py` | R1: bbox_valid warning on invalid detections |
| `src/inference/__init__.py` | R2: PEP 562 lazy loader |
| `src/inference/speciesnet_infer.py` | R3: deferred torch/speciesnet imports |
| `tests/inference/test_cct_3images.py` | R4: migrated to new Detection API |
| `tests/inference/test_speciesnet_infer.py` | 49 new tests (79 → 128 total) |

## Files Modified — Milestone 5

| File | Change |
|:--|:--|
| `docs/inference/LICENSING.md` | M5-D1: YOLOv5 licence evidence; M5-D2: disclaimer + qualified conclusions |
| `.python-version` | M5-D3: new file, contains `3.12` |
| `docs/inference/PROGRESS.md` | M5-D4: this update |


## Milestone 6 — Evaluation Metrics Calculation ✅

### Evaluation dataset

100 images sampled from Caltech Camera Traps (CCT) validation split.
Seed: 42. Stratified sampling with priority S2 > S5 > S4 > S1 > S3.
Manifest: `data/eval_manifest.json` (SHA-256: `ad8d7bc792cd6631e9a3dff675fd4a76b3022a1fc0ca142692b4a1ef15c3fdea`).

- 75 animal images (93 GT bounding boxes across 8 CCT categories)
- 25 empty images (no animal GT, excluding category 30)
- All images downloaded and JPEG-verified (35.8 MB total)

### Inference

- Detector: `SpeciesNetAnimalDetector` (SpeciesNet v4.0.3a / MegaDetector V5)
- Device: NVIDIA RTX 4050 Laptop GPU, CUDA 12.8
- 100/100 images processed, 0 failures, 174 total detections
- Average: ~0.46 s/image (batch size 1, sequential)

### Image-level results (Eval A)

| T | P | R | F1 | FPR | TP | FP | FN | TN |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.813 | 0.987 | 0.892 | 0.680 | 74 | 17 | 1 | 8 |
| 0.10 | 0.913 | 0.973 | 0.942 | 0.280 | 73 | 7 | 2 | 18 |
| **0.20** | **0.948** | **0.973** | **0.961** | **0.160** | **73** | **4** | **2** | **21** |
| 0.50 | 0.973 | 0.960 | 0.966 | 0.080 | 72 | 2 | 3 | 23 |

### Instance-level results (Eval B, Hungarian matching, IoU ≥ 0.5)

| T | P | R | F1 | TP | FP | FN |
|---:|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.529 | 0.978 | 0.687 | 91 | 81 | 2 |
| 0.10 | 0.800 | 0.946 | 0.867 | 88 | 22 | 5 |
| **0.20** | **0.898** | **0.946** | **0.921** | **88** | **10** | **5** |
| 0.50 | 0.946 | 0.935 | 0.941 | 87 | 5 | 6 |

### Classification results (at T = 0.01 matched TPs)

- Species-tier (opossum, raccoon, bobcat, skunk, coyote): 54/54 = 1.000
- Genus-tier (deer, rabbit, fox): 11/17 = 0.647
  - Deer: 11/11 correct
  - Rabbit: 0/5 (family-level output only — genus field empty)
  - Fox: 0/1 (family-level output only — genus field empty)
- Zero species-tier misidentifications

### Threshold recommendation

T = 0.20 is a recall-oriented operating point; T = 0.50 is precision-oriented.
Neither is universally optimal. See `EVALUATION_REPORT.md` for analysis.

### Audit

9-point independent audit completed (`EVALUATION_AUDIT.md`). All metrics verified.
S5 definition corrected from < 3 % to < 5 % of image area.

### Scope limitation

> Species accuracy applies only to 5 species-tier + 3 genus-tier CCT categories
> from the Caltech val split. Results must NOT be described as general wildlife
> accuracy. Species and genus accuracy are always reported separately and never
> combined.

### Data files (all gitignored)

| File | Contents |
|:--|:--|
| `data/eval_manifest.json` | 100 image records, strata, GT metadata |
| `data/cct_samples/eval/` | 100 JPEG images (35.8 MB) |
| `data/evaluation_results/raw_predictions.json` | 174 detections, per-detection detail |
| `data/evaluation_results/metrics_summary.json` | Metrics at 4 thresholds |
| `data/evaluation_results/metrics_detail.json` | Per-image detail |
| `data/evaluation_results/audit_detail.json` | Audit supporting data |

---

## Milestone 7A — Targeted Error Analysis ✅

Investigation-only. No model code, predictions, manifest, or metrics altered.

### Key findings

| Error Category | Count (T = 0.20) |
|:--|--:|
| Detector FP on empty images | 4 |
| Detector FN (missed images) | 2 |
| Instance-level FP — localization | 2 |
| Instance-level FP — localization overlap | 3 |
| Instance-level FP — annotation candidate | 4 |
| Classification blank on matched TP | 3 |
| Classification wrong | 0 |

- **75 blank classifications** (43.1 % of 174 detections): 5 matched GT boxes (4 birds, 1 rabbit); 70 unmatched.
- **Annotation omission candidates** (not confirmed): `59e1028c` (primary), `58af7554` (secondary).
- **Rabbit/fox genus fallback:** SpeciesNet returns family-level labels with empty genus field. Genus-level score aggregation investigated but found not defensible.
- **Night/small-animal confound:** All S1-primary images carry both S4 and S5 tags; cannot isolate pure night or pure small-subject effect.
- **S4/S5 overlap:** 38/47 S4-tagged images also carry S5 (81 %); 38/58 S5-tagged images also carry S4 (66 %).
- **21 visual inspection images** generated in `data/evaluation_results/error_analysis/vis/` (gitignored).

### Reconciliation

6-point reconciliation completed. Key corrections:
- Task 4: third matched blank at T = 0.20 is `595adc96` (conf 0.646), not `58d15e51`.
- Task 3: 28 of 39 unmatched detections in multi-det images are blank, not ~65.
- Stratum assignment: `primary_stratum` = selection pool; `all_stratum_tags` = eligibility. No contradiction.
- `localization_miss: 3` counts non-FN images only; 5 total missed GT boxes at T = 0.20.

### Documentation

| File | Contents |
|:--|:--|
| `docs/inference/ERROR_ANALYSIS.md` | Main error analysis (9 tasks) |
| `docs/inference/ERROR_ANALYSIS_RECONCILIATION.md` | 6-point reconciliation |

---

## Milestone 7B — Post-Processing NMS Experiment ✅

Post-hoc NMS applied to existing raw predictions. Model not rerun. No source files changed.

### Experiment

- Greedy confidence-ranked NMS at IoU thresholds 0.30–0.70.
- Evaluated at T = 0.01, 0.10, 0.20, 0.50.
- 13 detections suppressed at NMS IoU = 0.30; 0 genuine-risk suppressions (conf ≥ 0.10 AND non-blank).

### Results

| Threshold | NMS effect |
|:--|:--|
| T = 0.20 | **No change** — all metrics identical to baseline |
| T = 0.50 | **No change** — all metrics identical to baseline |
| T = 0.10 | inst FP −1; inst F1 +0.004 (marginal, does not establish NMS preferable) |
| T = 0.01 | inst F1 +0.028 but **1 genuine TP loss** (`58bd1bec` rabbit, conf 0.017) |

### Decision

**Do not add post-processing NMS to the production inference pipeline.**

Rationale:
1. Zero improvement at recommended operating thresholds (T = 0.20 and T = 0.50).
2. Marginal improvement at T = 0.10 (+0.004 inst F1) is within sampling variability.
3. NMS causes a genuine TP loss at T = 0.01, demonstrating the suppression risk.
4. Double-suppression risk — SpeciesNet already applies internal NMS.
5. Root cause (low-conf ghost dets) is handled by raising threshold to T ≥ 0.10.

### Documentation

`docs/inference/MILESTONE_7B_RESULTS.md` — full experiment report.

---

## Milestone 8 — Integration Readiness ✅

Pre-integration checklist completed. No production code changed.

### Checklist summary

- Input/output contracts documented (all field types, semantics, constraints)
- CPU/GPU behaviour documented (lazy imports, device auto-selection, VRAM usage)
- Error handling documented (no silent skips; classification failure preserves detection)
- Dependencies and setup instructions (PyTorch CUDA 12.8, SpeciesNet 5.0.5, Kaggle auth)
- YOLOv5 GPL-3.0 / AGPL-3.0 licensing caution documented
- 128 unit tests across 22 test classes — all passing, fully mocked, < 7 s
- 7 known limitations documented (L1–L7)
- Recommended thresholds: T = 0.20 (recall-oriented), T = 0.50 (precision-oriented)

### Documentation

`docs/inference/MILESTONE_8_READINESS.md` — integration readiness checklist.

---

## Files Created — Milestones 6–8

| File | Status |
|:--|:--|
| `docs/inference/EVALUATION_REPORT.md` | New — evaluation results and analysis |
| `docs/inference/EVALUATION_AUDIT.md` | New — 9-point metrics audit |
| `docs/inference/ERROR_ANALYSIS.md` | New — targeted error analysis (9 tasks) |
| `docs/inference/ERROR_ANALYSIS_RECONCILIATION.md` | New — 6-point reconciliation |
| `docs/inference/MILESTONE_7B_RESULTS.md` | New — NMS experiment results |
| `docs/inference/MILESTONE_8_READINESS.md` | New — integration readiness checklist |
| `docs/inference/PROGRESS.md` | Updated — this update (Milestones 6–8) |
