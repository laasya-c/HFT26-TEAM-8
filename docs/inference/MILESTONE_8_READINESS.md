# Milestone 8 — Integration Readiness Checklist

**Project:** WILDSCOPE — Wildlife Camera-Trap Inference System  
**Team:** ByteStrom (HFT26-TEAM-8) · Branch: `harsh`  
**Date:** 2026-10-31  
**Status:** Investigation only — no production code changed, no files staged

> [!NOTE]
> This checklist documents the current state of the inference component as of Milestones 1–7B. It is not a build or test run record — it is a pre-integration review. All test results recorded here were obtained by actually running the test suite (see §7).

---

## 1. Input Contract

| Parameter | Type | Required | Constraints | Where defined |
|:---|:---|:---|:---|:---|
| `image_paths` | `list[str \| Path]` | Yes | Absolute paths to JPEG/PNG images; must exist on disk | `speciesnet_detector.py` `detect_batch()` |
| `min_conf` | `float` | No (default `0.0`) | Range [0.0, 1.0]; applied as a post-inference confidence floor, **not** an NMS pass | `base_detector.py` `BaseDetector.detect_batch()` |
| `model_name` | `str` | No (default `DEFAULT_MODEL_NAME`) | `kaggle:google/speciesnet/pyTorch/v4.0.3a/1` or HuggingFace equivalent | `speciesnet_detector.py` |
| `classify_device` | `str \| None` | No (default `None` = auto) | `None`, `"cpu"`, `"cuda"`, `"mps"` | `speciesnet_detector.py` |

**Image loading:** Uses `speciesnet.utils.load_rgb_image()`. Returns `None` on read failure; the caller receives `DetectionStatus.LOAD_FAILURE`.  
**Supported formats:** Any PIL-readable format (JPEG recommended; CCT evaluation used JPEG exclusively).  
**Image dimensions:** Preserved in `ImageDetectionResult.image_w` and `.image_h`.

> [!IMPORTANT]
> Paths must be **absolute**. Relative paths are not tested and may fail silently inside SpeciesNet's internal preprocessing.

---

## 2. Output Contract

### `ImageDetectionResult` (one per input image)

| Field | Type | Semantics |
|:---|:---|:---|
| `filepath` | `str` | Input path, reproduced verbatim |
| `status` | `DetectionStatus` | `OK` \| `LOAD_FAILURE` \| `INFERENCE_ERROR` \| `NOT_RUN` |
| `succeeded` | `bool` property | `True` iff `status == OK`; does NOT require `detections` to be non-empty |
| `image_w`, `image_h` | `int \| None` | Pixel dimensions; `None` on load failure |
| `detections` | `list[Detection]` | Empty list = model ran, found nothing above `conf_thres=0.01` |
| `detect_device` | `str \| None` | e.g. `"cuda"`, `"cpu"` — actual device used |
| `classify_device` | `str \| None` | May be `None` if no animal detections were present |
| `load_time_s`, `detect_time_s`, `classify_time_s`, `total_time_s` | `float` | Wall-clock seconds |
| `error_message` | `str \| None` | Non-`None` only on failure |
| `animal_count` | `int` property | Count of `Detection` objects with `detector_label == "animal"` |

### `Detection` (one per bounding box)

| Field | Type | Semantics |
|:---|:---|:---|
| `detector_conf` | `float` | Raw MegaDetector score — **NOT a calibrated probability** |
| `detector_label` | `str` | `"animal"` \| `"vehicle"` \| `"person"` |
| `detector_category` | `str` | Raw category string (`"1"` = animal) |
| `bbox_norm` | `list[float]` | `[x_min, y_min, width, height]` normalised [0, 1] — **defensive copy** |
| `bbox_valid` | `bool` property | Live; calls `validate_bbox()` on every access |
| `bbox_pixels` | `tuple[int,int,int,int]` property | `(x,y,w,h)` in pixels; raises `ValueError` if `bbox_valid` is `False` |
| `classification` | `SpeciesClassification` | Species result; may be not-attempted for non-animal labels |
| `is_animal` | `bool` property | `detector_label.lower() == "animal"` |

### `SpeciesClassification`

| Field | Semantics |
|:---|:---|
| `top_labels` | `list[str]` — up to 5, semicolon-delimited 7-segment SpeciesNet labels; **never sum scores across labels** |
| `top_scores` | `list[float]` — softmax values; sum of top-5 may be < 1.0 (remaining classes hold the rest) |
| `attempted` | `bool` — `False` if classification was skipped (e.g. non-animal detection) |
| `is_blank` | `bool` property — `True` iff final `;`-segment of `top_label` == `"blank"` (exact, case-insensitive) |
| `is_unknown` | `bool` property — `True` if `attempted=False` OR `top_labels` is empty |
| `top_label` | `str \| None` — highest-scoring label, or `None` |
| `top_score` | `float \| None` — highest score, or `None` |

**SpeciesNet label format:** `uuid;class;order;family;genus;species;common_name` (7 segments).  
- Genus segment (index 4) is **empty** for family-level outputs (rabbit, fox in CCT sample).  
- Parse with `label.split(';')[5]` for species, `[4]` for genus, `[3]` for family.

> [!WARNING]
> `detector_conf` and `top_score` are entirely independent values from two separate model stages. Never average, combine, or compare them as if they are on the same scale.

---

## 3. CPU / GPU Behaviour

| Scenario | Behaviour | Notes |
|:---|:---|:---|
| CUDA available | Detector on `cuda`; classifier on `cuda` (default) | Verified on RTX 4050 Laptop, 6 GB VRAM, CUDA 12.8 |
| `classify_device="cpu"` | Detector stays on CUDA; classifier on CPU | Supported; use for VRAM-limited environments |
| No CUDA | Both stages fall back to CPU | SpeciesNet handles device selection internally |
| `classify_device=None` (default) | SpeciesNet auto-selects: CUDA > MPS > CPU | Reported in `result.classify_device` |
| **Device reporting** | `result.detect_device` and `result.classify_device` always record actual device | `None` only if image failed to load |

**VRAM usage (observed):** ~1 023 MB allocated, ~1 100 MB reserved on RTX 4050 during 100-image evaluation.  
**Throughput (observed):** ~0.46 s/image on RTX 4050 (sequential, batch size 1). No batching optimisation is implemented.

> [!TIP]
> `SpeciesNetAnimalDetector` uses **lazy imports** — importing `src.inference` does not load `torch` or SpeciesNet. Model weights are loaded only when the first `SpeciesNetAnimalDetector()` is instantiated. Create **one instance** and reuse it for all images; do not re-instantiate per image.

---

## 4. Error Handling

| Error condition | Status set | `error_message` | Detection list |
|:---|:---|:---|:---|
| Image file does not exist | `LOAD_FAILURE` | `"load_rgb_image returned None"` | `[]` |
| Image corrupt / unreadable | `LOAD_FAILURE` | `"load_rgb_image returned None"` | `[]` |
| Detector internal failure | `INFERENCE_ERROR` | Detector failure string | `[]` |
| Model runtime exception | `INFERENCE_ERROR` | Exception `str()` | `[]` |
| Classification failure (per detection) | `OK` (**not** failure) | `None` on result | Detection kept; `clf.attempted=True`, `clf.top_labels=[]` |
| Invalid bbox returned by model | `OK` (warning logged) | `None` | Detection kept; `bbox_valid=False`; `bbox_pixels` raises `ValueError` |

**Silent-skip policy:** **No detection is silently discarded.** Classification failure and invalid bboxes are logged at WARNING level and the detection is preserved. The caller must check `result.succeeded`, `det.bbox_valid`, and `clf.is_unknown` before consuming values.

**Logging:** Uses Python's standard `logging` module under `src.inference.*`. Call `logging.basicConfig(level=logging.INFO)` to see model-loading and per-image timing output.

---

## 5. Dependencies and Setup

### Required packages (from `requirements-inference.txt`)

```
torch>=2.0.0           # GPU-accelerated tensor ops; install CUDA variant separately
torchvision            # image transforms used by SpeciesNet
speciesnet==5.0.5      # detector + classifier package
yolov5==7.0.11         # MegaDetector backbone (GPL-3.0 — see LICENSING.md)
pillow>=10.0           # image I/O
numpy                  # array ops
```

### Install steps

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install PyTorch with CUDA 12.8 (Windows)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128

# 3. Install remaining inference dependencies
pip install -r docs/inference/requirements-inference.txt

# 4. (First run only) Model weights are auto-downloaded from Kaggle
#    Requires: kaggle CLI authenticated OR KAGGLE_USERNAME + KAGGLE_KEY env vars
#    Cache location: ~/.cache/kagglehub/  (~500 MB)
#    No manual download step needed; SpeciesNetAnimalDetector() triggers it.
```

### Licensing note

> [!CAUTION]
> `yolov5==7.0.11` declares **GPL-3.0** in its PyPI dist-info, which conflicts with the upstream Ultralytics repository's AGPL-3.0 licence. Current hackathon-only use does not trigger copyleft obligations, but **legal review is required before any distribution or deployment**. See `docs/inference/LICENSING.md` for full analysis.

---

## 6. Tests Required Before Integration

All tests are fully mocked — no model weights are downloaded, no network access required, runs in < 5 seconds.

### Existing test suite: `tests/inference/test_speciesnet_infer.py`

**128 tests across 22 test classes.** All 128 passed at the time of this document (see §7).

| Test class | Count | Coverage area |
|:---|---:|:---|
| `TestSingleAnimalDetection` | 4 | Field population, confidence/score separation, dimensions, bbox pixels |
| `TestMultipleDetections` | 3 | Order preservation, `animal_count`, `animals()` helper |
| `TestNoDetections` | 2 | `OK` status with empty list, zero-detection via mock |
| `TestUnknownBlankSpecies` | 7 | `is_blank`, `is_unknown`, `top_label`/`top_score` None when empty |
| `TestClassificationFailureKeepsDetection` | 2 | Detection preserved when classification fails |
| `TestInvalidImagePath` | 3 | `LOAD_FAILURE`, `INFERENCE_ERROR`, `succeeded=False` |
| `TestConfidenceFiltering` | 6 | `filter_by_conf()` — removes low, preserves original, exact threshold |
| `TestBBoxValidation` | 7 | Valid/invalid geometry, `bbox_pixels` correctness |
| `TestDeviceSelection` | 4 | Device fields, `repr`, mock `device` property |
| `TestHierarchicalTaxonomy` | 3 | Labels preserved verbatim, scores not summed |
| `TestDetectWrapperDelegates` | 2 | `detect()` calls `detect_batch()` once, returns single result |
| `TestSucceededProperty` | 4 | All four `DetectionStatus` values |
| `TestBugRegressions` (C1–C3) | 10 | `is_blank` exact match, `filter_by_conf` deep copy, `bbox_norm` defensive copy |
| `TestIsBlankExactMatch` | 10 | Full regression battery for C1 |
| `TestFilterByConfDeepCopy` | 5 | Full regression battery for C2 |
| `TestBBoxNormDefensiveCopy` | 3 | Full regression battery for C3 |
| `TestBBoxValidityFlag` | 10 | `bbox_valid` live property, `bbox_pixels` guard, deepcopy/filter survival |
| `TestValidateBBoxEdgeCases` | 22 | All malformed inputs including NaN, ±∞, wrong length, out-of-range |
| `TestMilestone4ALazyImports` | 3 | Subprocess: `import src.inference` does not load torch |
| `TestMilestone4AMigration` | 4 | AST lint: old field names absent, new API present |
| `TestBBoxValidLiveProperty` | 3 | Post-construction mutation updates `bbox_valid` |
| `TestValidateBBoxNeverRaises` | 4 | Non-numeric input never raises; returns `False` |

### Integration test: `tests/inference/test_cct_3images.py`

**Run directly** (not pytest-collected). Requires model weights on disk and GPU. Reports SpeciesNet output on 3 CCT images. Use only for live environment verification.

```powershell
.venv\Scripts\python.exe tests\inference\test_cct_3images.py
```

### Minimum gate before integration

All of the following must pass before merging inference code into any shared module:

- [ ] `pytest tests/inference/test_speciesnet_infer.py` — **128 tests pass**
- [ ] No `torch`, `speciesnet`, or `yolov5` imported at module level in `src/inference/__init__.py` (lazy import test covers this)
- [ ] `result.succeeded` checked before consuming detections
- [ ] `det.bbox_valid` checked before calling `det.bbox_pixels`
- [ ] `clf.is_unknown` or `clf.attempted` checked before consuming `top_labels`/`top_scores`
- [ ] Confidence threshold applied via `filter_by_conf()` or `min_conf` parameter; **not** by adding NMS

---

## 7. Test Execution Record

```
pytest tests/inference/test_speciesnet_infer.py -v --tb=short
platform win32 -- Python 3.12.10, pytest-8.3.5
collected 128 items

128 passed in 6.57 s
```

Run at: 2026-10-31 ~12:16 IST. No failures, no warnings, no model weights loaded.

**Earlier run note:** A prior test invocation piped output through `| tail -20`, which failed because the `tail` command is not available in Windows PowerShell (`CommandNotFoundException`). The shell pipeline failed before Python could execute. The command was rerun without the pipe, confirming 128 tests passed. The run above (without the pipe) is the definitive successful test execution record.

---

## 8. Known Limitations and Blockers

| ID | Limitation | Severity | Mitigation |
|:---|:---|:---|:---|
| L1 | Sequential inference only (batch size 1) | Medium | Accept for hackathon; GPU throughput still acceptable (~0.46 s/image) |
| L2 | YOLOv5 GPL-3.0 / AGPL-3.0 conflict | **High (legal)** | Hackathon use OK; legal review before any distribution |
| L3 | CCT training-data overlap with SpeciesNet unknown | Medium | Results must not be described as an independent generalization estimate |
| L4 | Genus-level classification fails for rabbit and fox (family-level output) | Low (documented) | Report at family tier; genus aggregation not defensible (see 7A reconciliation) |
| L5 | Annotation omission candidates not verified | Low | `59e1028c` and `58af7554` flagged for manual review; metrics treat GT as authoritative |
| L6 | No post-processing NMS | None | Intentional (see MILESTONE_7B_RESULTS.md); raise operational threshold to T = 0.10 instead |
| L7 | Model weights not in Git | By design | `.gitignore` excludes `*.pt`, `*.pth`, `data/`; Kaggle download on first run |

---

## 9. Recommended Operational Thresholds

| Threshold | img F1 | inst F1 | Empty FPR | Recommended use |
|---:|---:|---:|---:|:---|
| 0.10 | 0.942 | 0.867 | 0.280 | Not recommended in isolation |
| **0.20** | **0.961** | **0.921** | **0.160** | **Recall-oriented default (wildlife monitoring)** |
| 0.50 | 0.966 | 0.941 | 0.080 | Precision-oriented (automated alert queues) |

Neither threshold is universally optimal. Select based on deployment context. Both values are call-site parameters, not hardcoded values.

---

## 10. Staged Files (Git Status at Checklist Time)

```
Staged (19):     .gitignore, .python-version,
                 docs/inference/LICENSING.md, docs/inference/PROGRESS.md,
                 docs/inference/requirements-inference.txt,
                 requirements-dev.txt, requirements-lock-cuda.txt, requirements.txt,
                 src/__init__.py, src/inference/__init__.py,
                 src/inference/base_detector.py, src/inference/speciesnet_detector.py,
                 src/inference/speciesnet_infer.py,
                 tests/__init__.py, tests/inference/__init__.py,
                 tests/inference/test_cct_3images.py, tests/inference/test_speciesnet_infer.py,
                 tests/inference/visual_inspection.py, tests/inference/visualize_detections.py

Untracked (6):   docs/inference/ERROR_ANALYSIS.md
                 docs/inference/ERROR_ANALYSIS_RECONCILIATION.md
                 docs/inference/EVALUATION_AUDIT.md
                 docs/inference/EVALUATION_REPORT.md
                 docs/inference/MILESTONE_7B_RESULTS.md
                 docs/inference/MILESTONE_8_READINESS.md  ← this file

Nothing committed. No model code modified.
```

> [!IMPORTANT]
> Do not stage, commit, or push any file without explicit user approval. Show `git status` and `git diff --cached --name-only` before every `git add` or `git commit` call.

---

*End of Milestone 8 readiness checklist. Investigation only — no production changes made.*

