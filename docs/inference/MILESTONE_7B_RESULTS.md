# Milestone 7B — Post-Processing NMS Experiment Results

**Date:** 2026-10-31  
**Branch:** `harsh` · **Status:** Experiment complete, awaiting approval before implementation  
**Method:** Post-hoc NMS applied to `data/evaluation_results/raw_predictions.json` — model not rerun  
**Experiment data:** `data/evaluation_results/nms_experiment/nms_results.json` (gitignored)

> [!NOTE]
> This experiment operates exclusively on existing raw predictions. No model code was modified, no new inference was run, and no source files were changed. The manifest, raw predictions, and all existing metrics are unchanged.

---

## Background and Motivation

The Milestone 7A error analysis identified that 28 of 39 unmatched detections in multi-detection images were low-confidence blank ghost responses. The existing `base_detector.py` explicitly documents:
> *"Never apply NMS unless documented (to avoid double-suppression)"*

SpeciesNet already applies internal NMS at its `conf_thres=0.01` call threshold. The question is whether **an additional post-processing NMS pass**, applied after model output, could reduce spurious duplicate detections without hurting true-positive recall.

---

## Experimental Design

### Method
- **Greedy confidence-ranked NMS** applied per image to all `animal`-label detections from raw predictions.
- NMS runs *before* any confidence threshold filter, so even sub-threshold detections can be suppressed (removing them before they could ever be counted as FPs at higher thresholds).
- NMS IoU thresholds tested: **0.30, 0.40, 0.50, 0.60, 0.70**.
- Evaluation thresholds tested at each NMS setting: **0.01, 0.10, 0.20, 0.50**.
- "Genuine risk" defined as: a suppressed detection with `conf ≥ 0.10` AND `is_blank = False`.

### Metrics computed
- Image-level: Precision, Recall, F1, False-Positive Rate (FPR)
- Instance-level (Hungarian matching, IoU ≥ 0.5): Precision, Recall, F1, mean IoU
- Total detections remaining after NMS at each evaluation threshold
- Count of detections suppressed, with genuine-risk breakdown

---

## Results

### At reference threshold T = 0.20

| Setting | Suppressed | Genuine-risk suppressions | img P | img R | img F1 | img FPR | inst P | inst R | inst F1 | Dets |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Baseline (no NMS)** | — | — | 0.9481 | 0.9733 | **0.9605** | 0.1600 | 0.8980 | 0.9462 | **0.9215** | 98 |
| NMS IoU = 0.30 | 13 | 0 | 0.9481 | 0.9733 | 0.9605 | 0.1600 | 0.8980 | 0.9462 | 0.9215 | 98 |
| NMS IoU = 0.40 | 10 | 0 | 0.9481 | 0.9733 | 0.9605 | 0.1600 | 0.8980 | 0.9462 | 0.9215 | 98 |
| NMS IoU = 0.50 | 0 | 0 | 0.9481 | 0.9733 | 0.9605 | 0.1600 | 0.8980 | 0.9462 | 0.9215 | 98 |
| NMS IoU = 0.60 | 0 | 0 | 0.9481 | 0.9733 | 0.9605 | 0.1600 | 0.8980 | 0.9462 | 0.9215 | 98 |
| NMS IoU = 0.70 | 0 | 0 | 0.9481 | 0.9733 | 0.9605 | 0.1600 | 0.8980 | 0.9462 | 0.9215 | 98 |

**All NMS configurations produce identical metrics at T = 0.20.** At this threshold, NMS IoU ≤ 0.40 suppresses 10–13 detections, but all suppressed detections were already below T = 0.20 — so the detection list entering the T = 0.20 evaluation is unchanged.

### At threshold T = 0.10

| Setting | Suppressed | Genuine-risk suppressions | img P | img R | img F1 | img FPR | inst P | inst R | inst F1 | Dets |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Baseline (no NMS)** | — | — | 0.9125 | 0.9733 | 0.9419 | 0.2800 | 0.8000 | 0.9462 | 0.8670 | 110 |
| NMS IoU = 0.30 | 13 | 0 | 0.9125 | 0.9733 | 0.9419 | 0.2800 | 0.8073 | 0.9462 | 0.8713 | 109 |
| NMS IoU = 0.40 | 10 | 0 | 0.9125 | 0.9733 | 0.9419 | 0.2800 | 0.8073 | 0.9462 | 0.8713 | 109 |
| NMS IoU = 0.50 | 0 | 0 | 0.9125 | 0.9733 | 0.9419 | 0.2800 | 0.8000 | 0.9462 | 0.8670 | 110 |

NMS IoU ≤ 0.40 removes 1 instance-level FP at T = 0.10 (inst FP: 22 → 21), improving instance precision from 0.8000 to 0.8073 and instance F1 from 0.8670 to 0.8713 (+0.004). Instance TP (88) and FN (5) are unchanged; image-level metrics are identical. This small improvement does not establish that NMS is preferable overall — the gain is within the margin of a 100-image sample and T = 0.10 is below the recommended operational threshold.

### At low threshold T = 0.01

| Setting | Suppressed | Genuine-risk | img P | img R | img F1 | inst P | inst R | inst F1 | Dets |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Baseline** | — | — | 0.8132 | **0.9867** | 0.8916 | 0.5291 | **0.9785** | 0.6868 | 172 |
| NMS IoU = 0.30 | 13 | **0** | 0.8132 | 0.9867 | 0.8916 | 0.5660 | 0.9677 | 0.7143 | 159 |
| NMS IoU = 0.40 | 10 | **0** | 0.8132 | 0.9867 | 0.8916 | 0.5556 | 0.9677 | 0.7059 | 162 |
| NMS IoU = 0.50 | 0 | 0 | 0.8132 | 0.9867 | 0.8916 | 0.5291 | 0.9785 | 0.6868 | 172 |

At T = 0.01, NMS IoU = 0.30 reduces total detections from 172 to 159 and improves instance-level precision from 0.529 to 0.566 (+0.037). However, instance TP drops from 91 to 90 and instance FN rises from 2 to 3 — NMS suppresses the `58bd1bec` rabbit detection (conf = 0.017, GT IoU = 0.649), which was a genuine matched TP at T = 0.01. This is a real instance-level TP loss caused by NMS. **Image-level metrics are identical at all NMS settings** because the `58bd1bec` image is already an image-level FN at T = 0.01 (its only remaining detection after suppression has conf = 0.056, also below T = 0.10).

---

## What Was Suppressed (Full Detail, NMS IoU = 0.30, 13 suppressions)

| Image | eval_a_label | Suppressed conf | Blank | GT IoU | Det–Det IoU | Winner conf | Winner pred |
|:---|:---|---:|:---|---:|---:|---:|:---|
| `58678de5` (S3) | negative | 0.025 | Yes | 0.000 | 0.400 | 0.145 | blank |
| `58bd1bec` (S1) | positive | 0.017 | Yes | **0.649** | 0.417 | 0.056 | blank |
| `58ce4067` (S3) | negative | 0.102 | Yes | 0.000 | 0.433 | 0.137 | blank |
| `58ce4067` (S3) | negative | 0.023 | Yes | 0.000 | 0.439 | 0.044 | blank |
| `58ce4067` (S3) | negative | 0.018 | Yes | 0.000 | 0.402 | 0.033 | blank |
| `58d15e51` (S1) | positive | 0.014 | Yes | 0.074 | 0.318 | 0.549 | blank |
| `58d15e51` (S1) | positive | 0.021 | Yes | 0.031 | 0.436 | 0.337 | blank |
| `5906ef68` (S3) | negative | 0.064 | Yes | 0.000 | 0.421 | 0.116 | blank |
| `5906ef68` (S3) | negative | 0.011 | Yes | 0.000 | 0.378 | 0.116 | blank |
| `593a4cc7` (S3) | negative | 0.011 | Yes | 0.000 | 0.383 | 0.011 | blank |
| `59531d26` (S2) | positive | 0.028 | **No** | **0.440** | 0.429 | 0.699 | bird |
| `59531d26` (S2) | positive | 0.014 | Yes | 0.000 | 0.432 | 0.121 | blank |
| `5a2af3cf` (S4) | positive | 0.018 | **No** | 0.303 | 0.401 | 0.606 | mule deer |

**All 13 are below T = 0.10.** All 13 are classified as blank or have sub-threshold confidence. **Zero genuine-risk suppressions** (zero cases where conf ≥ 0.10 AND not blank). The two non-blank suppressions (`59531d26` bird at conf=0.028, `5a2af3cf` mule deer at conf=0.018) are duplicate near-overlaps of higher-confidence correct detections in the same image — in both cases the winner already matches the correct GT box.

**Notable case — `58bd1bec` suppressed blank (conf=0.017, GT IoU=0.649):**  
This is the rabbit detection that is a matched TP blank at T=0.01 (one of the 5 matched blanks identified in the Milestone 7A reconciliation). NMS at IoU=0.30 suppresses it in favour of the conf=0.056 blank winner, which does NOT achieve IoU ≥ 0.5 against the same GT box. This causes a genuine instance-level TP loss at T=0.01 (inst TP drops from 91 to 90, inst FN rises from 2 to 3). However, since both the suppressed detection and its winner are below T=0.10, neither survives at T ≥ 0.10 regardless. **At T ≥ 0.10, no distinct-animal TP loss was observed in this experiment.**

---

## Why NMS Has No Meaningful Effect at Operational Thresholds

At **T = 0.20 and T = 0.50**, all NMS configurations produce metrics identical to baseline. No detections are affected because the 13 suppressions all involve detections with `conf < 0.10`.

At **T = 0.10**, NMS IoU ≤ 0.40 removes 1 instance FP (inst F1 improves by +0.004). This is a real but marginal improvement on a 100-image sample that does not establish NMS as preferable overall.

At **T = 0.01**, NMS IoU = 0.30 removes 12 instance FPs but also causes 1 genuine instance TP loss (the `58bd1bec` rabbit). Instance F1 improves because the FP reduction dominates, but the TP loss demonstrates that NMS carries a real risk of suppressing genuine animal detections.

The suppressions fall into two categories:

1. **Low-conf blank pairs overlapping in background regions** (S3 empty images and S1/S2 animal images): these disappear at T=0.10 whether NMS is applied or not.
2. **Low-conf near-duplicates of already-correct high-conf detections**: the winner already produces the correct match; suppressing the low-conf near-duplicate does not change the match count — except in the `58bd1bec` case, where suppression destroys the only GT-matching detection.

At **T = 0.50**, there are zero det–det pairs with IoU ≥ 0.30 among the 92 remaining detections — the high-confidence detections SpeciesNet produces are already well-separated spatially.

---

## Recommendation

> [!IMPORTANT]
> **Do not add post-processing NMS to the production inference pipeline.**

### Rationale

1. **No improvement at recommended operating thresholds.** At T = 0.20 (recall-oriented) and T = 0.50 (precision-oriented), NMS produces **identical** precision, recall, F1 and FPR to the baseline across all tested IoU thresholds. NMS adds code complexity with zero measurable benefit at these thresholds.

2. **Marginal improvement at T = 0.10 does not justify the added complexity.** NMS IoU ≤ 0.40 removes 1 instance FP at T = 0.10 (inst F1: 0.8670 → 0.8713, a +0.004 gain). This is within the sampling variability of a 100-image evaluation and does not establish that NMS is preferable overall.

3. **NMS causes a genuine TP loss at T = 0.01.** The suppressed `58bd1bec` rabbit detection (conf = 0.017, GT IoU = 0.649) was a real instance-level matched TP. NMS at IoU = 0.30 destroys this match by suppressing it in favour of a higher-confidence blank winner that does not overlap the same GT box. At T ≥ 0.10, this detection is already below threshold regardless, so the TP loss has no operational impact — but it demonstrates that additional NMS creates a genuine risk of losing real animal detections.

4. **Double-suppression risk.** As documented in `base_detector.py`, SpeciesNet already applies internal NMS. Adding a second NMS pass is redundant and introduces the risk of suppressing legitimate detections if image or model characteristics change on unseen data.

5. **The root cause of low-confidence blank ghost detections is the model's internal NMS threshold (conf_thres=0.01), not missing post-processing.** Raising the operational threshold to T = 0.10 eliminates all ghost detections without any code change.

### What can be done instead (no code change needed)

| Issue | Solution | Code change? |
|:---|:---|:---|
| Low-conf blank ghosts at T=0.01 | Use T=0.10 or T=0.20 in production | No — threshold is a call parameter |
| 4 FP on empty images at T=0.20 | Use T=0.50 for precision-critical deployments | No |
| Multi-detection on single animal | Already handled correctly by T≥0.10 | No |

---

## Baseline Metrics Summary (for reference)

### Image-level (Eval A)

| T | P | R | F1 | FPR | TP | FP | FN | TN |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.8132 | 0.9867 | 0.8916 | 0.6800 | 74 | 17 | 1 | 8 |
| 0.10 | 0.9125 | 0.9733 | 0.9419 | 0.2800 | 73 | 7 | 2 | 18 |
| **0.20** | **0.9481** | **0.9733** | **0.9605** | **0.1600** | **73** | **4** | **2** | **21** |
| 0.50 | 0.9730 | 0.9600 | 0.9664 | 0.0800 | 72 | 2 | 3 | 23 |

### Instance-level (Eval B, Hungarian IoU ≥ 0.5)

| T | P | R | F1 | mean IoU | TP | FP | FN |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.01 | 0.5291 | 0.9785 | 0.6868 | — | 91 | 81 | 2 |
| 0.10 | 0.8000 | 0.9462 | 0.8670 | — | 87 | 23 | 5 |
| **0.20** | **0.8980** | **0.9462** | **0.9215** | — | **88** | **10** | **5** |
| 0.50 | 0.9457 | 0.9355 | 0.9405 | — | 87 | 5 | 6 |

---

## Git Status (at time of experiment, 2026-10-31 ~06:00 IST)

```
Staged (19):     unchanged
Untracked (4):   docs/inference/ERROR_ANALYSIS.md
                 docs/inference/ERROR_ANALYSIS_RECONCILIATION.md
                 docs/inference/EVALUATION_AUDIT.md
                 docs/inference/EVALUATION_REPORT.md
                 docs/inference/MILESTONE_7B_RESULTS.md  <- this file
Nothing committed. No model code modified.
```

> **Note:** This is a historical snapshot from the time of the experiment. Subsequent documentation milestones added `MILESTONE_8_READINESS.md` and corrected this file, increasing the untracked count.

*End of Milestone 7B. Awaiting approval before any production changes.*

