"""
WILDSCOPE — Final visual inspection for Image C and Image B duplicate pair.
tests/inference/visual_inspection.py

------------------------------------------------------------------------
MANUAL INVESTIGATION TOOL — NOT A PYTEST TEST
------------------------------------------------------------------------
This script is a one-off investigation aid produced during Milestone 2c.
It is NOT collected or executed by pytest.  Run it directly:

    python tests/inference/visual_inspection.py

Prerequisites
-------------
This script reads pre-generated detection data from:

    data/cct_samples/annotated/raw_detections.json

This file is intentionally gitignored and is NOT included in the
repository.  It must be generated locally by running the visualization
workflow first:

    python tests/inference/visualize_detections.py

The CCT sample images (also gitignored) must also be present under
data/cct_samples/ before running either script.  See
docs/inference/requirements-inference.txt for setup instructions.

The script will exit with a clear error message if the required JSON
file is absent — this is expected behaviour for a fresh clone.
------------------------------------------------------------------------

JSON format compatibility
-------------------------
This script reads the JSON produced by visualize_detections.py.

The current (Milestone 4A+) JSON uses these field names per detection:
    detector_conf, detector_label, detector_category,
    bbox_norm, bbox_valid, crop_px,
    top_labels, top_scores, classification_attempted

The helper functions below (_get_conf, _get_top_labels, _get_top_scores,
_get_bbox_valid) accept both the current format and the older format
(conf, top5_classes, top5_scores) so that previously cached JSON files
can still be used.  If bbox_valid is absent (old format), the bbox is
assumed to be valid.
------------------------------------------------------------------------

Produces:
  1. Image C — full original (resized to fit screen)
  2. Image C — 3x magnified crop of the predicted bbox region
  3. Image C — annotated crop: model bbox + CCT bbox overlaid
  4. Image B — detections #4 and #12 highlighted separately on original

Saves all outputs to: data/cct_samples/annotated/inspection/

Does NOT modify original images, model weights, or any teammate-owned files.
Does NOT run inference — reuses raw_detections.json from prior run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parents[2]
SAMPLES_DIR = REPO_ROOT / "data" / "cct_samples"
ANN_DIR     = SAMPLES_DIR / "annotated"
OUT_DIR     = ANN_DIR / "inspection"
OUT_DIR.mkdir(parents=True, exist_ok=True)

IMG_C_PATH = SAMPLES_DIR / "5971fa92-23d2-11e8-a6a3-ec086b02610b.jpg"
IMG_B_PATH = SAMPLES_DIR / "59610788-23d2-11e8-a6a3-ec086b02610b.jpg"

JSON_PATH  = ANN_DIR / "raw_detections.json"

# ── Load saved detection data — with a clear error if missing ─────────────
if not JSON_PATH.exists():
    print(
        f"\nERROR: Required JSON file not found:\n  {JSON_PATH}\n\n"
        "This file is intentionally gitignored and must be generated locally.\n"
        "Run the following command first:\n\n"
        "    python tests/inference/visualize_detections.py\n\n"
        "(The CCT sample images must also be present under data/cct_samples/.)\n"
    )
    sys.exit(1)

with open(JSON_PATH) as f:
    all_data = json.load(f)

data_by_label = {d["image"]: d for d in all_data}
img_c_data = data_by_label["Image_C_empty"]
img_b_data = data_by_label["Image_B_bird"]

W, H = 2048, 1494   # all images are this size

# ── CCT ground-truth bbox for Image C (bbox file, category_id=30) ──────────
# [x_min, y_min, width, height] absolute pixels
CCT_C_BBOX_ABS = [1459.93, 1010.35, 128.73, 368.64]


# ── JSON format compatibility helpers ─────────────────────────────────────
# These helpers read both the current (Milestone 4A+) JSON field names and
# the older field names produced by the pre-Milestone 4A version of
# visualize_detections.py.  Fall-back values are used when a key is absent.

def _get_conf(det: dict) -> float:
    """detector_conf (current) or conf (legacy)."""
    return det.get("detector_conf", det.get("conf", 0.0))


def _get_top_labels(det: dict) -> list:
    """top_labels (current) or top5_classes (legacy)."""
    return det.get("top_labels", det.get("top5_classes", []))


def _get_top_scores(det: dict) -> list:
    """top_scores (current) or top5_scores (legacy)."""
    return det.get("top_scores", det.get("top5_scores", []))


def _get_bbox_valid(det: dict) -> bool:
    """bbox_valid (current); absent in legacy format → assume True."""
    return det.get("bbox_valid", True)


# ── Helper: try to load a bold/larger font, fall back to PIL default ────────
def get_font(size: int = 22) -> ImageFont.ImageFont:
    for name in ["arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf",
                 "DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def draw_rect_abs(draw, x, y, w, h, colour, width=3, dashed=False):
    """Draw a rectangle from absolute [x, y, w, h] pixel coords."""
    x0, y0, x1, y1 = x, y, x + w, y + h
    if not dashed:
        draw.rectangle([x0, y0, x1, y1], outline=colour, width=width)
        return
    # Dashed border
    seg = 14
    for (sx, sy, ex, ey) in [(x0,y0,x1,y0),(x1,y0,x1,y1),
                               (x0,y1,x1,y1),(x0,y0,x0,y1)]:
        length = ((ex-sx)**2+(ey-sy)**2)**0.5
        steps = max(1, int(length/seg))
        for i in range(0, steps, 2):
            t0 = i/steps; t1 = min((i+1)/steps, 1)
            draw.line([(sx+t0*(ex-sx), sy+t0*(ey-sy)),
                       (sx+t1*(ex-sx), sy+t1*(ey-sy))],
                      fill=colour, width=width)


def draw_rect_norm(draw, img_w, img_h, xn, yn, wn, hn, colour, width=3, dashed=False):
    draw_rect_abs(draw, xn*img_w, yn*img_h, wn*img_w, hn*img_h, colour, width, dashed)


def label_box(draw, x, y, text, colour, font, padding=3):
    """Draw a filled label background above the top-left corner of a box."""
    bb = draw.textbbox((x, y - 28), text, font=font)
    # Clamp to top of image
    if bb[1] < 0:
        bb = (bb[0], 0, bb[2], bb[3] - bb[1])
    draw.rectangle([bb[0]-padding, bb[1]-padding, bb[2]+padding, bb[3]+padding],
                   fill=colour)
    draw.text((x, max(0, y-28)), text, fill=(0,0,0), font=font)


# ══════════════════════════════════════════════════════════════════════════════
# 1.  Image C — Full original (scaled to ~1024 px wide for display)
# ══════════════════════════════════════════════════════════════════════════════
print("Generating Image C — full view...")
img_c_orig = Image.open(IMG_C_PATH).convert("RGB")

MAX_DISPLAY_W = 1024
scale = MAX_DISPLAY_W / img_c_orig.width
display_h = int(img_c_orig.height * scale)
img_c_display = img_c_orig.resize((MAX_DISPLAY_W, display_h), Image.LANCZOS)

# Draw model bbox + CCT bbox on display copy (scaled)
d = ImageDraw.Draw(img_c_display)
font = get_font(18)

# Model predicted bbox (normalised)
det0 = img_c_data["detections"][0]

# Guard: only draw if the bbox geometry is valid (or assumed valid for legacy JSON)
if not _get_bbox_valid(det0):
    print("  WARNING: det#0 has invalid bbox — skipping model bbox overlay.")
    xn = yn = wn = hn = 0.0   # will not be used for drawing
else:
    xn, yn, wn, hn = det0["bbox_norm"]
    # Scale to display resolution
    draw_rect_abs(d, xn*MAX_DISPLAY_W, yn*display_h, wn*MAX_DISPLAY_W, hn*display_h,
                  colour=(0, 220, 0), width=3)
    label_box(d, xn*MAX_DISPLAY_W, yn*display_h,
              f"Model det#0 conf={_get_conf(det0):.3f}", (0,220,0), font)

# CCT bbox (empty annotation)
cx, cy, cw, ch = CCT_C_BBOX_ABS
draw_rect_abs(d, cx*scale, cy*scale, cw*scale, ch*scale,
              colour=(0, 200, 220), width=3, dashed=True)
label_box(d, cx*scale, cy*scale + ch*scale + 4,
          "CCT GT: empty (cat_id=30)", (0,200,220), font)

out1 = OUT_DIR / "imgC_full_display.jpg"
img_c_display.save(out1, quality=92)
print(f"  Saved: {out1}")


# ══════════════════════════════════════════════════════════════════════════════
# 2.  Image C — 3× magnified crop of the model's predicted bbox region
#     We expand the crop by 60% on each side for context.
#     Skipped if det#0 has invalid geometry.
# ══════════════════════════════════════════════════════════════════════════════
print("Generating Image C — magnified crop (3x)...")

if not _get_bbox_valid(det0):
    print("  WARNING: det#0 bbox invalid — skipping magnified crop (sections 2 and 3).")
    out2 = out3 = None
else:
    img_c_orig2 = Image.open(IMG_C_PATH).convert("RGB")

    # Absolute pixel coords of model bbox
    mx = xn * W;  my = yn * H;  mw = wn * W;  mh = hn * H

    # Context margin: 60% of the box on each side
    margin_x = mw * 0.6
    margin_y = mh * 0.4

    crop_x0 = max(0, int(mx - margin_x))
    crop_y0 = max(0, int(my - margin_y))
    crop_x1 = min(W, int(mx + mw + margin_x))
    crop_y1 = min(H, int(my + mh + margin_y))

    crop_orig = img_c_orig2.crop((crop_x0, crop_y0, crop_x1, crop_y1))

    MAG = 3
    mag_w = crop_orig.width * MAG
    mag_h = crop_orig.height * MAG
    crop_mag = crop_orig.resize((mag_w, mag_h), Image.LANCZOS)

    out2 = OUT_DIR / "imgC_crop_3x_noannotation.jpg"
    crop_mag.save(out2, quality=95)
    print(f"  Saved: {out2}")


    # ══════════════════════════════════════════════════════════════════════════
    # 3.  Image C — Same magnified crop WITH annotations overlaid
    # ══════════════════════════════════════════════════════════════════════════
    print("Generating Image C — annotated magnified crop...")
    crop_ann = crop_mag.copy()
    d2 = ImageDraw.Draw(crop_ann)
    font2 = get_font(24)

    # Model bbox in magnified crop space
    rel_mx = (mx - crop_x0) * MAG
    rel_my = (my - crop_y0) * MAG
    rel_mw = mw * MAG
    rel_mh = mh * MAG

    draw_rect_abs(d2, rel_mx, rel_my, rel_mw, rel_mh,
                  colour=(0, 220, 0), width=4)
    top_labels = _get_top_labels(det0)
    top_scores = _get_top_scores(det0)
    top1 = top_labels[0] if top_labels else "(none)"
    top1_score = top_scores[0] if top_scores else 0.0
    top1_name = top1.split(";")[-1].strip() if ";" in top1 else top1
    label_box(d2, rel_mx, rel_my,
              f"Model: {top1_name} {top1_score:.3f} | conf={_get_conf(det0):.3f}",
              (0,220,0), font2)

    # CCT bbox in magnified crop space
    rel_cx = (cx - crop_x0) * MAG
    rel_cy = (cy - crop_y0) * MAG
    rel_cw = cw * MAG
    rel_ch = ch * MAG

    draw_rect_abs(d2, rel_cx, rel_cy, rel_cw, rel_ch,
                  colour=(0, 200, 220), width=4, dashed=True)
    label_box(d2, rel_cx, rel_cy + rel_ch + 6,
              "CCT: empty (cat_id=30)", (0, 200, 220), font2)

    out3 = OUT_DIR / "imgC_crop_3x_annotated.jpg"
    crop_ann.save(out3, quality=95)
    print(f"  Saved: {out3}")


# ══════════════════════════════════════════════════════════════════════════════
# 4.  Image B — Detections #4 and #12 highlighted separately
# ══════════════════════════════════════════════════════════════════════════════
print("Generating Image B — duplicate pair #4 and #12...")
img_b_orig = Image.open(IMG_B_PATH).convert("RGB")

# Scale to 1024px wide for display
MAX_B_W = 1024
scale_b = MAX_B_W / img_b_orig.width
b_display_h = int(img_b_orig.height * scale_b)
img_b_display = img_b_orig.resize((MAX_B_W, b_display_h), Image.LANCZOS)

d3 = ImageDraw.Draw(img_b_display)
font3 = get_font(20)

det4  = img_b_data["detections"][4]
det12 = img_b_data["detections"][12]

for det, colour, label_fmt in [
        (det4,  (255, 80,  0),  "Det#4"),
        (det12, (200, 0, 200),  "Det#12")]:
    if not _get_bbox_valid(det):
        print(f"  WARNING: {label_fmt} has invalid bbox — skipping draw.")
        continue
    xn2, yn2, wn2, hn2 = det["bbox_norm"]
    conf_val = _get_conf(det)
    lbl = (f"{label_fmt}  conf={conf_val:.3f}  "
           f"(x={int(xn2*W)},y={int(yn2*H)})")
    rx = xn2 * MAX_B_W
    ry = yn2 * b_display_h
    rw = wn2 * MAX_B_W
    rh = hn2 * b_display_h
    draw_rect_abs(d3, rx, ry, rw, rh, colour=colour, width=4)
    label_box(d3, rx, ry, lbl, colour, font3)

# Also mark GT#8 (the left-edge GT bird they both may correspond to)
# GT#8: x=5.05, y=868.14, w=100.95, h=123.66 (abs px)
GT8 = [5.05, 868.14, 100.95, 123.66]
gx, gy, gw, gh = GT8
draw_rect_abs(d3, gx*scale_b, gy*scale_b, gw*scale_b, gh*scale_b,
              colour=(0, 220, 220), width=3, dashed=True)
label_box(d3, gx*scale_b, gy*scale_b, "GT#8 (CCT bird)", (0, 220, 220), font3)

out4 = OUT_DIR / "imgB_duplicate_det4_det12.jpg"
img_b_display.save(out4, quality=92)
print(f"  Saved: {out4}")

# ── Also produce a magnified crop around the left-edge region ──────────────
# Only possible if both det#4 and det#12 have valid geometry.
if _get_bbox_valid(det4) and _get_bbox_valid(det12):
    img_b_crop_orig = Image.open(IMG_B_PATH).convert("RGB")

    # Bounding union of det#4 and det#12 in full-res pixels
    d4x = det4["bbox_norm"][0]*W;   d4y = det4["bbox_norm"][1]*H
    d4w = det4["bbox_norm"][2]*W;   d4h = det4["bbox_norm"][3]*H
    d12x = det12["bbox_norm"][0]*W; d12y = det12["bbox_norm"][1]*H
    d12w = det12["bbox_norm"][2]*W; d12h = det12["bbox_norm"][3]*H

    union_x0 = max(0, int(min(d4x, d12x) - 30))
    union_y0 = max(0, int(min(d4y, d12y) - 30))
    union_x1 = min(W, int(max(d4x+d4w, d12x+d12w) + 30))
    union_y1 = min(H, int(max(d4y+d4h, d12y+d12h) + 30))

    b_crop = img_b_crop_orig.crop((union_x0, union_y0, union_x1, union_y1))
    MAG_B = 4
    b_crop_mag = b_crop.resize((b_crop.width*MAG_B, b_crop.height*MAG_B), Image.LANCZOS)

    d4mag = ImageDraw.Draw(b_crop_mag)
    font4 = get_font(22)

    for det, colour, lbl in [
            (det4,  (255, 80, 0),   f"Det#4 conf={_get_conf(det4):.3f}"),
            (det12, (200,  0, 200), f"Det#12 conf={_get_conf(det12):.3f}")]:
        xn2, yn2, wn2, hn2 = det["bbox_norm"]
        rx = (xn2*W - union_x0) * MAG_B
        ry = (yn2*H - union_y0) * MAG_B
        rw = wn2 * W * MAG_B
        rh = hn2 * H * MAG_B
        draw_rect_abs(d4mag, rx, ry, rw, rh, colour=colour, width=4)
        label_box(d4mag, rx, ry, lbl, colour, font4)

    # GT#8
    gx2 = (GT8[0] - union_x0) * MAG_B
    gy2 = (GT8[1] - union_y0) * MAG_B
    gw2 = GT8[2] * MAG_B
    gh2 = GT8[3] * MAG_B
    draw_rect_abs(d4mag, gx2, gy2, gw2, gh2, colour=(0,220,220), width=3, dashed=True)
    label_box(d4mag, gx2, gy2, "GT#8 bird", (0,220,220), font4)

    out5 = OUT_DIR / "imgB_duplicate_crop_4x.jpg"
    b_crop_mag.save(out5, quality=95)
    print(f"  Saved: {out5}")
else:
    print("  WARNING: det#4 or det#12 has invalid bbox — skipping magnified crop.")
    out5 = None

print("\nAll inspection images generated. No original images were modified.")
print("\nFiles saved:")
for f in [out1, out2, out3, out4, out5]:
    if f is not None:
        print(f"  {f}")
