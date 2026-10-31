# WILDSCOPE Wildlife Inference — Evaluation Report

**Project:** WILDSCOPE — Camera-trap inference system  
**Team:** ByteStrom (HFT26-TEAM-8)  
**Model:** SpeciesNet v4.0.3a (`google/speciesnet/pyTorch/v4.0.3a/1`)  
**Dataset:** Caltech Camera Traps (CCT) — validation split  
**Evaluation date:** 2026-10-31  
**Device:** NVIDIA RTX 4050 Laptop GPU (CUDA 12.8)  
**Evaluation images:** 100 held-out CCT val-split images (SHA-256 of sorted IDs: `ad8d7bc792cd6631e9a3dff675fd4a76b3022a1fc0ca142692b4a1ef15c3fdea`)  
**Evaluation script:** `brain/.../scratch/compute_metrics.py`  
**Outputs:** `data/evaluation_results/metrics_summary.json`, `data/evaluation_results/metrics_detail.json`

---

## 1. Executive Summary

SpeciesNet v4.0.3a achieves **strong animal detection** on Caltech Camera Trap images when the
detector confidence threshold is tuned appropriately.

- At **T = 0.20**, image-level precision = 0.948, recall = 0.973, F1 = 0.961, FPR = 0.160.
  This threshold prioritises recall: it recovers the same number of animal images as T = 0.10
  while producing fewer empty-image false alarms (4 vs 7). **T = 0.50** achieves higher F1
  (0.966) and lower FPR (0.080) at the cost of missing one additional animal image. Neither
  threshold is universally optimal; see Section 8 for the full trade-off.
- **Species-tier classification** is perfect on this sample: top-1 accuracy = 54/54 = 1.000 at
  T = 0.01 (53/53 at T = 0.20) for the five supported CCT species.
- **Genus-tier classification** is lower: top-1 = 11/17 = 0.647, top-5 = 16/17 = 0.941.
  Deer is correctly classified at genus level (11/11). Rabbit and fox predictions return
  family-level labels (`Leporidae`, `Canidae`) rather than genus-level labels — a systematic
  model behaviour, not random misclassification.
- **Empty-image FPR** is high at T = 0.01 (0.680) and drops substantially at T = 0.10 (0.280)
  and T = 0.20 (0.160).
- **Instance-level precision** is substantially lower than image-level precision at all thresholds
  because the model frequently produces 2–7 detections per image where CCT supplies only 1 GT
  bounding box annotation. This reflects known camera-trap annotation sparsity.
- **43.1% of all 174 detections are blank** (label `;;;;;;blank`). Of these, 5 matched a GT
  bounding box at IoU ≥ 0.5 (correct location, blank classification); 70 were fully unmatched.

> **Scope statement:** Species accuracy applies only to 5 species-tier + 3 genus-tier CCT
> categories from the Caltech val split. Results must NOT be described as general wildlife
> accuracy. Species and genus accuracy are always reported separately and never combined.

---

## 2. Dataset and Evaluation Design

### 2.1 Sampling

| Field | Value |
|:---|:---|
| Dataset | Caltech Camera Traps — CCT val split |
| Seed | 42 |
| Priority order | S2 → S5 → S4 → S1 → S3 |
| Total images | 100 |
| Empty images (Eval A negative) | 25 (S3) |
| Animal images (Eval A positive) | 75 (S1+S2+S4+S5) |
| Images with usable GT bboxes | 57 unique images |
| Total GT animal bbox annotations | 93 (excluding cat-id 30 trigger regions) |

### 2.2 Strata

| Stratum | Description | n |
|:---|:---|:---|
| S1 | Species-tier animals (5 supported species) | 35 |
| S2 | Multi-animal (≥ 2 GT boxes per image) | 15 |
| S3 | Empty (negative) | 25 |
| S4 | Night-proxy (hour ≥ 20 or < 6) | 10 |
| S5 | Difficult bbox (area < 5 % of actual image area, using per-image dimensions) | 15 |

### 2.3 Taxonomy tiers

| Tier | Category IDs | Categories | In sample |
|:---|:---|:---|:---|
| Species | 1, 3, 6, 7, 9 | opossum, raccoon, bobcat, skunk, coyote | All 5 |
| Genus | 5, 10, 14, 34, 51 | squirrel, rabbit, lizard, deer, fox | 3 (deer, rabbit, fox) |
| Excluded | 8, 11, 16, 21, 33, 99 | dog, bird, cat, badger, car, rodent | dog, bird, cat |

---

## 3. Evaluation A — Image-Level Detection

**Definition:** An image is "detected" if at least one animal detection with `detector_conf ≥ T`
exists. S3 images are negative; all other images are positive. Car-only / excluded-only images
not present in this sample.

| Threshold | Precision | Recall | F1 | FPR | TP | FP | FN | TN |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| T = 0.01 | 0.813 | 0.987 | 0.892 | 0.680 | 74 | 17 | 1 | 8 |
| T = 0.10 | 0.912 | 0.973 | 0.942 | 0.280 | 73 | 7 | 2 | 18 |
| **T = 0.20** | **0.948** | **0.973** | **0.961** | **0.160** | **73** | **4** | **2** | **21** |
| T = 0.50 | 0.973 | 0.960 | 0.966 | 0.080 | 72 | 2 | 3 | 23 |

- **n_positive = 75, n_negative = 25**
- At T = 0.01 the model misses only 1 animal image (FN = 1) but raises 17 false alarms on empty
  images (68% of empty images trigger at least one low-confidence detection).
- At T = 0.20 only 4 empty images trigger alarms, with no additional recall loss beyond the 2
  images already missed at T = 0.10.
- At T = 0.50 three animal images are missed. T = 0.50 achieves the highest image-level F1
  (0.966) and lowest FPR (0.080) in this evaluation; whether this or a lower threshold is
  preferable depends on the operating context (see Section 8).

---

## 4. Evaluation B — Instance-Level Detection (Hungarian IoU ≥ 0.5)

**Definition:** Predicted and GT boxes are matched using the Hungarian algorithm maximising IoU;
a prediction is a TP only if matched IoU ≥ 0.5. Unmatched predictions are FP; unmatched GT
boxes are FN. Category 30 trigger-region annotations are excluded.

| Threshold | Precision | Recall | F1 | Mean IoU | TP | FP | FN |
|---:|---:|---:|---:|---:|---:|---:|---:|
| T = 0.01 | 0.529 | 0.978 | 0.687 | 0.8552 | 91 | 81 | 2 |
| T = 0.10 | 0.800 | 0.946 | 0.867 | 0.8600 | 88 | 22 | 5 |
| **T = 0.20** | **0.898** | **0.946** | **0.921** | **0.8600** | **88** | **10** | **5** |
| T = 0.50 | 0.946 | 0.935 | 0.941 | 0.8607 | 87 | 5 | 6 |

- **Total GT animal bbox annotations: 93. Total model detections at T = 0.01: 172.**
- The model often produces multiple overlapping detections per animal (2–7 per image on 13 S1
  images) because CCT annotates at most one box per image per animal. These extra detections count
  as FP even if they correctly locate the same animal.
- Mean IoU for matched TPs is consistently ~0.86 across all thresholds, indicating the model
  localises matched animals accurately.
- At T = 0.20, instance precision reaches 0.898 with only a 0.03-point recall drop relative to
  T = 0.01.

### 4.1 IoU Distribution for Matched Detections (T = 0.20)

| IoU range | Count | % |
|:---|---:|---:|
| 0.0 – 0.1 | 0 | 0.0% |
| 0.1 – 0.2 | 0 | 0.0% |
| 0.2 – 0.3 | 0 | 0.0% |
| 0.3 – 0.4 | 0 | 0.0% |
| 0.4 – 0.5 | 0 | 0.0% |
| 0.5 – 0.6 | 2 | 2.3% |
| 0.6 – 0.7 | 3 | 3.4% |
| 0.7 – 0.8 | 14 | 15.9% |
| 0.8 – 0.9 | 33 | 37.5% |
| 0.9 – 1.0 | 36 | 40.9% |

All matched TPs have IoU ≥ 0.5 by definition. The distribution skews strongly toward high IoU
(0.8+), with 69/88 (78.4%) of matches having IoU ≥ 0.8. Counts are independently audited
(see `docs/inference/EVALUATION_AUDIT.md`, Point 2).

---

## 5. Classification Accuracy

Classification is evaluated on **matched TPs** from Eval B. Results are reported at both
T = 0.01 (maximum-recall population) and T = 0.20 (recommended operating threshold) to show
how the evaluated population changes with threshold. Species-tier and genus-tier results are
reported **separately** and never combined.

Blank detections (label `;;;;;;blank`) are excluded from the classification denominator.
Of 75 total blank detections, **5 matched a GT bounding box at IoU ≥ 0.5** — meaning the
detector correctly located the animal but the classifier returned blank. The remaining 70 blanks
were unmatched (no GT box overlap). Matched blanks contribute to instance-level TP counts in
Eval B but produce 0 correct top-1 classifications.

### 5.1 Species-Tier (Categories 1, 3, 6, 7, 9)

| Metric | T = 0.01 | T = 0.20 |
|:---|---:|---:|
| Matched TPs | 54 | 53 |
| Blank (excluded from denominator) | 0 | 0 |
| Eligible | 54 | 53 |
| Top-1 correct | **54 / 54 = 1.000** | **53 / 53 = 1.000** |
| Top-5 correct | **54 / 54 = 1.000** | **53 / 53 = 1.000** |

The model achieves perfect top-1 and top-5 accuracy on all 5 supported species at both
thresholds. The population difference (54 vs 53) reflects one low-confidence raccoon match
that falls below T = 0.20.

### 5.2 Genus-Tier (Categories 10, 34, 51)

| Metric | T = 0.01 | T = 0.20 |
|:---|---:|---:|
| Matched TPs | 18 | 17 |
| Blank (excluded from denominator) | 1 | 0 |
| Eligible | 17 | 17 |
| Top-1 correct | **11 / 17 = 0.647** | **11 / 17 = 0.647** |
| Top-5 correct | **16 / 17 = 0.941** | **16 / 17 = 0.941** |

- Genus-tier matching uses the genus segment of the semicolon-delimited SpeciesNet label
  (`uuid;class;order;family;genus;species;common_name`, segment index 4).
- All 11 deer matches are correct (genus `odocoileus`). Deer is the only genus-tier category
  with reliable top-1 classification on this sample.
- The 6 incorrect genus predictions (5 rabbit, 1 fox) are not random misclassifications.
  SpeciesNet returns **family-level labels** for these: rabbit GT images receive the prediction
  `Leporidae` ("rabbit and hare family") and fox GT images receive `Canidae` ("canine family").
  In both cases the genus segment (label index 4) is empty — the model hedges at family level
  rather than committing to a specific genus. This is a systematic behaviour when the model is
  uncertain between multiple genera within a family.
- Top-5 results show that the correct genus appears among the top-5 candidates for 5 of the
  6 incorrect top-1 cases (rabbit: 4/5; fox: 0/1 at top-5).

### 5.3 Per-Category Breakdown

Results at T = 0.01; T = 0.20 counts shown where they differ.

| Category | Tier | n (T=0.01) | n (T=0.20) | Blank | Eligible | Top-1 acc |
|:---|:---|---:|---:|---:|---:|---:|
| opossum | species | 14 | 14 | 0 | 14 | 1.000 |
| raccoon | species | 21 | 20 | 0 | 20–21 | 1.000 |
| bobcat | species | 9 | 9 | 0 | 9 | 1.000 |
| coyote | species | 8 | 8 | 0 | 8 | 1.000 |
| skunk | species | 2 | 2 | 0 | 2 | 1.000 |
| deer | genus | 11 | 11 | 0 | 11 | 1.000 |
| rabbit | genus | 6 | 5 | 1 (T=0.01) | 5 | 0.000 ¹ |
| fox | genus | 1 | 1 | 0 | 1 | 0.000 ¹ |
| bird | excluded | 10 | 9 | 4 (T=0.01) | — | — |
| dog | excluded | 7 | 7 | 0 | — | — |
| cat | excluded | 2 | 2 | 0 | — | — |

¹ Sample sizes (rabbit n=5, fox n=1) are too small for a reliable accuracy estimate.
Rabbit top-5 = 4/5 = 0.800. Fox top-5 = 0/1 = 0.000.

---

## 6. Blank Classification Analysis

**75 of 174 total detections (43.1%) carry the blank label**  
(`f1856211-cfb7-4a5b-9158-c0f72fd09ee6;;;;;;blank`)

Of the 75 blank detections:
- **5** matched a GT bounding box at IoU ≥ 0.5 at T = 0.01 (the detector correctly located
  the animal but the classifier returned blank).
- **70** were unmatched (no GT box overlap at IoU ≥ 0.5).

### 6.1 Confidence Distribution of Blank Detections

| Detector confidence | Count |
|:---|---:|
| < 0.05 | 50 |
| 0.05 – 0.10 | 7 |
| 0.10 – 0.20 | 11 |
| 0.20 – 0.50 | 3 |
| ≥ 0.50 | 4 |

57/75 blanks (76%) have detector_conf < 0.10. Applying T = 0.10 removes most unmatched blanks
from consideration without meaningful recall loss.

### 6.2 Stratum Distribution of Blank Detections

| Stratum | Blank dets |
|:---|---:|
| S3 (empty) | 40 |
| S1 | 18 |
| S2 | 14 |
| S4 | 1 |
| S5 | 2 |

40/75 blanks (53%) arise from S3 empty images — these are the classifier's output on images
with no animals, where the detector still fires at low confidence. The remaining 35 blanks
appear on animal images (S1, S2, S4, S5) as extra low-confidence detections.

### 6.3 Interpretation

- Blanks on S3 images are expected: the detector fires spuriously at T = 0.01, and the
  classifier correctly returns "blank" (no animal).
- Blanks on animal images (35/75, all with GT bbox present) represent extra detector firings on
  background regions or additional animals. These are FP at instance level but do not degrade
  image-level recall.
- Of the 18 blanks on S1-primary images, 16 occur on images that also carry an S4 (night-proxy)
  tag. Because all S1-primary images in this sample carry S4+S5 tags (see Section 7), this
  association is confounded by the sampling design and should not be interpreted as evidence of a
  causal night-time blank effect without controlled comparison.
- The blank label is unambiguous: all 75 blanks share the same UUID and empty taxonomy segments.
  Blank detections must not be counted as wildlife-positive predictions.

---

## 7. Stratum Breakdown (T = 0.01)

| Stratum | n | Eval A P | Eval A R | Eval B P | Eval B R |
|:---|---:|---:|---:|---:|---:|
| S1 | 35 | 1.000 | 1.000 | 0.607 | 0.971 |
| S2 | 15 | 1.000 | 1.000 | 0.733 | 1.000 |
| S3 | 25 | 0.000 | N/A | 0.000 | N/A |
| S4 | 10 | 1.000 | 0.900 | 0.750 | 0.900 |
| S5 | 15 | 1.000 | 1.000 | 0.882 | 1.000 |

- **S3:** All 25 empty images are correctly handled at image-level (label = negative). The 17
  false alarms at T = 0.01 (FPR = 0.680) collapse Eval A precision to 0.000 for S3; at T = 0.20
  only 4 S3 images produce alarms (FPR = 0.160).
- **S4 (night-proxy):** One missed detection at image level (Eval A R = 0.900). "Night-proxy"
  means the image was captured between 20:00–06:00 — this is a temporal proxy, not a radiometric
  darkness measure. **Important:** The S4 primary-stratum row covers only the 10 images whose
  highest-priority stratum assignment was S4. A further 37 images carry the S4 tag but are
  assigned to S1 (35 images) or S2 (2 images) as their primary stratum. The S4 row therefore
  does not represent performance across all 47 S4-tagged images; it represents the subset not
  already captured by S1 or S2.
- **S1/S2/S5 instance precision:** Low Eval B precision on S1 (0.607) and S2 (0.733) reflects
  the annotation-sparsity effect described in Section 4. The model produces multiple valid-looking
  boxes; CCT provides only one GT box per animal.
- **Stratum overlap:** All 35 S1-primary images also carry S4 and S5 tags (they are night-proxy
  single-animal images with a small bounding box). Each image is counted once, in its
  primary stratum. Tag counts (`all_stratum_tags`) are: S1=60, S2=15, S3=25, S4=47, S5=58.

---

## 8. Threshold Selection

No single threshold is optimal across all use cases. The table below summarises the trade-off
across the four evaluated thresholds.

| T | Eval A F1 | Eval A Recall | Eval A FPR | Eval B F1 | Eval B FP |
|--:|--:|--:|--:|--:|--:|
| 0.01 | 0.892 | **0.987** | 0.680 | 0.687 | 81 |
| 0.10 | 0.942 | 0.973 | 0.280 | 0.867 | 22 |
| 0.20 | 0.961 | 0.973 | 0.160 | 0.922 | 10 |
| 0.50 | **0.966** | 0.960 | **0.080** | **0.941** | 5 |

**T = 0.20 — recall-oriented operating point.**  
This threshold matches the recall of T = 0.10 (both recover 73/75 animal images) while
reducing empty-image false alarms from 7 to 4. It is suitable when missing an animal image is
the primary concern and a 16% false-alarm rate on empty images is acceptable.

**T = 0.50 — precision-oriented operating point.**  
T = 0.50 achieves the highest image-level F1 (0.966) and the lowest empty-image FPR (0.080) on
this evaluation sample. It misses 3 animal images (recall = 0.960 vs 0.973 at T = 0.20, a
difference of 1 image). It is preferable when minimising false alarms is the primary criterion
and a small additional miss rate is acceptable.

The choice between T = 0.20 and T = 0.50 is a domain decision. Neither is universally optimal.
Practitioners should select based on the relative cost of missed detections versus false alarms
in their specific deployment context.

---

## 9. Limitations

1. **Sample size:** N = 100 images. Classification counts per category are small (≤ 21
   per species, ≤ 11 per genus). Results are indicative, not statistically conclusive.

2. **Annotation sparsity:** CCT provides at most one GT bbox annotation per image per animal
   instance. Images with multiple real animals may have only one GT box. This inflates
   instance-level FP counts (Eval B) and makes Eval B precision conservative. Two images
   (`59e1028c` and `58af7554`) have high-confidence non-blank model detections that are unmatched
   due to insufficient IoU with the single GT box; these are possible annotation omissions and
   should be reviewed manually before treating all instance-level FPs as false alarms.

3. **Night-proxy limitation:** S4 classification uses timestamp (hour ≥ 20 or < 6) as a proxy
   for low-light conditions. This does not account for image quality, flash type, or infrared
   vs. colour imaging. The S4 primary-stratum row (n=10) does not represent performance across
   all 47 S4-tagged images (see Section 7).

4. **Label format dependency:** Classification matching depends on the semicolon-delimited
   SpeciesNet label format (`uuid;class;order;family;genus;species;common_name`). A change in
   label format in future model versions would require updating the matching logic.

5. **Scope:** Results cover only the 5 species-tier and 3 genus-tier categories represented in
   the CCT val split. They cannot be generalised to other ecosystems, species, or camera-trap
   datasets.

6. **Category 30 exclusion:** CCT category 30 (trigger-region bounding boxes) is correctly
   excluded from all animal-level metrics. If future datasets use different sentinel categories,
   the exclusion list must be updated.

7. **Excluded-tier metrics:** Bird, dog, and cat predictions are logged but not scored. They
   represent 19/91 matched instance-level detections at T = 0.01.

8. **Training-data overlap:** Whether SpeciesNet v4.0.3a was trained on images from the
   Caltech Camera Traps dataset could not be established from available documentation. The model
   card bundled with the downloaded weights (`README.md`) references only the GitHub repository
   and Kaggle model page and contains no training dataset inventory or split exclusion list.
   Public documentation for related Google camera-trap models notes that training data includes
   Wildlife Insights contributions and public repositories; CCT is among the publicly available
   North American camera-trap datasets. A training-data overlap cannot be ruled out, and results
   — particularly the near-perfect species-tier accuracy — may be optimistic if CCT images were
   included in model training. MegaDetector's prior training history is not sufficient evidence
   to conclude that the SpeciesNet classifier was exposed to CCT data.

---

## 10. Files Produced

| File | Location | Size |
|:---|:---|---:|
| Inference raw predictions | `data/evaluation_results/raw_predictions.json` | 289,515 B |
| Metrics summary | `data/evaluation_results/metrics_summary.json` | 8,741 B |
| Metrics detail | `data/evaluation_results/metrics_detail.json` | 379,872 B |
| Evaluation manifest | `data/eval_manifest.json` | — |
| Evaluation images | `data/cct_samples/eval/` | 35.8 MB |

All files under `data/` are gitignored and excluded from version control.

---

## 11. Git State

**19 files staged, nothing committed.**  
The evaluation was conducted without modifying any staged source files, tests, or documentation.
No additional files were staged during this milestone.

```
A  .gitignore
A  .python-version
A  docs/inference/LICENSING.md
A  docs/inference/PROGRESS.md
A  docs/inference/requirements-inference.txt
A  requirements-dev.txt
A  requirements-lock-cuda.txt
A  requirements.txt
A  src/__init__.py
A  src/inference/__init__.py
A  src/inference/base_detector.py
A  src/inference/speciesnet_detector.py
A  src/inference/speciesnet_infer.py
A  tests/__init__.py
A  tests/inference/__init__.py
A  tests/inference/test_cct_3images.py
A  tests/inference/test_speciesnet_infer.py
A  tests/inference/visual_inspection.py
A  tests/inference/visualize_detections.py
```

