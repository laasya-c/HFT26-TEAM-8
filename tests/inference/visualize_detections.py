"""
WILDSCOPE — Detection Visualization and Investigation Script
tests/inference/visualize_detections.py

------------------------------------------------------------------------
MANUAL INVESTIGATION TOOL — NOT A PYTEST TEST
------------------------------------------------------------------------
This script is a one-off investigation aid produced during Milestone 2b/2c.
It is NOT collected or executed by pytest.  Run it directly:

    python tests/inference/visualize_detections.py

Prerequisites
-------------
The CCT sample images must be present under data/cct_samples/:

    data/cct_samples/5998cfa4-23d2-11e8-a6a3-ec086b02610b.jpg  (Image A)
    data/cct_samples/59610788-23d2-11e8-a6a3-ec086b02610b.jpg  (Image B)
    data/cct_samples/5971fa92-23d2-11e8-a6a3-ec086b02610b.jpg  (Image C)

These files are intentionally gitignored.  The script will exit with an
error if they are absent.  See docs/inference/requirements-inference.txt
for setup instructions.

SpeciesNet model weights are downloaded automatically by kagglehub on
first run (~1.8 s from cache on subsequent runs).
------------------------------------------------------------------------

Produces annotated images for the 3-image CCT inference investigation.
Runs SpeciesNetAnimalDetector inference fresh, then overlays:
  - Model predicted bboxes (numbered, colour-coded by confidence)
  - Ground-truth bboxes (dashed cyan, separate colour)

Saves outputs to: data/cct_samples/annotated/
Saves a JSON dump of raw detections to: data/cct_samples/annotated/raw_detections.json

Does NOT modify original images, model weights, or any teammate-owned files.
Does NOT commit or push anything.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Repo root on sys.path ──────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.inference.speciesnet_detector import SpeciesNetAnimalDetector
from src.inference.base_detector import DetectionStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────
SAMPLES_DIR = REPO_ROOT / "data" / "cct_samples"
OUT_DIR = SAMPLES_DIR / "annotated"
OUT_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_FILES = [
    SAMPLES_DIR / "5998cfa4-23d2-11e8-a6a3-ec086b02610b.jpg",  # Image A — opossum
    SAMPLES_DIR / "59610788-23d2-11e8-a6a3-ec086b02610b.jpg",  # Image B — bird x9
    SAMPLES_DIR / "5971fa92-23d2-11e8-a6a3-ec086b02610b.jpg",  # Image C — empty
]

LABELS = {
    "5998cfa4-23d2-11e8-a6a3-ec086b02610b.jpg": "Image_A_opossum",
    "59610788-23d2-11e8-a6a3-ec086b02610b.jpg": "Image_B_bird",
    "5971fa92-23d2-11e8-a6a3-ec086b02610b.jpg": "Image_C_empty",
}

# Ground-truth bounding boxes from CCT annotations
# Format: absolute pixels [x_min, y_min, width, height] (CCT format)
# Image dimensions: 2048 x 1494
W, H = 2048, 1494

GT_BBOXES = {
    "5998cfa4-23d2-11e8-a6a3-ec086b02610b.jpg": [
        # category_id=1 (opossum)
        {"bbox_abs": [499.2, 711.68, 353.28, 199.68], "category": "opossum"},
    ],
    "59610788-23d2-11e8-a6a3-ec086b02610b.jpg": [
        # category_id=11 (bird) — 9 GT boxes
        {"bbox_abs": [1910.40, 1067.50, 136.28, 113.56], "category": "bird"},
        {"bbox_abs": [1594.95, 1095.26,  58.04,  60.57], "category": "bird"},
        {"bbox_abs": [1630.28,  941.32,  75.71,  65.61], "category": "bird"},
        {"bbox_abs": [1274.44,  951.42, 100.95,  50.47], "category": "bird"},
        {"bbox_abs": [1294.63,  830.28,  90.85,  37.85], "category": "bird"},
        {"bbox_abs": [1529.33,  842.90,  85.80,  37.85], "category": "bird"},
        {"bbox_abs": [ 903.47,  820.19, 111.04, 103.47], "category": "bird"},
        {"bbox_abs": [ 426.50,  731.86, 108.52,  88.33], "category": "bird"},
        {"bbox_abs": [   5.05,  868.14, 100.95, 123.66], "category": "bird"},
    ],
    "5971fa92-23d2-11e8-a6a3-ec086b02610b.jpg": [
        # category_id=30 (empty) — there IS a bbox in the empty annotation file
        # This box marks the region annotated as "empty" by CCT.
        {"bbox_abs": [1459.93, 1010.35, 128.73, 368.64], "category": "empty (CCT cat_id=30)"},
    ],
}


# ── Drawing helpers ────────────────────────────────────────────────────────

def conf_to_colour(conf: float) -> tuple[int, int, int]:
    """Map detection confidence to a traffic-light RGB colour."""
    if conf >= 0.7:
        return (0, 220, 0)    # green — high confidence
    elif conf >= 0.3:
        return (255, 165, 0)  # orange — medium confidence
    else:
        return (220, 0, 0)    # red — low confidence


def draw_bbox_abs(draw: ImageDraw.Draw,
                  x: float, y: float, w: float, h: float,
                  colour: tuple, label: str,
                  line_width: int = 3,
                  dashed: bool = False) -> None:
    """Draw a bbox from absolute pixel coords [x_min, y_min, w, h]."""
    x0, y0, x1, y1 = x, y, x + w, y + h

    if dashed:
        # Draw dashed border by drawing segments
        seg = 15
        coords = [
            (x0, y0, x1, y0),  # top
            (x1, y0, x1, y1),  # right
            (x0, y1, x1, y1),  # bottom
            (x0, y0, x0, y1),  # left
        ]
        for (sx, sy, ex, ey) in coords:
            length = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
            steps = max(1, int(length / seg))
            for i in range(0, steps, 2):
                t0_ = i / steps
                t1_ = min((i + 1) / steps, 1.0)
                draw.line(
                    [(sx + t0_ * (ex - sx), sy + t0_ * (ey - sy)),
                     (sx + t1_ * (ex - sx), sy + t1_ * (ey - sy))],
                    fill=colour, width=line_width,
                )
    else:
        draw.rectangle([x0, y0, x1, y1], outline=colour, width=line_width)

    # Label background
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font = ImageFont.load_default()

    bbox_text = draw.textbbox((x0, y0 - 24), label, font=font)
    draw.rectangle(bbox_text, fill=colour)
    draw.text((x0, y0 - 24), label, fill=(0, 0, 0), font=font)


def draw_bbox_norm(draw: ImageDraw.Draw,
                   img_w: int, img_h: int,
                   xn: float, yn: float, wn: float, hn: float,
                   colour: tuple, label: str,
                   line_width: int = 3,
                   dashed: bool = False) -> None:
    """Convert normalised [0-1] bbox to pixels, then draw."""
    draw_bbox_abs(
        draw,
        x=xn * img_w, y=yn * img_h,
        w=wn * img_w,  h=hn * img_h,
        colour=colour, label=label,
        line_width=line_width, dashed=dashed,
    )


# ── Per-image annotator ────────────────────────────────────────────────────

def annotate_image(result, gt_bboxes: list[dict], short_label: str) -> Path:
    """
    Draw model predictions and GT boxes on a copy of the original image.
    Returns the path to the saved annotated image.
    """
    img = Image.open(result.filepath).convert("RGB")
    draw = ImageDraw.Draw(img)
    img_w, img_h = img.size

    # ── 1. Ground-truth boxes (dashed cyan) ──────────────────────────────
    for gi, gt in enumerate(gt_bboxes):
        x, y, w, h = gt["bbox_abs"]
        draw_bbox_abs(
            draw, x, y, w, h,
            colour=(0, 220, 220),
            label=f"GT:{gi}  {gt['category']}",
            line_width=2,
            dashed=True,
        )

    # ── 2. Model predictions (solid, colour-coded by confidence) ─────────
    for i, det in enumerate(result.detections):
        # Guard: only draw geometry when the bbox is geometrically valid.
        if not det.bbox_valid:
            log.warning(
                "Detection #%d has invalid bbox_norm=%r — skipping bbox draw; "
                "classification label still shown in report.",
                i, det.bbox_norm,
            )
            continue

        xn, yn, wn, hn = det.bbox_norm
        colour = conf_to_colour(det.detector_conf)

        # Build label: index, conf, top-1 species
        top_labels = det.classification.top_labels
        top1 = top_labels[0] if top_labels else "(no classif.)"
        if top1 == "":
            top1 = "(blank)"
        lbl = f"#{i} {det.detector_conf:.2f} | {top1[:30]}"

        draw_bbox_norm(
            draw, img_w, img_h,
            xn, yn, wn, hn,
            colour=colour, label=lbl,
            line_width=3,
        )

    out_path = OUT_DIR / f"{short_label}_annotated.jpg"
    img.save(out_path, quality=90)
    log.info("Saved: %s", out_path)
    return out_path


# ── Detailed text report ───────────────────────────────────────────────────

def crop_px_dims(img_w: int, img_h: int,
                 xn: float, yn: float, wn: float, hn: float) -> tuple[int, int]:
    """Return pixel dimensions of a normalised crop."""
    return int(wn * img_w), int(hn * img_h)


def iou(b1: list[float], b2: list[float]) -> float:
    """
    Compute IoU of two normalised [xmin, ymin, w, h] boxes.
    """
    x1a, y1a = b1[0], b1[1]
    x2a, y2a = b1[0] + b1[2], b1[1] + b1[3]
    x1b, y1b = b2[0], b2[1]
    x2b, y2b = b2[0] + b2[2], b2[1] + b2[3]

    ix1, iy1 = max(x1a, x1b), max(y1a, y1b)
    ix2, iy2 = min(x2a, x2b), min(y2a, y2b)

    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter = inter_w * inter_h

    area_a = b1[2] * b1[3]
    area_b = b2[2] * b2[3]
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


def report_image(result, gt_bboxes: list[dict], label: str) -> dict:
    """Print detailed per-image report and return structured data."""
    divider = "=" * 74
    sub     = "-" * 74
    img_w, img_h = result.image_w, result.image_h

    print(f"\n{divider}")
    print(f"  {label}  |  {Path(result.filepath).name}")
    print(f"  Dimensions : {img_w} x {img_h} px")
    print(f"  GT boxes   : {len(gt_bboxes)}")
    print(f"  Model dets : {len(result.detections)}")
    print(divider)

    # ── Detection table ──────────────────────────────────────────────────
    for i, det in enumerate(result.detections):
        xn, yn, wn, hn = det.bbox_norm
        top_labels = det.classification.top_labels
        top_scores = det.classification.top_scores
        top1 = top_labels[0] if top_labels else "(none)"
        top1_score = top_scores[0] if top_scores else 0.0

        print(f"\n  Detection #{i}")
        print(f"    Label          : {det.detector_label}  "
              f"(category={det.detector_category})")
        print(f"    Conf (MegaDet) : {det.detector_conf:.6f}")
        print(f"    BBox norm      : x={xn:.4f}  y={yn:.4f}  "
              f"w={wn:.4f}  h={hn:.4f}")
        print(f"    BBox valid     : {det.bbox_valid}")

        if det.bbox_valid:
            crop_w, crop_h = crop_px_dims(img_w, img_h, xn, yn, wn, hn)
            print(f"    BBox pixels    : x={int(xn*img_w)}  y={int(yn*img_h)}"
                  f"  w={crop_w}  h={crop_h}")
            print(f"    Crop size      : {crop_w} x {crop_h} px")
            # Flag very small crops
            MIN_DIM = 50
            if crop_w < MIN_DIM or crop_h < MIN_DIM:
                print(f"    *** SMALL CROP: {crop_w}x{crop_h} px — "
                      "classifier may return blank due to insufficient visual info ***")
        else:
            print("    BBox pixels    : N/A (invalid geometry — see bbox_norm)")

        if det.classification.attempted:
            print(f"    Classif device : {result.classify_device}")
            if top_labels:
                print("    Top-5 species  :")
                for rank, (cls, sc) in enumerate(
                        zip(top_labels, top_scores), 1):
                    cls_disp = cls if cls else "(blank)"
                    print(f"      #{rank}: {cls_disp:<55} {sc:.6f}")
            else:
                print("    Top-5 species  : [classifier returned empty list]")

    # ── IoU overlap matrix (only for images with many detections) ────────
    dets = result.detections
    # Only compare detections with valid geometry for IoU
    valid_dets = [(i, d) for i, d in enumerate(dets) if d.bbox_valid]
    if len(valid_dets) >= 2:
        print(f"\n{sub}")
        print("  Overlap analysis (IoU matrix — detections with IoU > 0.3 flagged):")
        overlaps_found = False
        for a, (i, di) in enumerate(valid_dets):
            for j, dj in valid_dets[a + 1:]:
                score = iou(di.bbox_norm, dj.bbox_norm)
                if score > 0.3:
                    print(f"    Det #{i} <-> Det #{j} : IoU = {score:.3f}"
                          "  <-- possible duplicate")
                    overlaps_found = True
        if not overlaps_found:
            print("    No overlapping pairs (IoU > 0.3) found.")

    # ── GT vs model comparison ────────────────────────────────────────────
    print(f"\n{sub}")
    print("  Ground-truth boxes (CCT — NOT fed to model):")
    for gi, gt in enumerate(gt_bboxes):
        bx, by, bw, bh = gt["bbox_abs"]
        print(f"    GT #{gi}: category={gt['category']}"
              f"  x={bx:.1f} y={by:.1f} w={bw:.1f} h={bh:.1f} (abs px)")

    structured = {
        "image": label,
        "filepath": result.filepath,
        "image_wh": [img_w, img_h],
        "gt_boxes": gt_bboxes,
        "detections": [
            {
                "idx": i,
                "detector_label": d.detector_label,
                "detector_category": d.detector_category,
                "detector_conf": d.detector_conf,
                "bbox_norm": d.bbox_norm,
                "bbox_valid": d.bbox_valid,
                "crop_px": (
                    list(crop_px_dims(img_w, img_h,
                                      d.bbox_norm[0], d.bbox_norm[1],
                                      d.bbox_norm[2], d.bbox_norm[3]))
                    if d.bbox_valid else None
                ),
                "top_labels": d.classification.top_labels,
                "top_scores": d.classification.top_scores,
                "classification_attempted": d.classification.attempted,
            }
            for i, d in enumerate(result.detections)
        ],
    }
    return structured


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 74)
    print("WILDSCOPE — Detection Visualization & Investigation")
    print("=" * 74)

    # Verify inputs
    missing = [p for p in IMAGE_FILES if not p.exists()]
    if missing:
        print("ABORT — missing images:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)

    print("\nInitialising SpeciesNetAnimalDetector (models load from cache)...")
    detector = SpeciesNetAnimalDetector()
    print(f"Detector device : {detector.device}")
    print(f"Output dir      : {OUT_DIR}")

    print("\nRunning detect_batch on 3 images...")
    t0 = time.perf_counter()
    results = detector.detect_batch([str(p) for p in IMAGE_FILES])
    elapsed = time.perf_counter() - t0
    print(f"Inference complete in {elapsed:.1f} s\n")

    all_data = []
    saved_paths = []

    for result in results:
        fname = Path(result.filepath).name
        short_label = LABELS[fname]
        gt = GT_BBOXES.get(fname, [])

        if result.status != DetectionStatus.OK:
            print(f"ERROR for {fname}: {result.error_message}")
            continue

        # Text report
        data = report_image(result, gt, short_label)
        all_data.append(data)

        # Annotated image
        out_path = annotate_image(result, gt, short_label)
        saved_paths.append(out_path)

    # Save raw JSON (uses current field names — readable by visual_inspection.py)
    json_path = OUT_DIR / "raw_detections.json"
    with open(json_path, "w") as f:
        json.dump(all_data, f, indent=2)
    print(f"\nRaw detections saved: {json_path}")

    print("\nAnnotated images:")
    for p in saved_paths:
        print(f"  {p}")

    print("\nDone. No original images were modified.")


if __name__ == "__main__":
    main()
