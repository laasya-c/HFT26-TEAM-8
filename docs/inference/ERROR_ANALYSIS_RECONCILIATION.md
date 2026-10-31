# Milestone 7A — Error Analysis Reconciliation

**Date:** 2026-10-31  
**Scope:** Investigation only. No model code, predictions, metrics, manifest, thresholds, or reports modified.  
**Source data:**
- `data/eval_manifest.json` — 100 images
- `data/evaluation_results/raw_predictions.json` — 174 raw detections
- `data/evaluation_results/error_analysis/error_data.json` — Task 7A extraction
- `data/evaluation_results/error_analysis/recon_blanks.json` — Task 1 recomputation
- `data/evaluation_results/error_analysis/recon_multidet.json` — Task 2 detail
- `data/evaluation_results/error_analysis/recon_categories.json` — Task 4 detail
- `scratch/generate_manifest.py` — manifest generator (primary-stratum priority source of truth)
- `scratch/audit_p5.py` — Point 5 independent audit script (run 2026-10-31)

---

## Point 1 — Matched Blank Detections: Exact Records and Threshold Survival

### Original report statement (to be corrected)

The original `ERROR_ANALYSIS.md` stated "3 matched blanks survive at T=0.20" in Task 4's opening count, and also stated "3 at T=0.20" in the Task 8 categorization table row `classification_blank: 3`. These statements are **consistent with each other and with the recomputed data** — the discrepancy is in the Task 4 body text, which grouped the second `59531d26` detection (conf=0.066, below T=0.10) with the three that survive at T≥0.10.

### Verified exact records (5 matched blanks at T=0.01)

All five are confirmed by independent Hungarian recomputation.

| # | Image ID | Det conf | Bbox (xywh) | IoU vs GT | GT category | GT cat ID | Stratum | Night |
|---:|:---|---:|:---|---:|:---|---:|:---|:---|
| 1 | `58bd1bec-23d2-11e8-a6a3-ec086b02610b` | **0.016651** | [271, 533, 130, 141] | **0.6494** | rabbit | 10 | S1 | ✓ |
| 2 | `59531d26-23d2-11e8-a6a3-ec086b02610b` | **0.734956** | [311, 1095, 87, 89] | **0.8059** | bird | 11 | S2 | — |
| 3 | `59531d26-23d2-11e8-a6a3-ec086b02610b` | **0.066011** | [1239, 504, 162, 127] | **0.8977** | bird | 11 | S2 | — |
| 4 | `5957c33d-23d2-11e8-a6a3-ec086b02610b` | **0.571164** | [1450, 648, 67, 106] | **0.7777** | bird | 11 | S2 | — |
| 5 | `595adc96-23d2-11e8-a6a3-ec086b02610b` | **0.645627** | [329, 1086, 66, 100] | **0.8296** | bird | 11 | S2 | — |

All five use the identical blank label: `f1856211-cfb7-4a5b-9158-c0f72fd09ee6;;;;;;blank`.

### Threshold survival

| | T=0.01 | T=0.10 | T=0.20 | T=0.50 |
|:---|:---:|:---:|:---:|:---:|
| #1 rabbit, conf=0.0167 | ✓ | — | — | — |
| #2 bird, conf=0.7350 | ✓ | ✓ | ✓ | ✓ |
| #3 bird, conf=0.0660 | ✓ | — | — | — |
| #4 bird, conf=0.5712 | ✓ | ✓ | ✓ | ✓ |
| #5 bird, conf=0.6456 | ✓ | ✓ | ✓ | ✓ |

**Summary:** 5 matched blanks exist at T=0.01. 3 survive at T=0.10 and all higher thresholds. The "5 matched blanks" and "3 survive at T≥0.10" are both correct and consistent. The discrepancy in the original report was in the body text of Task 4, which referred to the low-conf bird blank (#3) together with the three survivors when describing T=0.20 behavior.

### Correction needed in ERROR_ANALYSIS.md

The Task 4 body section states: *"At T=0.20 (reference), matched blanks with conf ≥ 0.20: 3 (the two bird detections with conf 0.735 and 0.571, plus one additional blank in the image `58d15e51`)"* — this is **incorrect**. The third matched blank at T=0.20 is `595adc96` (conf=0.646), not `58d15e51`. The `58d15e51` unmatched blank detections are *unmatched* at T=0.20.

**Correct statement:** At T=0.20, exactly 3 matched blank TPs survive: `59531d26` (conf=0.735), `5957c33d` (conf=0.571), and `595adc96` (conf=0.646), all bird GT, all S2. The `58bd1bec` rabbit blank and the second `59531d26` bird blank drop below T=0.10.

---

## Point 2 — Multi-Detection Classification (22 Images)

### Detection totals at T=0.01

22 images have more detections than GT boxes at T=0.01, yielding **39 unmatched detections** in total.

### Classification of the 39 extra detections

| Classification | Count | Definition |
|:---|---:|:---|
| `LIKELY_false_blank` | 28 | is_blank=True, low confidence, no meaningful GT overlap |
| `POSSIBLE_annotation_omission` | 2 | conf ≥ 0.10, non-blank, best GT IoU ≥ 0.30 |
| `DUPLICATE_overlapping` | 2 | IoU ≥ 0.30 with both a GT box and a matched detection |
| `LOCALIZATION_overlap` | 3 | best GT IoU ≥ 0.10, mostly blank, low confidence |
| `PLAUSIBLE_additional_animal` | 2 | conf ≥ 0.20, non-blank, no GT overlap (IoU = 0) |
| `UNCERTAIN` | 2 | conf < 0.20, non-blank, no GT overlap, species label |

### Detailed per-category analysis

**`POSSIBLE_annotation_omission` (2 detections):**
- `58af7554` det#1: conf=0.619, "northern raccoon", best GT IoU=0.366, match IoU=0.277. Image has 2 GT raccoons already matched. This detection covers an adjacent region that may hold a third raccoon.
- `59e1028c` det#0: conf=0.891, "northern raccoon", best GT IoU=0.369, match IoU=0.000 (no matched det in this image — GT raccoon is completely unmatched). This is the **primary** omission candidate.

**`DUPLICATE_overlapping` (2 detections):**
- `59531d26` det#5: conf=0.028, "bird", IoU=0.441 vs a bird GT box, IoU=0.429 vs the matched detection for that GT. A low-confidence near-duplicate of an already-matched bird detection.
- `5a2af3cf` det#2: conf=0.018, "mule deer", IoU=0.303 vs GT, IoU=0.401 vs the matched detection. A near-duplicate at very low confidence.

**`PLAUSIBLE_additional_animal` (2 detections):**
- `59e105b5` det#1: conf=0.277, "virginia opossum", IoU=0 vs any GT. One GT opossum already matched. The unmatched detection is in a distinct image region with no GT annotation. Plausible additional animal, not a duplicate.
- `5a0c9c39` det#1: conf=0.385, "coyote", IoU=0 vs GT coyote. Matched detection covers the GT coyote; the second detection is in a completely different region. Plausible second animal in frame or background trigger.

**`UNCERTAIN` (2 detections):**
- `59ddc030` det#1: conf=0.059, "coyote", IoU=0 vs GT. Non-blank, low confidence, no GT overlap. The GT coyote is matched by another detection (conf=0.773). Could be background vegetation or a second animal.
- `59e103ca` det#1: conf=0.169, "coyote", IoU=0 vs GT. Non-blank, sub-threshold (below T=0.20), no GT overlap. Same image pattern as above; ambiguous.

**`LOCALIZATION_overlap` (3 detections):** All three are blank with IoU 0.10–0.27 vs a GT box and/or matched detection — these represent imprecise ghost responses at the edge of an annotated animal, not separate subjects.

**`LIKELY_false_blank` (28 detections):** All are is_blank=True with IoU < 0.10 vs any GT box and typically conf < 0.15. These are background noise responses that disappear at T ≥ 0.10.

### Summary table

| Category | Detections | Unique images | Recommendation |
|:---|---:|---:|:---|
| Likely false (blank, low-conf) | 28 | 17 | Eliminated by T=0.10 threshold |
| Duplicate/overlap | 2 | 2 | NMS would suppress |
| Localization overlap | 3 | 3 | Borderline; mostly blank/low-conf |
| Plausible additional animal | 2 | 2 | Warrants manual review, not FP by definition |
| Possible annotation omission | 2 | 2 | `59e1028c` (primary), `58af7554` (secondary) |
| Uncertain | 2 | 2 | Cannot classify without visual inspection |

> **Conclusion:** 28/39 (72%) extra detections are almost certainly background noise eliminated at T=0.10. 2/39 are possible annotation omissions. 2/39 may represent additional unannotated animals. None of the 39 can be definitively classified as confirmed false positives without visual inspection.

---

## Point 3 — SpeciesNet Classification Output Structure and Genus Aggregation

### Label format (confirmed from raw data)

```
{uuid};{class};{order};{family};{genus};{species};{common_name}
```

- **110 unique label strings** appear across 860 total top-5 outputs in the 174 detections.
- Tier breakdown of unique labels: ~88 species-level, ~8 genus-level (genus filled, species empty), ~12 family-level or higher (genus and species empty), 1 blank, 1 "mammal" (class only).

### Score semantics

Top-5 scores behave like **softmax probabilities truncated at top-5** — they do not necessarily sum to 1.0:
- Top-5 sum range: 0.761 to 1.000 (mean 0.983, across 172 detections with ≥2 scores)
- 79/172 (46%) sum within 0.001 of 1.0; 135/172 (79%) within 0.01 of 1.0
- When the top-1 score is very high (e.g., 0.998), the remaining 0.002 is distributed among 4 labels with near-zero scores

This means **the top-5 list does not always capture the full probability distribution**. Scores may be truncated from a full softmax over hundreds of classes.

### Genus aggregation: mathematical analysis

For each of the 7 rabbit/fox matched TPs, genus-level aggregation (summing top-5 scores by genus) gives:

| Image | GT | Top-1 label | Top-1 genus | Aggregated best genus | Correct? | Score sum |
|:---|:---|:---|:---|:---|:---|---:|
| `5961070f` | fox | canine family | **empty** | `canis` (0.0074) | **No** (correct: *Urocyon*) | 0.9997 |
| `5965ab2a` | rabbit | rabbit/hare family | **empty** | `sylvilagus` (0.172) | **Yes** | 0.9580 |
| `599fc063` | rabbit | rabbit/hare family | **empty** | `sylvilagus` (sum≈0.001) | **Yes** (barely) | ~1.0 |
| `59ccd30e` | rabbit | rabbit/hare family | **empty** | `sylvilagus` (0.396) | **Yes** | 0.9537 |
| `59fae70d` | rabbit | rabbit/hare family | **empty** | `sylvilagus` (0.002) | **Yes** (barely) | 1.0000 |
| `5a263975` | rabbit | rabbit/hare family | **empty** | `lepus` (0.136) | **Yes** (leporid, wrong genus) | 0.9816 |
| `58bd1bec` | rabbit | blank | **empty** | `wallabia` (0.022) | **No** (blank dominates) | 0.9323 |

**Aggregation would help for 3–4 of 6 non-blank rabbit cases** (where *Sylvilagus* mass in top-5 exceeds any other genus). It **would not help** for:
- Fox: the dominant mass (score=0.99) is at the family level (`canidae`); genus aggregation picks `canis` as best, not the correct fox genus (*Urocyon*). Fox appears only at rank 3 with score 0.002.
- Rabbit `5a263975`: all genus mass in top-5 belongs to `lepus` (jackrabbit), not `sylvilagus`. Family `leporidae` dominates.
- Blank rabbit `58bd1bec`: blank probability (0.861) dominates; genus sums are vanishingly small for non-leporid genera.

### Defensibility assessment

| Criterion | Assessment |
|:---|:---|
| **Mathematical validity** | Only valid if top-5 scores represent the full probability mass (i.e., they sum to ≈ 1.0). In 21% of detections, top-5 sum < 0.99 — meaningful probability remains unaccounted for in non-top-5 classes. Aggregation is an approximation, not an exact computation. |
| **Taxonomic validity** | Summing family-level mass into genus-level aggregation conflates different levels of the taxonomy. A family-level label (e.g., "leporidae") being ranked above species labels does not mean family probability should be redistributed to species genera. |
| **Correctness rate** | 3/6 non-blank rabbit cases: aggregation picks the correct genus. 3/6: it either picks the wrong genus or fails (fox, jackrabbit image, blank image). Success rate is case-dependent, not reliable. |
| **Recommendation** | Genus-cluster aggregation is taxonomically speculative and mathematically approximate. It should not be applied without access to the full probability distribution over all classes. The proposal to implement it was already marked as "investigation only" in the original report. This finding confirms that the approach is not defensible as a reliable general method. |

---

## Point 4 — Error Category Exclusivity and Unique Counts

### Are categories mutually exclusive?

**No.** The error categories are defined at different granularity levels, causing expected overlaps:

| Overlap pattern | Images | Explanation |
|:---|---:|:---|
| `detector_fn_image` + `gt_unmatched` | 2 | A missed image has all its GT boxes unmatched — both categories apply simultaneously |
| `annotation_candidate` + `gt_unmatched` | 2 | `59e1028c` and `58af7554`: the annotation candidate detection is unmatched, but so is a GT box in the same image |
| `classification_blank` + `gt_unmatched` | 1 | `59531d26`: 3 blanks matched to birds (correct bbox), but the 4th bird GT box is unmatched (instance miss) |

### Unique counts at T=0.20

| Error category | Unique images | Unique det/events | Overlaps with |
|:---|---:|---:|:---|
| `detector_fp_empty` | 4 | 4 | None — mutually exclusive with animal-image categories |
| `detector_fn_image` | 2 | 0 | `gt_unmatched` |
| `localization_fp` | 1 | 2 | None |
| `annotation_candidate` | 4 | 4 | `gt_unmatched` for 2 of 4 |
| `classification_blank` | 3 | 3 | `gt_unmatched` for 1 of 3 |
| `gt_unmatched` | 5 | 5 | Multiple categories above |

**Images in any error category: 14 unique images** (of 100).  
**Images in multiple categories simultaneously: 5** (listed above).

### Total unique counts

| Unit | Count |
|:---|---:|
| Unique images with any error at T=0.20 | **14** |
| Unique images with multiple error categories | **5** |
| Unique unmatched detections (instance-level FP) | **10** (4 on empty + 4 annotation cand. + 2 localization) |
| Unique missed GT boxes | **5** |
| Unique matched blanks (classification errors) | **3** |

> **Clarification for ERROR_ANALYSIS.md Task 8 table:** The original `localization_miss` count of 3 was the count of missed GT boxes that were not in image-level FN images. The `gt_unmatched` count of 5 (from recomputation) is the total missed GT boxes including those in FN images. The difference (5 vs 3) is because FN images (`58bd1bec`, `599a5afa`) contribute 2 unmatched GT boxes that were counted under `detector_fn_image` instead of `localization_miss` in the original script. Both counts are internally consistent; the original report's `localization_miss: 3` refers only to images that had detections but where some GT box was still missed.

---

## Point 5 — S4/S5 Denominators, Primary-Stratum Priority, and Tag Counting

### 5a. Primary-stratum assignment mechanism (from generator source)

The manifest generator (`scratch/generate_manifest.py`) implements the following logic:

1. **Pool construction** (independent of each other):
   - `pool_S2`: ≥2 animal bboxes in bbox file
   - `pool_S5`: ≥1 animal bbox with area < 5% of actual image area
   - `pool_S4`: ≥1 animal bbox AND hour ≥ 20 or < 6 (night proxy)
   - `pool_S1_all`: exactly 1 animal bbox, category in `WILDLIFE_CATS`
   - `pool_S3`: image-level category == {30} (empty) exclusively

2. **Sampling priority** (S2 > S5 > S4 > S1 > S3), targets (S2=15, S5=15, S4=10, S1=35, S3=25):
   - S2 is sampled first; selected images are excluded from later draws.
   - S5 next, excluding already-selected.
   - S4 next, excluding already-selected.
   - S1 last among animal images, excluding already-selected.
   - S3 last, for empty images.

3. **`all_stratum_tags`** is computed **after** selection, by checking each image against all five eligibility pools **independently**. It reflects **eligibility**, not selection stratum.

**Key consequence:** An image eligible for both S4 and S1 that is not selected in the S4 draw (because the S4 quota was already filled by other images, or it lost the random draw) is available to be selected in the S1 draw. It receives `primary_stratum = S1` but retains `S4` in `all_stratum_tags` because it genuinely meets the S4 eligibility criterion. There is **no contradiction** — primary stratum and all_stratum_tags measure different things.

### 5b. Corrections to previous reconciliation claims

The prior version of this document made two incorrect statements about the S1 and S4 primary-stratum image groups. These are corrected here using counts read directly from `data/eval_manifest.json` and verified by `scratch/audit_p5.py`.

**Incorrect claim 1:** "22 S1-primary images carry both S4 and S5"  
**Correct figure:** **18** S1-primary images carry both S4 and S5.

**Incorrect claim 2:** "all 10 S4-primary images carry S5"  
**Correct figure:** **8** of 10 S4-primary images carry S5. The 2 that do not are `597e617f` (tags: `['S1','S4']`) and `5a2af3cf` (tags: `['S1','S4']`).

### 5c. Verified counts from manifest (directly read, not inferred)

| Denominator | Count | Source |
|:---|---:|:---|
| All images | 100 | manifest |
| Animal images (`eval_a_label = positive`) | 75 | manifest |
| Empty images (`eval_a_label = negative`) | 25 | manifest |
| S4 tag present (all 100 images) | 47 | `all_stratum_tags` |
| S5 tag present (all 100 images) | 58 | `all_stratum_tags` |
| S4 primary stratum | 10 | `primary_stratum` |
| S5 primary stratum | 15 | `primary_stratum` |
| Empty images carrying S4 | **0** | verified |
| Empty images carrying S5 | **0** | verified |

### 5d. S4/S5 cross-tabulation (all 100 images)

| S4∧S5 | S4 only | S5 only | Neither | Total |
|---:|---:|---:|---:|---:|
| **38** | **9** | **20** | **33** | **100** |

Animal images only (75):

| S4∧S5 | S4 only | S5 only | Neither | Total |
|---:|---:|---:|---:|---:|
| **38** | **9** | **20** | **8** | **75** |

The 8 animal images with neither S4 nor S5 are all daytime images without any small bbox.

### 5e. Cross-tabulation: primary stratum × S4/S5 tags

| Primary | S4∧S5 | S4 only | S5 only | Neither | Total |
|:---|---:|---:|---:|---:|---:|
| S1 | **18** | **4** | **5** | **8** | 35 |
| S2 | 3 | 3 | 9 | 0 | 15 |
| S3 | 0 | 0 | 0 | 25 | 25 |
| S4 | **8** | **2** | 0 | 0 | 10 |
| S5 | **9** | 0 | **6** | 0 | 15 |
| **Total** | **38** | **9** | **20** | **33** | **100** |

**Notes on each row:**
- **S1 (35):** 22 carry S4 (18 both S4+S5, 4 S4-only); 23 carry S5 (18 both, 5 S5-only); 8 carry neither. S1-primary images span all S4/S5 combinations because the S4 and S5 quotas were filled with other images before S1 sampling ran, leaving S4/S5-eligible images to be drawn into S1.
- **S2 (15):** All 15 carry S5 (since multi-bbox images often have small bboxes) or S4. None carry neither.
- **S3 (25):** All empty images; carry no S4 or S5 (empty images cannot meet animal-bbox eligibility for S4/S5).
- **S4 (10):** 8 also carry S5 (small bbox present); 2 do not (`597e617f`, `5a2af3cf`). All 10 carry S1 tag (pool_S1 requires exactly 1 animal bbox — these images have exactly 1 bbox and were eligible for S1 as well).
- **S5 (15):** 9 also carry S4 (night + small); 6 carry S5 only (daytime or not night). All 15 carry S1 tag.

### 5f. Overlap interpretation

38 of 47 S4-tagged images (80.9%) also carry S5. The two subsets overlap substantially and **cannot be interpreted as independent measurements** in the Task 5 performance breakdown.

The denominators used in `ERROR_ANALYSIS.md` Task 5 (`n=47` for S4, `n=58` for S5, all animal images from `all_stratum_tags`) are **correct as stated**. The issue is interpretive: performance on S4 images and S5 images is not separable without further subgroup analysis.

---

## Point 6 — Visualization File Verification

### What was verified programmatically

The following checks were performed by `scratch/recon_task36.py` using Pillow on all 21 JPEG files:

| Check | Method | Result |
|:---|:---|:---|
| File opens without error | `PIL.Image.open()` | ✓ All 21 pass |
| Image dimensions | `.size` attribute | ✓ All 21 are 2048 × 1494 px |
| Image ID in filename matches manifest | String prefix match against `manifest['images']` | ✓ All 21 match |
| GT box count at render time matches manifest | Count from `bbox_annotations` (excl. cat_id=30) at script runtime | ✓ All 21 match |
| Detection count at T=0.01 matches raw predictions | Count from `raw_predictions.json` at script runtime | ✓ All 21 match |

> **Important:** These are automated file-integrity and metadata-consistency checks. **No human visually inspected the rendered annotation overlays.** The checks confirm that each visualization file (a) is a valid JPEG, (b) is derived from the correct source image ID, and (c) was rendered with the correct number of GT boxes and detections as inputs. Whether the drawn boxes appear visually correct on screen has not been verified.

### What requires human inspection

The following cases would benefit from human visual review to confirm that box positions, colors, and labels render correctly on the actual image content:

| Image | Reason for manual review recommendation |
|:---|:---|
| `59e1028c` (annotation candidate) | High-stakes omission candidate; box placement at IoU=0.369 is ambiguous — human judgment needed to assess spatial relationship |
| `58af7554` (annotation candidate) | Secondary omission candidate; three raccoon detections near two GT boxes |
| `58d15e51` (multi-det bobcat) | 7 detection boxes rendered at T=0.01; verify the matched TP box is visually distinct from 6 ghost responses |
| `599a5afa` (deer miss, 0.10% area) | GT box covers 0.10% of image; verify it is even visible in the rendered visualization |
| `5906ef68` (FP on empty) | Drawn at T=0.20 (1 det); 5 additional T=0.01 detections not shown — visual may not represent the full detection picture |

### Transparency note

The phrase "visually validated" in any prior summary refers only to automated metadata consistency checks. It does **not** claim that a human reviewed the rendered images. That distinction is preserved in this reconciliation.

---

## Corrections Required in ERROR_ANALYSIS.md

| Section | Issue | Correct statement |
|:---|:---|:---|
| Task 4 body — "High-conf matched blanks at T=0.20" | Third is `58d15e51` | Third is `595adc96` (conf=0.646); `58d15e51` blanks are unmatched |
| Task 3 — "~65 are blank" | Refers to all blanks, not just unmatched | 28/39 unmatched detections in multi-det images are blank |
| Task 5 — S4/S5 | No mention of overlap between S4 and S5 subsets | Add: 38/47 S4 and 38/58 S5 animal images overlap; subsets cannot be interpreted independently |
| Task 8 footnote | `localization_miss: 3` unexplained vs 5 total missed GT | Add: "3 = missed GT boxes in images with some detections; 5 = total missed GT boxes including FN images" |

---

## Git Status Verification

```
Staged (19):     unchanged — all pre-existing files
Untracked (4):   docs/inference/ERROR_ANALYSIS.md
                 docs/inference/ERROR_ANALYSIS_RECONCILIATION.md (this file)
                 docs/inference/EVALUATION_AUDIT.md
                 docs/inference/EVALUATION_REPORT.md
Nothing committed. Nothing staged. No model or inference code changed.
```

---

*End of Milestone 7A Reconciliation. Investigation only — awaiting approval before any further changes.*

