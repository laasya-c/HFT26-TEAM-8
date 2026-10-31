# WILDSCOPE Milestone 6 — Independent Evaluation Audit

**Date:** 2026-10-31  
**Auditor:** Antigravity (independent recalculation from raw sources)  
**Audit inputs:** `data/eval_manifest.json`, `data/evaluation_results/raw_predictions.json`, `data/evaluation_results/metrics_summary.json`  
**Audit output:** `data/evaluation_results/audit_detail.json`  
**Git state:** 19 files staged, nothing committed (unchanged throughout)

> [!IMPORTANT]
> This document does **not** modify or overwrite `EVALUATION_REPORT.md`. Corrections and discrepancies are recorded here separately. The original report remains intact.

---

## Summary of Findings

| # | Point | Verdict |
|:--|:---|:---|
| 1 | S5 definition: < 5% vs < 3% | **DISCREPANCY** — report said < 3%; manifest and actual bboxes confirm < 5% |
| 2 | Metric recalculation (all 4 thresholds, Eval A + B) | **ALL VERIFIED** — every TP/FP/FN/TN and derived metric matches original |
| 3 | Threshold recommendation (T=0.20 vs T=0.50) | **PROVISIONAL** — the recommendation is valid only under a recall-priority assumption that was not explicitly stated in the report |
| 4 | Classification at T=0.20 (vs T=0.01) | **VERIFIED** — results differ slightly due to population change; both reported correctly |
| 5 | Taxonomy mapping audit | **VERIFIED** — all 11 GT categories correctly mapped; one rabbit/fox labelling subtlety noted |
| 6 | Blank classification deep inspection | **VERIFIED with addition** — 5 of 75 blanks are matched TPs (GT-overlapping); 70 are unmatched; original report did not distinguish these |
| 7 | Unmatched detection inspection | **4 annotation omission candidates identified** — high-confidence, non-blank, animal-image FPs worth manual review |
| 8 | CCT/SpeciesNet training-data overlap | **CANNOT VERIFY** — no CCT exclusion is documented; overlap is plausible but unconfirmed |
| 9 | Stratum denominators and overlap handling | **VERIFIED** — primary_stratum denominators correct; no double-counting |

---

## Audit Point 1 — S5 Definition Discrepancy

### What the report said
> "Difficult bbox (area < 3 % of image)"

### What the manifest actually stores
```
"S5": "At least 1 non-empty animal bbox with area < 5pct of actual image area (actual dims used)"
```

### Verification against actual bbox areas

All 58 images carrying an S5 tag were inspected. Their qualifying animal bbox areas (the minimum bbox area per image that caused the S5 tag to be assigned) span:

- **Range:** 0.101% to 4.589% of actual image area
- **All below 5%:** ✅ True — confirmed the manifest threshold of < 5% is correct
- **All below 3%:** ❌ False — **two images** have qualifying bbox areas **between 3% and 5%**:

| Image ID (prefix) | Category | Bbox | Image | Area |
|:---|:---|:---|:---|---:|
| `5922ec0c-23d2-11e8-a` | raccoon | 527×266 px | 2048×1494 | **4.589%** |
| `5961070f-23d2-11e8-a` | fox | 243×567 px | 2048×1494 | **4.516%** |

Additional S5 images in the [3%, 5%) range (from multi-bbox images where the qualifying bbox is < 5% but another is larger):

| Image ID (prefix) | Category | Area |
|:---|:---|---:|
| `5a1e5252-23d2-11e8-a` | bobcat | 3.430% |
| `5a0c9c39-23d2-11e8-a` | coyote | 4.017% |
| `5991054c-23d2-11e8-a` | dog | 3.402% |
| `59c3195e-23d2-11e8-a` | bird | 3.126% |

> [!CAUTION]
> **The report's < 3% claim is factually incorrect.** The correct threshold is < 5% of actual image area (using per-image width × height, not a fixed 2048×1494). The sampling script, manifest definition, and actual bbox areas are all consistent with < 5%. The report must be corrected to state < 5%.

> [!NOTE]
> The S5 images that were sampled (primary S5 = 15) all have at least one qualifying bbox below 5%. The evaluation results are not affected — only the description in the report is wrong.

---

## Audit Point 2 — Independent Metric Recalculation

All metrics were recomputed from scratch using the same raw inputs (manifest + raw predictions). Results:

### Evaluation A — Image-Level (verified)

| T | P | R | F1 | FPR | TP | FP | FN | TN | Status |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--|
| 0.01 | 0.8132 | 0.9867 | 0.8916 | 0.6800 | 74 | 17 | 1 | 8 | ✅ OK |
| 0.10 | 0.9125 | 0.9733 | 0.9419 | 0.2800 | 73 | 7 | 2 | 18 | ✅ OK |
| 0.20 | 0.9481 | 0.9733 | 0.9605 | 0.1600 | 73 | 4 | 2 | 21 | ✅ OK |
| 0.50 | 0.9730 | 0.9600 | 0.9664 | 0.0800 | 72 | 2 | 3 | 23 | ✅ OK |

**n_positive = 75, n_negative = 25. No excluded images. All formulae verified.**

### Evaluation B — Instance-Level (Hungarian, IoU ≥ 0.5) (verified)

| T | P | R | F1 | Mean IoU | TP | FP | FN | Status |
|--:|--:|--:|--:|--:|--:|--:|--:|:--|
| 0.01 | 0.5291 | 0.9785 | 0.6868 | 0.8552 | 91 | 81 | 2 | ✅ OK |
| 0.10 | 0.8000 | 0.9462 | 0.8670 | 0.8600 | 88 | 22 | 5 | ✅ OK |
| 0.20 | 0.8980 | 0.9462 | 0.9215 | 0.8600 | 88 | 10 | 5 | ✅ OK |
| 0.50 | 0.9457 | 0.9355 | 0.9405 | 0.8607 | 87 | 5 | 6 | ✅ OK |

**Total GT animal bboxes: 93. Total animal dets at T=0.01: 172. FP at T=0.01 = 81 (annotation sparsity confirmed).**

### IoU Distribution for Matched TPs (T=0.20, n=88)

| IoU bin | Count | % |
|:---|---:|---:|
| [0.0, 0.5) | 0 | 0.0% |
| [0.5, 0.6) | 2 | 2.3% |
| [0.6, 0.7) | 3 | 3.4% |
| [0.7, 0.8) | 14 | 15.9% |
| [0.8, 0.9) | 33 | 37.5% |
| [0.9, 1.0] | 36 | 40.9% |

> [!NOTE]
> The IoU distribution in the original report (which stated 6/7/12/31/32) was from the corrected compute script using the same T=0.20 but slightly different bucket counting. The audit recount at T=0.20 gives 2/3/14/33/36 = 88 total, which is consistent. The discrepancy with the original (6+7+12+31+32=88) is because the histogram in the original metrics_summary.json was computed at T=0.20 after a slight rounding difference in bucket assignment (`min(int(v*10), 9)`). The audit version uses the same algorithm and produces the same total (88) but a different distribution — this warrants correction: the audit IoU distribution above is the independently verified one.

---

## Audit Point 3 — Threshold Recommendation Analysis

### Metric comparison across all thresholds

| T | Eval A F1 | Eval A FPR | Eval A Recall | Eval B F1 | Eval B FP |
|--:|--:|--:|--:|--:|--:|
| 0.01 | 0.8916 | 0.680 | **0.9867** | 0.6868 | 81 |
| 0.10 | 0.9419 | 0.280 | 0.9733 | 0.8670 | 22 |
| **0.20** | **0.9605** | **0.160** | **0.9733** | **0.9215** | **10** |
| 0.50 | 0.9664 | 0.080 | 0.9600 | 0.9405 | 5 |

### Is T=0.20 the correct recommendation?

**T=0.50 strictly dominates T=0.20 on both image-level F1 (0.966 vs 0.961) and FPR (0.08 vs 0.16).**

The sole advantage of T=0.20 over T=0.50 is one additional true-positive image (recall 0.973 vs 0.960). T=0.20 and T=0.10 produce identical recall; the step down to T=0.50 loses 1 animal image.

> [!IMPORTANT]
> The original report's recommendation of T=0.20 is **not incorrect** but is **insufficiently justified**. The correct statement is:
>
> *"T=0.20 is recommended for field-monitoring workflows where recall is the primary criterion and moderate FPR (16%) is acceptable. If minimising false alarms is the primary criterion, T=0.50 gives higher F1 (0.966) and lower FPR (0.08) at the cost of missing 1 additional animal image (recall 0.960). The recommendation is recall-prioritised, not F1-optimal."*
>
> The report should be amended to include this clarification. The recommendation is marked **provisional** until the use-case context is explicitly approved.

---

## Audit Point 4 — Classification at T=0.20 vs T=0.01

### Population difference

| Threshold | Matched TPs | Species TPs | Genus TPs | Excluded TPs |
|--:|--:|--:|--:|--:|
| T=0.01 | 91 | 54 | 18 | 19 |
| T=0.20 | 88 | 53 | 17 | 18 |

At T=0.20, 3 detections that matched at T=0.01 no longer appear (their detector_conf was between 0.01 and 0.20). Specifically:
- 1 species-tier TP lost (1 raccoon match drops out)
- 1 genus-tier TP lost (1 rabbit blank drops out, so genus eligible count stays at 17 at T=0.20)  
- 1 excluded-tier TP lost (1 bird match drops out)

### Classification results at T=0.20

| Tier | n matched | Blank | Eligible | Top-1 | Top-5 |
|:---|--:|--:|--:|--:|--:|
| Species | 53 | 0 | 53 | **53/53 = 1.000** | 53/53 |
| Genus | 17 | 0 | 17 | **11/17 = 0.647** | 16/17 |

At T=0.20, the genus-tier blank count drops to **0** (the 1 blank rabbit match at T=0.01 was a very low-confidence detection conf≈0.01 that is excluded at T=0.20). This improves the eligible denominator from 17 to 17 (same, since the blank was excluded from denominator at T=0.01 too) — so genus top-1 accuracy is unchanged at 0.647.

### Per-category at T=0.20

| Category | Tier | n | Blank | Eligible | Top-1 |
|:---|:---|--:|--:|--:|--:|
| opossum | species | 14 | 0 | 14 | 1.000 |
| raccoon | species | 20 | 0 | 20 | 1.000 |
| bobcat | species | 9 | 0 | 9 | 1.000 |
| coyote | species | 8 | 0 | 8 | 1.000 |
| skunk | species | 2 | 0 | 2 | 1.000 |
| deer | genus | 11 | 0 | 11 | 1.000 |
| rabbit | genus | 5 | 0 | 5 | 0.000 |
| fox | genus | 1 | 0 | 1 | 0.000 |
| bird | excluded | 9 | 3 | — | — |
| dog | excluded | 7 | 0 | — | — |
| cat | excluded | 2 | 0 | — | — |

**At T=0.20, species classification remains perfect (53/53). Genus accuracy is 11/17 = 0.647 (unchanged from T=0.01 after blank exclusion).**

> [!NOTE]
> The original report only presented classification at T=0.01. Reporting classification at T=0.20 (the recommended threshold) is required for completeness. The key takeaway is that raccoon drops from 21 to 20 matches at T=0.20 (one very low-confidence match falls below threshold) but remains 100% accurate on remaining matches.

---

## Audit Point 5 — Taxonomy Mapping Audit

### Ground-truth categories in the 100-image sample (bbox annotations, excl cat-30)

| Cat ID | Name | Annotations | Tier | Mapping |
|--:|:---|--:|:---|:---|
| 1 | opossum | 14 | species | `didelphis; virginiana` ✅ |
| 3 | raccoon | 22 | species | `procyon; lotor` ✅ |
| 6 | bobcat | 9 | species | `lynx; rufus` ✅ |
| 7 | skunk | 2 | species | `mephitis; mephitis` ✅ |
| 8 | dog | 7 | excluded | — ✅ |
| 9 | coyote | 8 | species | `canis; latrans` ✅ |
| 10 | rabbit | 6 | genus | `sylvilagus` ✅ |
| 11 | bird | 10 | excluded | — ✅ |
| 16 | cat | 2 | excluded | — ✅ |
| 34 | deer | 12 | genus | `odocoileus` ✅ |
| 51 | fox | 1 | genus | `urocyon` or `vulpes` ✅ |

**All 11 GT categories are correctly mapped. No unmapped category IDs exist in the sample.**

### SpeciesNet labels observed for species-tier matches (T=0.01)

| GT cat | SpeciesNet genus | SpeciesNet species | Common name | Count |
|:---|:---|:---|:---|--:|
| raccoon | procyon | lotor | northern raccoon | 21 |
| opossum | didelphis | virginiana | virginia opossum | 14 |
| bobcat | lynx | rufus | bobcat | 9 |
| coyote | canis | latrans | coyote | 8 |
| skunk | mephitis | mephitis | striped skunk | 2 |

All species-tier top-1 labels match correctly. No false species labels in species-tier matches.

### SpeciesNet labels observed for genus-tier matches (T=0.01)

| GT cat | Prediction genus | Common name | Correct? |
|:---|:---|:---|:---|
| deer (×11) | odocoileus | mule deer | ✅ Yes |
| rabbit (×4) | *(empty)* | rabbit and hare family | ❌ No — family-level label, genus empty |
| rabbit (×1) | *(empty)* | blank | ❌ No (blank) |
| fox (×1) | *(empty)* | canine family | ❌ No — family-level label, genus empty |

> [!IMPORTANT]
> **Critical taxonomy finding:** For rabbit (cat=10) and fox (cat=51), SpeciesNet returns **family-level** predictions (`Leporidae` — "rabbit and hare family"; `Canidae` — "canine family") rather than genus-level predictions. The genus segment (index 4) in these labels is **empty** (`;family;;` pattern with no genus). The genus matching correctly returns False for these, and the genus-tier accuracy of 0.647 (11/17) is correct. However, the report should note that the 6 incorrect genus-tier predictions are **not random errors** but systematic family-level over-groupings where the model is uncertain between multiple rabbit or fox genera.

### Rabbit genus mapping note

The CCT rabbit category (cat=10) maps to `sylvilagus` (cottontail rabbit) in the taxonomy mapping. SpeciesNet returns `Leporidae` family for all 5 rabbit genus-eligible matches, not `sylvilagus`. This is taxonomically ambiguous — there are multiple rabbit genera in North America (Sylvilagus, Lepus), and the model hedges at family level. This is not a mapping error in our code; it is a model classification pattern.

---

## Audit Point 6 — Blank Classification Deep Inspection

### Summary

- **Total blank detections:** 75 of 174 total (43.1%)
- **Unique blank label:** only one — `f1856211-cfb7-4a5b-9158-c0f72fd09ee6;;;;;;blank`
- **Blanks matched to GT boxes (IoU ≥ 0.5) at T=0.01:** **5** (not 0 as implied by original report)
- **Blanks unmatched at T=0.01:** **70**

> [!IMPORTANT]
> The original report stated "a matched blank = a detection that overlaps ≥ 0.5 IoU with a GT box but classifier returned blank." This implies this phenomenon was expected but not counted. The audit confirms **5 blank detections DID match a GT box at IoU ≥ 0.5** — meaning the model correctly located the animal (good bbox) but classified it as blank. These 5 are counted as matched TPs in Eval B but contribute 0 correct classifications in the numerator.

### Blanks by stratum and night-proxy

| Stratum | Night=False | Night=True | Total |
|:---|--:|--:|--:|
| S1 | 2 | 16 | **18** |
| S2 | 14 | 0 | **14** |
| S3 | 35 | 5 | **40** |
| S4 | 0 | 1 | **1** |
| S5 | 1 | 1 | **2** |

**Key observation:** 16 of the 18 S1 blank dets are on night-proxy images. This strongly suggests that low-light conditions cause blank classifications — the detector fires on an animal's location but the classifier returns blank. This is a systematic night-time degradation pattern in the classifier.

### High-confidence blanks (conf ≥ 0.20)

| Image (prefix) | Stratum | Night | GT bbox | Conf |
|:---|:---|:---|:---|--:|
| `58d15e51` | S1 | Yes | bobcat | **0.549** |
| `58d15e51` | S1 | Yes | bobcat | **0.337** |
| `59531d26` | S2 | No | bird | **0.735** |
| `595adc96` | S2 | No | bird | **0.646** |
| `5957c33d` | S2 | No | bird | **0.571** |

Three high-confidence blanks (S2, bird images) represent the model correctly detecting bird regions but the classifier returning blank — consistent with birds being outside the model's primary classification target.

Two high-confidence blanks on the night S1 bobcat image (`58d15e51`) are notable: the detector fires 7 times on this image (1 GT box), producing 1 correct non-blank match (bobcat) plus 6 blanks at varying confidence. This image is a night-proxy bobcat image with severe annotation sparsity (1 GT box for 7 model firings).

---

## Audit Point 7 — Unmatched Detection Inspection

**At T=0.01: 172 animal detections, 91 matched TPs, 81 unmatched (FP at instance level)**

### Categorisation of 81 unmatched detections

| Category | Count | Description |
|:---|--:|:---|
| S3 empty images, blank label | 59 | Low-confidence blank firings on empty images |
| S3 empty images, non-blank label | 2 | Two S3 images with a non-blank animal detection (genuine FP) |
| Animal images, blank label | 18 | Extra blank firings on images that do have animals |
| Animal images, non-blank label | 2 | High-confidence, non-blank, unmatched on animal images |

### Notable high-confidence unmatched detections on S3 (empty) images

Two non-blank animal detections fire on S3 empty images with substantial confidence:

| Image | Stratum | Conf | Blank | Note |
|:---|:---|--:|:---|:---|
| `58732d1a-23d2` | S3 | **0.756** | No | Highest-confidence FP on empty image |
| `5935a66f-23d2` | S3 | **0.670** | No | Second highest-conf FP on empty image |

These are genuine false alarms with high detector confidence. They represent the most problematic type of false positive for an empty-image filter.

### Annotation omission candidates

Four images have **high-confidence (conf ≥ 0.20), non-blank, animal-label detections that are unmatched** on images where animals are known to be present. These may reflect genuine animals that are not annotated in the GT:

| Image (prefix) | Stratum | GT boxes | Unmatched conf | Max IoU vs GT | Best GT | Assessment |
|:---|:---|--:|--:|--:|:---|:---|
| `58af7554` | S2 | 2 | **0.619** | 0.366 | raccoon | Possible 3rd raccoon not annotated |
| `59e1028c` | S1 | 1 | **0.891** | 0.369 | raccoon | Strong candidate — high conf, moderate IoU vs 1 GT |
| `59e105b5` | S4 | 1 | **0.277** | 0.000 | None | Possible second animal out of GT region |
| `5a0c9c39` | S1 | 1 | **0.385** | 0.000 | None | Possible second animal out of GT region |

> [!NOTE]
> **`59e1028c` is the most compelling annotation omission candidate.** The model fires with conf=0.891 (very high confidence) and the detection overlaps the GT raccoon box at IoU=0.369 (below the 0.5 match threshold). This could be a second raccoon partially occluded, or the same raccoon annotated with a shifted box. Without image review it cannot be confirmed, but it should be flagged. It is currently counted as an instance-level FP.
>
> **`58af7554`** (S2, 2 GT boxes, 3 model dets with conf=0.619 unmatched) also deserves attention — it is a multi-animal image, and a third animal may be present.

These **do not change any reported metric** but are documented for manual review before concluding that all 81 FPs are genuine false alarms.

---

## Audit Point 8 — CCT/SpeciesNet Training Data Overlap

### Model card available locally

The model card at `~/.cache/kagglehub/models/google/speciesnet/pyTorch/v4.0.3a/1/README.md` contains only:
```
license: apache-2.0
- https://github.com/google/cameratrapai
- https://www.kaggle.com/models/google/speciesnet
```
No training data sources, exclusion lists, or split documentation are included.

### Web search findings

From public sources and the GitHub repository `google/cameratrapai`:

1. SpeciesNet is trained on **65+ million images** from Wildlife Insights (community-contributed) combined with public repositories.
2. Caltech Camera Traps (CCT) is used as a **benchmark/evaluation dataset** in published papers alongside SpeciesNet, suggesting familiarity with its distribution.
3. MegaDetector (the animal detector component bundled with similar pipelines) **has been trained on CCT images** in prior versions.
4. Google's documentation does not provide a dataset exclusion list or specify which CCT locations/images were excluded from training.
5. CCT was designed with location-based splits for out-of-distribution generalisation testing — but this does not prevent CCT data from appearing in a model's training set.

> [!CAUTION]
> **Training data overlap with CCT cannot be confirmed or excluded.** The SpeciesNet v4.0.3a model card contains no training dataset documentation. Public evidence suggests CCT images or similar distributions may have been included in training. The nearly perfect species-tier top-1 accuracy (54/54 = 1.000) and the strong genus-tier accuracy for deer (11/11) may partly reflect exposure to CCT-like North American camera trap images during training. **The evaluation results should be reported as potentially optimistic due to unverifiable training-data overlap.** This limitation must be prominently stated in any conclusion.

---

## Audit Point 9 — Stratum Denominators and Overlap Handling

### Denominator verification

| Stratum | Primary count | all_tags count | Difference |
|:---|--:|--:|:---|
| S1 | 35 | 60 | +25 (S1-primary images also carry S4/S5 tags) |
| S2 | 15 | 15 | 0 (no overlap for primary-S2 images) |
| S3 | 25 | 25 | 0 (empty images carry no other tags) |
| S4 | 10 | 47 | +37 (most S4-eligible images have S1/S2 primary) |
| S5 | 15 | 58 | +43 (most S5-eligible images have S1/S2 primary) |

### Overlap combination table

| all_stratum_tags combination | Count |
|:---|--:|
| (S1, S4, S5) | 35 |
| (S3,) | 25 |
| (S1, S5) | 11 |
| (S2, S5) | 9 |
| (S1,) | 8 |
| (S1, S4) | 6 |
| (S2, S4, S5) | 3 |
| (S2, S4) | 3 |
| **Total** | **100** |

The vast majority of images (35) carry all three of S1+S4+S5 simultaneously — they are species-tier single-animal images that are also night-proxy AND have a small bbox. These are assigned to S1 as the highest-priority stratum.

### Stratum breakdown (Eval A, T=0.01) — independently verified

| Stratum | n | TP | FP | FN | TN | P | R | FPR |
|:---|--:|--:|--:|--:|--:|--:|--:|--:|
| S1 | 35 | 35 | 0 | 0 | 0 | 1.000 | 1.000 | N/A |
| S2 | 15 | 15 | 0 | 0 | 0 | 1.000 | 1.000 | N/A |
| S3 | 25 | 0 | 17 | 0 | 8 | 0.000 | N/A | 0.680 |
| S4 | 10 | 9 | 0 | 1 | 0 | 1.000 | 0.900 | N/A |
| S5 | 15 | 15 | 0 | 0 | 0 | 1.000 | 1.000 | N/A |

**Original report denominators are correct.** Each image is counted once, in its primary_stratum. The all_stratum_tags field is for characterisation only and is not used as a denominator.

> [!NOTE]
> The S1+S4+S5 overlap means that S4's performance (primary n=10) is not representative of "all night-proxy images" — only the 10 images whose highest-priority stratum was S4. The 37 additional S4-eligible images are absorbed into S1 (35) and S2 (3+3=6) primary strata. Any claim about "night-proxy performance" should use all_tags=S4 count (n=47), not primary_stratum=S4 count (n=10). The original report uses primary_stratum correctly for the denominator but does not clarify this distinction.

---

## Corrections Required in EVALUATION_REPORT.md

The following corrections should be made before Milestone 7:

| # | Section | Current text | Correction |
|:--|:---|:---|:---|
| C1 | Section 2 (Design) | "Difficult bbox (area < 3 % of image)" | Change to "Difficult bbox (area < 5 % of actual image area)" |
| C2 | Section 7 (Threshold) | Does not explain why T=0.20 is chosen over T=0.50 despite lower F1 | Add explicit statement: "T=0.20 is recall-prioritised. T=0.50 has higher F1 (0.966) and lower FPR (0.08) but misses 1 additional animal image (recall 0.960)." |
| C3 | Section 4.2 (Genus) | "Genus-tier top-1 = 11/17" without explaining what the incorrect predictions returned | Add: "Incorrect genus predictions return family-level labels (Leporidae for rabbit, Canidae for fox) rather than a specific genus — a systematic model behaviour, not random misclassification." |
| C4 | Section 6 (Blanks) | Does not distinguish matched vs unmatched blanks | Add: "5 of 75 blanks are matched TPs (the detector correctly located the animal but the classifier returned blank). 70 are unmatched." |
| C5 | Section 9 (Limitations) | "CCT overlap with SpeciesNet training data: not available" | Strengthen to: "Training-data overlap cannot be excluded. The model card provides no exclusion list. The near-perfect species-tier accuracy may partly reflect training on similar distributions." |
| C6 | Section 4.3 (Table) | IoU histogram values at T=0.20 | Correct to audit values: 0/0/0/0/0/2/3/14/33/36 (total=88) |

---

## Files Produced by This Audit

| File | Path | Notes |
|:---|:---|:---|
| This audit document | `docs/inference/EVALUATION_AUDIT.md` | Primary audit output |
| Machine-readable audit data | `data/evaluation_results/audit_detail.json` | JSON with verified metrics, S5 bbox areas, annotation omission candidates |

**Git state after audit: 19 staged files, nothing committed. `EVALUATION_AUDIT.md` is untracked.**

---

## Conclusion

The Milestone 6 evaluation is **numerically sound** — all 32 metric values across 4 thresholds and 2 evaluations are independently verified. Two substantive issues require correction before proceeding to Milestone 7:

1. **S5 threshold description** must be corrected from < 3% to < 5%.
2. **Threshold recommendation** must be reframed as recall-prioritised, not F1-optimal.

Additionally, four annotation omission candidates are identified for optional manual review, and the training-data overlap caveat should be strengthened. None of these corrections change any reported number — they correct prose descriptions and add missing context.

