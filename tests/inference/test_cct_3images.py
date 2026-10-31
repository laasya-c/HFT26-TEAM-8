"""
WILDSCOPE — CCT 3-image inference test runner
tests/inference/test_cct_3images.py

Runs genuine pretrained SpeciesNet inference on the three verified CCT samples
and prints a complete results report. Not a pytest test — run directly.

Usage:
    .venv\\Scripts\\python.exe tests\\inference\\test_cct_3images.py
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import torch

# Add repo root to path so src.inference is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.inference.speciesnet_detector import SpeciesNetAnimalDetector, DEFAULT_MODEL_NAME
from src.inference.base_detector import DetectionStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Ground-truth metadata (from CCT annotations — NOT fed to the model)
# Used only for post-hoc comparison in the printed report.
# ---------------------------------------------------------------------------
GROUND_TRUTH = {
    "5998cfa4-23d2-11e8-a6a3-ec086b02610b.jpg": {
        "label": "Image A",
        "gt_species": "opossum",
        "gt_bbox_count": 1,
        "gt_bboxes_norm": [[0.24375, 0.476359, 0.1725, 0.133655]],
    },
    "59610788-23d2-11e8-a6a3-ec086b02610b.jpg": {
        "label": "Image B",
        "gt_species": "bird",
        "gt_bbox_count": 9,
        "gt_bboxes_norm": None,   # omitted for brevity
    },
    "5971fa92-23d2-11e8-a6a3-ec086b02610b.jpg": {
        "label": "Image C",
        "gt_species": "empty",
        "gt_bbox_count": 0,
        "gt_bboxes_norm": None,
    },
}

SAMPLES_DIR = REPO_ROOT / "data" / "cct_samples"

IMAGE_FILES = [
    SAMPLES_DIR / "5998cfa4-23d2-11e8-a6a3-ec086b02610b.jpg",   # Image A
    SAMPLES_DIR / "59610788-23d2-11e8-a6a3-ec086b02610b.jpg",   # Image B
    SAMPLES_DIR / "5971fa92-23d2-11e8-a6a3-ec086b02610b.jpg",   # Image C
]


def divider(char="=", n=70):
    print(char * n)


def print_header():
    divider()
    print("WILDSCOPE — SpeciesNet 5.0.5 Inference Test")
    print(f"Model  : {DEFAULT_MODEL_NAME}")
    print(f"CUDA   : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU    : {torch.cuda.get_device_name(0)}")
        free, total = torch.cuda.mem_get_info(0)
        print(f"VRAM   : {total//(1024**2)} MB total  |  {free//(1024**2)} MB free")
    print(f"Images : {len(IMAGE_FILES)}")
    divider()


def print_result(result, gt):
    fname = Path(result.filepath).name
    label = gt.get("label", fname)

    divider("-", 70)
    print(f"{label}  —  {fname}")
    divider("-", 70)
    # DetectionStatus is an Enum; .name gives e.g. "OK", "LOAD_FAILURE"
    print(f"  Status          : {result.status.name}")
    print(f"  Image size      : {result.image_w} x {result.image_h} px")
    print(f"  GT species      : {gt.get('gt_species', '?')}")
    print(f"  GT bbox count   : {gt.get('gt_bbox_count', '?')}")
    print()

    if result.error_message:
        print(f"  ERROR: {result.error_message}")
        return

    # Timing
    print(f"  Timing:")
    print(f"    Image load    : {result.load_time_s*1000:.1f} ms")
    print(f"    Detection     : {result.detect_time_s*1000:.1f} ms  (device={result.detect_device})")
    print(f"    Classification: {result.classify_time_s*1000:.1f} ms  (device={result.classify_device or 'N/A - no animals detected'})")
    print(f"    Image total   : {result.total_time_s*1000:.1f} ms")
    print()

    # Detections — use new Detection field names
    n_det    = len(result.detections)
    n_animal = sum(1 for d in result.detections if d.detector_label == "animal")
    n_other  = n_det - n_animal
    print(f"  Detections      : {n_det} total  ({n_animal} animal, {n_other} non-animal)")
    print()

    if n_det == 0:
        print("  [No detections above threshold — model produced an empty list]")
        print()
        return

    for i, det in enumerate(result.detections):
        x, y, w, h = det.bbox_norm
        print(f"  Detection [{i}]:")
        print(f"    MegaDetector label : {det.detector_label}  (category={det.detector_category})")
        print(f"    Conf score         : {det.detector_conf:.6f}  (NOT a calibrated probability)")
        print(f"    BBox valid         : {det.bbox_valid}")
        print(f"    BBox (normalised)  : x={x:.6f}  y={y:.6f}  w={w:.6f}  h={h:.6f}")
        if det.bbox_valid:
            bx, by, bw, bh = det.bbox_pixels
            print(f"    BBox (pixels)      : x={bx}  y={by}  w={bw}  h={bh}")
        else:
            print(f"    BBox (pixels)      : UNAVAILABLE — invalid geometry (see bbox_norm above)")

        if det.classification.attempted:
            print(f"    Classification     : attempted (device={result.classify_device})")
            if det.classification.top_labels:
                print(f"    Top-5 species      :")
                for rank, (cls, score) in enumerate(
                    zip(det.classification.top_labels, det.classification.top_scores), 1
                ):
                    print(f"      #{rank}: {cls:<55} score={score:.6f}")
            else:
                print("    Top-5 species      : [empty — classifier returned no results]")
        else:
            print(f"    Classification     : skipped (label='{det.detector_label}', not an animal)")
        print()


def main():
    print_header()

    # Verify all images exist before starting model loading
    missing = [p for p in IMAGE_FILES if not p.exists()]
    if missing:
        print("ABORT: missing image files:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)

    print()
    print("Loading SpeciesNet models (downloading weights if not cached)...")
    print("This may take several minutes on first run.")
    print()

    # Reset VRAM stats before inference
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    t_total = time.perf_counter()
    detector = SpeciesNetAnimalDetector(model_name=DEFAULT_MODEL_NAME)
    results  = detector.detect_batch(IMAGE_FILES)
    total_elapsed = time.perf_counter() - t_total

    print()
    divider()
    print("RESULTS")
    divider()

    for result in results:
        fname = Path(result.filepath).name
        gt = GROUND_TRUTH.get(fname, {})
        print_result(result, gt)

    # Summary
    divider()
    print("SUMMARY")
    divider()
    ok   = sum(1 for r in results if r.status == DetectionStatus.OK)
    fail = sum(1 for r in results if r.status != DetectionStatus.OK)
    total_det = sum(len(r.detections) for r in results if r.status == DetectionStatus.OK)
    print(f"  Images processed  : {len(results)}")
    print(f"  Succeeded         : {ok}")
    print(f"  Failed/errored    : {fail}")
    print(f"  Total detections  : {total_det}")
    print(f"  Total wall time   : {total_elapsed:.1f} s")

    if torch.cuda.is_available():
        peak_alloc    = torch.cuda.max_memory_allocated(0) // (1024**2)
        peak_reserved = torch.cuda.max_memory_reserved(0) // (1024**2)
        print(f"  GPU peak alloc    : {peak_alloc} MB")
        print(f"  GPU peak reserved : {peak_reserved} MB")

    divider()
    print("Inference test complete. No predictions were hardcoded or fabricated.")
    print("Raw model outputs are printed above exactly as returned.")
    divider()

    return results


if __name__ == "__main__":
    main()
