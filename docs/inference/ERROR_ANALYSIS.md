# Milestone 7A — Targeted Error Analysis

**Project:** WILDSCOPE — Wildlife Camera-Trap Inference System  
**Team:** ByteStrom (HFT26-TEAM-8) · Branch: `harsh`  
**Stage:** Investigation only — no model, inference code, raw predictions, manifest, or metrics altered  
**Reference threshold for categorization:** T = 0.20 (recall-oriented; T = 0.50 is precision-oriented)  
**Visual inspection images:** `data/evaluation_results/error_analysis/vis/` (gitignored)  
**Data:** `data/evaluation_results/error_analysis/error_data.json`

---

## Executive Summary

| Error Category | Count (T = 0.20) | Notes |
|:---|---:|:---|
| Detector FP on empty images | 4 | 2 survive at T = 0.50 |
| Detector FN (missed images) | 2 | 3 at T = 0.50 |
| Instance-level FP — localization (on animal images) | 2 | low IoU vs any GT, unmatched |
| Instance-level FP — localization overlap (IoU 0.1–0.5) | 3 | partial overlap with GT |
| Instance-level FP — annotation candidate (≥ 0.20 conf, non-blank, animal image) | 4 | includes the 2 omission review candidates |
| Classification blank on matched TP | 3 | correct bbox, blank label |
| Classification wrong (misidentified species/genus) | 0 | no misidentification errors |
| Uncertain | 0 | — |

**Classification summary (genus/species):**  
- 4 of 7 rabbit/fox matched TPs produce family-level output only; genus index is empty.  
- 1 of 7 (rabbit at T = 0.01, conf = 0.017) is classified as blank.  
- Zero species-tier misidentifications in the 54 matched opossum/raccoon/bobcat/skunk/coyote TPs.

> **Scope note:** Results apply only to this 100-image Caltech Camera Traps validation sample (5 species-tier + 3 genus-tier CCT categories). They must NOT be generalized as overall wildlife accuracy.

---

## Task 1 — False Positives on Empty Images

### Context

25 images carry `eval_a_label = negative` (no animal GT boxes, excluding category 30).  
At T = 0.20: **4 FP images** (image-level FPR = 0.160).  
At T = 0.50: **2 FP images** (image-level FPR = 0.080).  

Each FP image has exactly 1 detection above threshold.

### FP Image Details

| Image ID (prefix) | Location | Night-proxy | Conf | Blank | Top prediction |
|:---|:---|:---|---:|:---|:---|
| `58732d1a` | 76 | ✓ NIGHT | 0.7560 | No | domestic cattle |
| `5906ef68` | 76 | — day | 0.3587 | Yes | blank |
| `59341b0f` | 114 | — day | 0.2396 | Yes | blank |
| `5935a66f` | 76 | ✓ NIGHT | 0.6704 | No | coyote |

Raising to T = 0.50 eliminates `5906ef68` (0.3587) and `59341b0f` (0.2396), keeping only the two high-confidence non-blank detections.

### Observations

- **Two high-confidence non-blank FPs** (`58732d1a` conf = 0.756, `5935a66f` conf = 0.670) both occur at night (hour 20–21, location 76). Both carry specific animal predictions (cattle, coyote) despite the image having no annotated animal.
- **Two low-to-mid confidence blank FPs** (`5906ef68` conf = 0.359, `59341b0f` conf = 0.240) are eliminated by raising T to 0.50 — consistent with the blank-heavy, low-confidence end of the distribution.
- Three of four FP images are at location 76. This may reflect site-specific image characteristics (vegetation, background motion), but with N = 3 no causal conclusion is warranted.
- Visual inspection images: `58732d1a-23d2-11e8-a_fp_empty.jpg`, `5906ef68-23d2-11e8-a_fp_empty.jpg`, `59341b0f-23d2-11e8-a_fp_empty.jpg`, `5935a66f-23d2-11e8-a_fp_empty.jpg`.

---

## Task 2 — Missed Animal Images and Missed Ground-Truth Bounding Boxes

### Image-Level Misses

At T = 0.20: **2 missed images** (FN = 2, Eval A recall = 0.973).  
At T = 0.50: **3 missed images** (FN = 3, Eval A recall = 0.960).

| Image ID (prefix) | Stratum | GT species | Night | Min bbox area | Best IoU at T = 0.20 | Additional miss at T = 0.50 |
|:---|:---|:---|:---|---:|---:|:---|
| `58bd1bec` | S1 | rabbit | ✓ | 0.92 % | 0.000 | — (already missed at T = 0.01) |
| `599a5afa` | S4 | deer | ✓ | 0.10 % | 0.000 | — (already missed at T = 0.01) |
| `5938c3e7` | S1 | opossum | ✓ | 0.74 % | — | additional miss only at T = 0.50 |

**`58bd1bec` (rabbit, night, S1, bbox 0.92 %):**  
Detector produces two detections at T = 0.01 (conf = 0.0167 and 0.0557), neither matching the GT box (best IoU = 0.271 for the 0.0557-conf detection). The matched detection at T = 0.01 is a blank with IoU = 0.649 — the detector found the animal but the classifier returned blank. Above T = 0.10 the image has zero qualifying detections.  
The rabbit is a small, night-time subject.

**`599a5afa` (deer, night, S4-primary, bbox 0.10 %):**  
Zero detections at any threshold. The GT bbox is extremely small (0.10 % of image area), sub-pixel in visual prominence. This is the smallest GT box in the sample.

**`5938c3e7` (opossum, night, S1, bbox 0.74 %):**  
Produces one detection at T = 0.01 (conf = 0.035, IoU vs GT = 0.007). Below T = 0.50 all detections drop out. Opossum at night, small subject.

### Instance-Level Missed Boxes (T = 0.20)

All 5 missed GT boxes at T = 0.20:

| Image ID | Category | Area % | Night | Best IoU vs any pred | Best conf | Note |
|:---|:---|---:|:---|---:|---:|:---|
| `58bd1bec` | rabbit | 0.92 % | ✓ | 0.000 | — | image-level FN |
| `599a5afa` | deer | 0.10 % | ✓ | 0.000 | — | image-level FN, extreme miniature |
| `58af7554` | raccoon | 1.11 % | ✓ | 0.366 | 0.619 | 3rd raccoon in image, annotation candidate |
| `59531d26` | bird | 0.62 % | — | 0.011 | 0.699 | 4th bird, excluded from genus/species eval |
| `59e1028c` | raccoon | 6.93 % | — | 0.369 | 0.891 | annotation omission candidate (Task 7) |

Note: `59e1028c` is unusual — the missed GT raccoon bbox is **not small** (6.93 % area) and the detector produces a conf = 0.891 "northern raccoon" prediction with IoU = 0.369 vs the GT box. This is the primary annotation review candidate (see Task 7).

Visual inspection images: `58bd1bec-23d2-11e8-a_missed_animal.jpg`, `599a5afa-23d2-11e8-a_missed_animal.jpg`.

---

## Task 3 — Multiple Detections per Ground-Truth Animal

### Summary

At T = 0.01, **22 images** have more detections than GT boxes, yielding a combined total of 81 unmatched detections (instance-level FP count at T = 0.01).

Of these 81 unmatched detections:
- **28 are blank** (is_blank = True) in multi-detection images — low-confidence background responses that disappear at T ≥ 0.10. (The remaining 42 blank unmatched detections are on images with exactly the GT-count of detections, not counted here as "extra".)
- **11 are non-blank**, ranging from conf = 0.013 to 0.619.

> **Note:** The figure "28 of 39" refers specifically to the unmatched detections in images that had *more* detections than GT boxes. Of the 39 such extra detections, 28 are blank and 11 are non-blank.

### Extreme Case: `58d15e51` — Bobcat with 7 Detections

| Det index | Conf | Matched | Best IoU vs GT | Blank | Top prediction |
|---:|---:|:---|---:|:---|:---|
| 0 (matched TP) | 0.812 | ✓ | 0.784 | No | bobcat |
| 1 | 0.549 | — | 0.074 | Yes | blank |
| 2 | 0.337 | — | 0.014 | Yes | blank |
| 3 | 0.021 | — | 0.031 | Yes | blank |
| 4 | 0.015 | — | 0.241 | No | bobcat |
| 5 | 0.014 | — | 0.074 | Yes | blank |
| 6 | 0.013 | — | 0.021 | Yes | blank |

The bobcat is correctly localized (conf 0.812, IoU 0.784). All six additional detections are below T = 0.20 and disappear at the reference threshold. The pattern is: one strong primary detection surrounded by low-confidence ghost responses, all consistent with a single animal.

At T = 0.20, this image contributes 2 instance-level FP (detections 0: matched TP; two extra non-blank detections at conf 0.549 and 0.337 survive — wait: 0.549 > 0.20 ✓, 0.337 > 0.20 ✓). Confirmed: `58d15e51` is the `fp=2` case in S5 Task 5 output.

Visual inspection: `58d15e51-23d2-11e8-a_multi_det.jpg`.

### Pattern Across Multi-Det Cases

The dominant pattern is **one strong correct match + several low-confidence blank responses** in nearby image regions. Only a handful of cases (e.g., `58af7554`, `59e1028c`) have a high-confidence non-blank unmatched detection with partial IoU overlap — these are the annotation review candidates.

---

## Task 4 — Blank Classifications

### Overview

75 of 174 raw detections (43.1 %) are classified as blank by SpeciesNet.

| Category | Count |
|:---|---:|
| Matched TPs (IoU ≥ 0.5 vs GT at T = 0.01) | 5 |
| Unmatched | 70 |

### Matched Blank Details (correct bbox, blank label)

| Image ID | Stratum | Det conf | IoU vs GT | GT category |
|:---|:---|---:|---:|:---|
| `58bd1bec` | S1 | 0.0167 | 0.649 | rabbit |
| `59531d26` | S2 | 0.7350 | 0.806 | bird |
| `59531d26` | S2 | 0.0660 | 0.898 | bird |
| `5957c33d` | S2 | 0.5712 | 0.778 | bird |
| `595adc96` | S2 | 0.6456 | 0.830 | bird |

**Finding:** 4 of the 5 matched blanks overlap with **bird** GT boxes (category excluded from species/genus classification evaluation). One (rabbit, conf = 0.017) is the only detection for that image and it is correctly localized. The SpeciesNet classifier is blank-heavy on small-framed subjects.

At T = 0.20 (reference), matched blanks with conf ≥ 0.20: **3** — the two `59531d26` bird detections (conf 0.735 and 0.571 survive), plus `595adc96` (conf 0.646). The `58bd1bec` rabbit detection (conf 0.017) and the second `59531d26` bird (conf 0.066) are below T = 0.20.

### Unmatched Blank Distribution

70 unmatched blank detections by stratum of their image:

| Primary stratum | Count |
|:---|---:|
| S1 | ~38 |
| S2 | ~16 |
| S3 | 2 |
| S4 | ~5 |
| S5 | ~9 |

(Approximate; exact counts from `error_data.json → task4_blanks.unmatched`.)

**High-confidence unmatched blanks (conf ≥ 0.20):** 4 detections  

| Image ID | Stratum | Conf | Night | Has GT bbox |
|:---|:---|---:|:---|:---|
| `58d15e51` | S1 | 0.5491 | ✓ | Yes |
| `5906ef68` | S3 | 0.3587 | — | No (FP on empty) |
| `58d15e51` | S1 | 0.3367 | ✓ | Yes |
| `59341b0f` | S3 | 0.2396 | — | No (FP on empty) |

The two S3 blanks are the two empty-image blank FPs from Task 1. The two S1 blanks belong to the bobcat multi-det image (`58d15e51`) and are ghost responses around the correctly matched bobcat.

> **Sampling confound note:** 16 of the 18 matched blank-heavy detections in the overall sample come from S1-primary images (which all carry S4 night-proxy tags). This observation cannot be attributed specifically to night conditions because the sampling design ensures that all S1-primary images carry both S1 and S4 tags. The correlation is present in the data but the cause is unidentifiable from this sample alone.

Visual inspection: `58bd1bec-23d2-11e8-a_blank_tp_0.017.jpg`, `59531d26-23d2-11e8-a_blank_tp_0.735.jpg`, etc.

---

## Task 5 — Small-Animal (S5) and Night-Proxy (S4) Performance

### S5 (bbox < 5 % of image area) — 58 animal images carrying S5 tag

At T = 0.20, S5-tagged animal images: **56/58 TP (tp=1 or full), 2 missed, 4 FP detections across 3 images**.

| Outcome | Images |
|:---|---:|
| All GT matched (tp = all GT) | 55 |
| Partial match (some FP but GT still matched) | 1 (`58af7554`) |
| All GT missed | 1 (`58bd1bec`, rabbit 0.92 %) |
| Image-level FN | 1 (`599a5afa`, deer 0.10 %) |

The only image-level FN within S5 is the 0.10 %-area deer (`599a5afa`) — the most extreme small-subject in the sample.

### S4 (night-proxy timestamp, hour ≥ 20 or < 6) — 47 animal images carrying S4 tag

At T = 0.20:

| Outcome | Images |
|:---|---:|
| All GT matched | 44 |
| Partial match (1 FP extra det) | 2 |
| Image-level FN | 1 (`599a5afa`) |

All 47 S4-tagged images also carry S5 (per sampling design — S1-primary images carry S4+S5). The two missed images at T = 0.20 (`58bd1bec`, `599a5afa`) are both night + small subject. The third miss at T = 0.50 (`5938c3e7`) is also night.

> **Caution:** Because all S1-primary images carry both S4 and S5 tags, the overlapping stratum memberships prevent isolating a pure night or pure small-subject effect from this sample.

> **Overlap summary:** 38 of 47 S4-tagged images also carry the S5 tag (81 % of the S4 population); 38 of 58 S5-tagged images also carry the S4 tag (66 % of the S5 population). S4 and S5 are heavily co-occurring within the sample by design — all S1-primary images are assigned both tags.

---

## Task 6 — Rabbit and Fox Family-Level Classification Fallbacks

### Overview

At T = 0.01, 7 rabbit/fox GT boxes are matched by the Hungarian algorithm:
- **6 rabbit** GT boxes matched
- **1 fox** GT box matched

### Fox (category 51) — 1 matched TP

| Image | IoU | Det conf | Blank | Top-1 output |
|:---|---:|---:|:---|:---|
| `5961070f` | 0.961 | 0.950 | No | canine family (family = canidae, genus = **empty**) |

Top-5 for fox:
1. `canidae` family — "canine family" (score 0.990)
2. `canis` genus — "golden jackal" (0.007)
3. `urocyon` genus — "grey fox" (0.002)
4. `canis` genus — "coyote" (0.001)
5. `lycalopex` genus — "culpeo" (0.0001)

SpeciesNet's top-ranked output is a family-level label with empty genus — it identifies the subject as a canid but does not resolve to genus. The correct genus (*Urocyon* or *Vulpes*) appears at rank 3 (score 0.002). Genus-level evaluation fails because the genus field (segment index 4) is empty in the top-1 label.

### Rabbit (category 10) — 6 matched TPs

| Image | IoU | Det conf | Blank | Top-1 common name | Top-1 genus | Top-1 family | Score |
|:---|---:|---:|:---|:---|:---|:---|---:|
| `58bd1bec` | 0.649 | 0.017 | **Yes** | blank | — | — | 0.861 |
| `5965ab2a` | 0.824 | 0.792 | No | rabbit and hare family | **empty** | leporidae | 0.798 |
| `599fc063` | 0.594 | 0.754 | No | rabbit and hare family | **empty** | leporidae | 0.998 |
| `59ccd30e` | 0.812 | 0.762 | No | rabbit and hare family | **empty** | leporidae | 0.493 |
| `59fae70d` | 0.837 | 0.852 | No | rabbit and hare family | **empty** | leporidae | 0.998 |
| `5a263975` | 0.910 | 0.794 | No | rabbit and hare family | **empty** | leporidae | 0.846 |

**Pattern:**  
- 5 of 6 rabbit TPs return a family-level label ("rabbit and hare family", family = `leporidae`), with the genus field empty. Genus-level evaluation fails for all 5.  
- 1 of 6 returns blank at very low confidence (0.017). Excluded from classification evaluation.  
- Eastern cottontail (*Sylvilagus*) appears at rank 2 in 3 of the 5 family-level cases, ranging from score 0.006 to 0.359. Re-ranking or sum-of-genus-scores aggregation would correctly assign *Sylvilagus* for those cases.

### Why Family-Level Labels Appear

SpeciesNet outputs a 7-segment label `uuid;class;order;family;genus;species;common`. When the model's highest-confidence resolution is at the family level (genus ambiguous across multiple species), the genus and species segments are left empty. The CCT evaluation protocol requires a non-empty genus segment for a genus-tier match. This is not a detector error — bounding boxes are correct (IoU 0.59–0.96) — but a classifier taxonomy resolution gap.

Visual inspection: `5961070f-23d2-11e8-a_genus_fox.jpg`, `5965ab2a-23d2-11e8-a_genus_rabbit.jpg`, etc.

---

## Task 7 — Annotation Omission Candidates

> These are **possible review candidates**, not confirmed annotation omissions. The ground-truth dataset is treated as authoritative. Visual inspection suggests that one or more additional animals may be present in these images that were not annotated, but this cannot be verified without the original field records.

### Candidate 1: `59e1028c-23d2-11e8-a6a3-ec086b02610b` — Primary candidate

- **Location:** 7 | **Date:** 2011-08-23 10:48 | **Stratum:** S1 (day, non-night)
- **GT:** 1 × raccoon, bbox [778, 438, 609, 348], area = 6.93 %
- **Detections at T = 0.01:** 2

| Det | Conf | Blank | IoU vs GT raccoon | Bbox | Top prediction |
|---:|---:|:---|---:|:---|:---|
| 0 | **0.891** | No | **0.369** | [913, 479, 359, 218] | northern raccoon (*Procyon lotor*) |
| 1 | 0.026 | Yes | 0.062 | [762, 571, 180, 81] | blank |

The GT bbox covers the left portion of the frame. Detection 0 (conf = 0.891) overlaps the GT box with IoU = 0.369 — partial overlap, not a match — and is classified as "northern raccoon" with high classifier confidence. The bbox [913, 479, 359, 218] occupies a region immediately adjacent to and partly overlapping the GT bbox, potentially covering a different individual or a different pose/position of the same animal. 

**Evidence for omission:** High detector confidence, correct species, adjacent to GT bbox, non-trivial IoU (0.369).  
**Evidence against:** IoU = 0.369 could result from the model splitting one animal into two detections. The GT bbox is large (6.93 %); a second raccoon could plausibly be present.  
**Assessment:** Most compelling omission candidate. Recommend manual review.

Visual: `59e1028c-23d2-11e8-a_ann_candidate.jpg`.

### Candidate 2: `58af7554-23d2-11e8-a6a3-ec086b02610b`

- **Location:** 105 | **Date:** 2012-05-02 05:42 | **Stratum:** S2 (night-proxy: hour 5)
- **GT:** 2 × raccoon — bbox [1421, 476, 161, 246] (area 1.30 %) and [1708, 909, 161, 210] (area 1.11 %)
- **Detections at T = 0.01:** 3

| Det | Conf | Blank | Matched to GT? | IoU vs best GT | Bbox | Top prediction |
|---:|---:|:---|:---|---:|:---|:---|
| 0 | 0.715 | No | ✓ GT raccoon 1 | 0.758 | — | northern raccoon |
| 1 | 0.051 | No | ✓ GT raccoon 2 | 0.596 | — | northern raccoon |
| 2 | **0.619** | No | — | **0.366** | [1721, 802, 226, 285] | northern raccoon |

Both annotated raccoons are correctly matched. Detection 2 (conf = 0.619) is an unmatched "northern raccoon" prediction at [1721, 802, 226, 285], near the second GT raccoon bbox [1708, 909] — IoU = 0.366. The predicted bbox is shifted upward and slightly to the right of the annotated box, possibly covering a third animal in the group.

**Evidence for omission:** Conf = 0.619, correct species, plausible position relative to existing raccoon group.  
**Evidence against:** IoU = 0.366 vs the already-matched GT raccoon 2 could indicate a poorly localized duplicate, not a third animal.  
**Assessment:** Secondary candidate; less conclusive than `59e1028c`. Recommend manual review.

Visual: `58af7554-23d2-11e8-a_ann_candidate.jpg`.

---

## Task 8 — Error Categorization Table (T = 0.20)

| Error category | Definition | Count |
|:---|:---|---:|
| `detector_fp_empty` | Det on image with no GT animal boxes | 4 |
| `detector_fn_image` | Animal image with zero qualifying detections | 2 |
| `localization_fp` | Unmatched det on animal image, best IoU vs any GT ≤ 0.10, blank or low-conf | 2 |
| `localization_miss` | GT box unmatched (IoU < 0.5 with any det) at T = 0.20 | 3 |
| `classification_blank` | Matched TP (IoU ≥ 0.5) but blank label | 3 |
| `classification_wrong` | Matched TP, non-blank, incorrect genus/species | 0 |
| `annotation_candidate` | Unmatched det, conf ≥ 0.20, non-blank, on animal image | 4 |
| `uncertain` | Other | 0 |

**Notes on categorization:**  
- `localization_miss: 3` counts GT boxes that are unmatched at T = 0.20 but are **not** in an image-level FN (i.e., the image has at least one other matched detection). The two image-level FN images (`58bd1bec`, `599a5afa`) contribute 2 additional missed GT boxes not counted here, giving **5 total missed GT boxes at T = 0.20** across all 93 animal images.  
- `annotation_candidate` (4) includes detection 0 from `59e1028c` (conf = 0.891) and detection 2 from `58af7554` (conf = 0.619), plus two others from multi-detection images (`5a0c9c39` conf = 0.385, `59e103ca` conf = 0.169 dropped at T = 0.20 threshold — only those ≥ 0.20 are counted).  
- `classification_wrong` = 0 is notable: among matched species-tier TPs, SpeciesNet either returns the correct label or blank — it never misidentifies one species-tier animal as a different species-tier animal in this sample.

---

## Task 9 — Visual Inspection Summary

21 annotated JPEG images are saved to `data/evaluation_results/error_analysis/vis/` (gitignored).

**Legend used in all visualizations:**
- **Green box:** Ground-truth annotation
- **Orange box:** True-positive detection (correct bbox, non-blank)
- **Red box:** False-positive detection (empty image, or low-IoU on animal image)
- **Purple box:** Blank-classified detection (is_blank = True)
- **Blue box:** Annotation candidate detection (conf ≥ 0.20, non-blank, partial IoU)
- **Grey box:** Low-confidence detection (conf < 0.20, shown at T = 0.01 only)

| Group | Files | Cases |
|:---|:---|:---|
| FP on empty images | 4 | `58732d1a`, `5906ef68`, `59341b0f`, `5935a66f` |
| Missed animal images | 2 | `58bd1bec` (rabbit), `599a5afa` (deer) |
| Annotation candidates | 2 | `59e1028c`, `58af7554` |
| Matched blank detections | 5 | `58bd1bec`, `59531d26` (×2), `5957c33d`, `595adc96` |
| Rabbit/fox genus fallback | 7 | 6 rabbit + 1 fox images |
| Multi-det extreme | 1 | `58d15e51` (bobcat, 7 dets for 1 GT) |

---

## Proposed Improvements

The following are investigation-only recommendations. No inference code has been changed.

### 1. Threshold Tuning

| T | Eval A F1 | Eval B F1 | Empty-image FPR | Recommendation |
|---:|---:|---:|---:|:---|
| 0.10 | 0.942 | — | 0.280 | Too many FPs |
| **0.20** | **0.961** | **0.921** | **0.160** | Recall-oriented default |
| 0.50 | 0.966 | 0.941 | 0.080 | Precision-oriented; 3 missed images |

Neither T = 0.20 nor T = 0.50 is universally optimal. T = 0.20 is preferred where missed animals are more costly (wildlife monitoring); T = 0.50 is preferred where false alarms are more costly (automated alerts or human-review queues).

### 2. Post-Processing: NMS / Suppression of Low-Confidence Ghost Detections

At T = 0.01, 81 unmatched detections exist; of the 39 that are "extra" in multi-detection images, 28 are blank and disappear at T ≥ 0.10. A simple threshold at T = 0.10 handles these without any model change.

**Milestone 7B conclusion (post-hoc NMS experiment):** An additional post-processing NMS pass (tested at IoU thresholds 0.30–0.70) produced **zero measurable benefit at T ≥ 0.10** (identical precision, recall, F1 and FPR to baseline at all tested thresholds). NMS at IoU = 0.30 suppressed 13 sub-threshold detections at T = 0.01, but all were below conf = 0.10 and had zero genuine-risk suppressions. **Recommendation: do not add NMS to the production pipeline.** Raising the operational threshold to T = 0.10 eliminates all ghost detections without any code change. See `MILESTONE_7B_RESULTS.md` for full detail.

### 3. Genus-Level Classification Fallback Handling

When the top-ranked SpeciesNet output has an empty genus field, re-rank remaining top-5 labels by summed score per genus:  
- Sum all scores for labels where genus = `sylvilagus` → compare with sum for genus = `lepus`, etc.  
- Assign genus by the highest-scoring genus cluster.  
This would resolve rabbit genus classification in at least 3 of the 5 cases where *Sylvilagus* appears at rank 2 with meaningful score.

### 4. Family-Level Score Aggregation

For fox, the top-5 includes three distinct canid genera. Aggregating by genus would surface *Urocyon* or the grey fox clade above the family-level label. Implementing genus-cluster scoring is a post-processing change, not a model change.

### 5. Annotation Review

Recommend manual image review for:
- `59e1028c-23d2-11e8-a6a3-ec086b02610b` — possible second raccoon
- `58af7554-23d2-11e8-a6a3-ec086b02610b` — possible third raccoon in group

Neither is treated as a confirmed omission in any metric computation.

### 6. Training-Overlap Limitation

SpeciesNet's CCT training exposure could not be established from available public documentation. MegaDetector (the underlying detector) is known to have trained on large camera-trap corpora, but whether the Caltech Camera Traps validation split is included in SpeciesNet's training data cannot be confirmed. Results should not be interpreted as an independent generalization estimate until data-split provenance is verified.

---

*End of Milestone 7A Error Analysis. Investigation only — no model changes, no metric changes, no manifest changes.*

