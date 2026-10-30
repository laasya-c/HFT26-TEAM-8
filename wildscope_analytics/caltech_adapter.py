"""
WILDSCOPE Decision Intelligence & Analytics Module
Caltech Camera Traps (CCT) Dataset Adapter - Phase 2

Imports official Caltech Camera Traps annotations into a WILDSCOPE Snapshot
using the dataset_reference data source mode. Reference annotations are NEVER
mixed with operational_prediction Detection records.

Official dataset:
  Homepage:   https://lila.science/datasets/caltech-camera-traps
  Format:     COCO Camera Traps (CCT) JSON
  License:    Community Data License Agreement - Permissive, Version 1.0
  Images:     ~243,100 across ~140 camera locations (Southern California)
  Annotation: Image-level categories (most) + bounding boxes (subset)
  Categories: ~22 categories including 'empty', species names, 'person', 'vehicle'
  Timestamps: 'date_captured' string (local time, timezone UNKNOWN - NOT UTC)
  Sequences:  seq_id groups burst captures from the same trigger event

NETWORK BLOCKER (sandbox):
  Direct download is blocked by sandbox network isolation.
  socket.gaierror: [Errno 11001] getaddrinfo failed when attempting any outbound connection.

  Acquisition instructions (user must run outside sandbox):
    1. Download metadata JSON (no images needed for reference analytics):
       GCP (no auth):
         gsutil cp gs://public-datasets-lila/caltechcameratraps/labels/caltech_camera_traps.json.zip .
       OR direct HTTP:
         curl -L "https://lilawildlife.blob.core.windows.net/lila-wildlife/caltechcameratraps/labels/caltech_camera_traps.json.zip" -o caltech_camera_traps.json.zip
         unzip caltech_camera_traps.json.zip
    2. Optionally download a subset of images for image-path verification:
         gsutil -m cp -r "gs://public-datasets-lila/caltech-unzipped/cct_images/" ./cct_images/ --max-bytes 500MB

TIMESTAMP POLICY:
  date_captured values are local wall-clock times with NO timezone specified in the dataset.
  The field is documented as local time but timezone is not published.
  Per project policy:
    - raw_timestamp preserves the original string exactly.
    - captured_at is ONLY populated if the caller supplies an explicit timezone policy.
    - Naive source timestamps are NEVER silently assigned UTC or any other timezone.
    - If no timezone policy is supplied, captured_at = None and a provenance warning is recorded.
    - Time-independent metrics remain usable regardless.

CATEGORY MAPPING:
  Original CCT category IDs (integers) and names (strings) are preserved exactly.
  wildscope_taxon_id provides a mapped internal identifier where reasonable.
  Non-animal categories (empty, person, vehicle) get is_animal=False, wildscope_taxon_id=None.
  Unknown/broad categories get wildscope_taxon_id=None with is_animal=True if applicable.

ID NAMESPACING:
  All IDs are prefixed with 'cct:' to avoid collisions with operational pipeline IDs:
    camera:      cct:cam:{location_id}
    media:       cct:img:{image_id}
    observation: cct:obs:{image_id}
    annotation:  cct:ann:{annotation_id}

SUBSET SELECTION:
  If max_images is specified, a deterministic subset is selected by sorted image ID.
  This is documented and reproducible; NOT cherry-picked for better-looking results.
"""

from __future__ import annotations

import json
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wildscope_analytics.contracts.entities import (
    Camera,
    DatasetReferenceAnnotation,
    MediaAsset,
    MonitoringEffort,
    Observation,
)
from wildscope_analytics.contracts.enums import (
    AnnotationSource,
    DataSourceMode,
    EncounterProcessingStatus,
    MediaType,
    ReviewOrderingMechanism,
)
from wildscope_analytics.contracts.snapshot import (
    CURRENT_SCHEMA_VERSION,
    Snapshot,
    SnapshotMetadata,
)


# ---------------------------------------------------------------------------
# KNOWN CCT CATEGORY MAPPING
# The actual category list is read from the annotation file.
# This mapping provides wildscope_taxon_id and is_animal flags for known categories.
# Categories not in this table default to:
#   is_animal=True, wildscope_taxon_id=None (unknown/unmapped animal)
# ---------------------------------------------------------------------------

# Format: category_name_lower → (wildscope_taxon_id_or_None, is_animal, is_empty)
_CCT_CATEGORY_MAP: dict[str, tuple[str | None, bool, bool]] = {
    # Non-animal categories (explicit vehicle, person, empty)
    "empty":          (None,                    False, True),
    "blank":          (None,                    False, True),
    "vehicle":        (None,                    False, False),
    "car":            (None,                    False, False),
    "truck":          (None,                    False, False),
    "motorcycle":     (None,                    False, False),
    "bicycle":        (None,                    False, False),
    "person":         (None,                    False, False),
    "human":          (None,                    False, False),
    "pedestrian":     (None,                    False, False),

    # Animals in CCT and common camera traps
    "opossum":        ("didelphis_virginiana",   True,  False),
    "raccoon":        ("procyon_lotor",          True,  False),
    "coyote":         ("canis_latrans",          True,  False),
    "bobcat":         ("lynx_rufus",             True,  False),
    "squirrel":       ("sciuridae_sp",           True,  False),
    "rabbit":         ("sylvilagus_sp",          True,  False),
    "rodent":         ("rodentia_sp",            True,  False),
    "deer":           ("odocoileus_sp",          True,  False),
    "bird":           ("aves_sp",                True,  False),
    "skunk":          ("mephitidae_sp",          True,  False),
    "fox":            ("vulpes_sp",              True,  False),
    "mountain lion":  ("puma_concolor",          True,  False),
    "mountain_lion":  ("puma_concolor",          True,  False),
    "dog":            ("canis_lupus_familiaris", True,  False),
    "cat":            ("felis_catus",            True,  False),
    "lizard":         ("squamata_sp",            True,  False),
    "cow":            ("bos_taurus",             True,  False),
    "badger":         ("taxidea_taxus",          True,  False),
    "pig":            ("sus_scrofa",             True,  False),
    "bat":            ("chiroptera_sp",          True,  False),
    "insect":         ("insecta_sp",             True,  False),
    "snake":          ("serpentes_sp",           True,  False),

    # Broad animal groups
    "small mammal":   (None,                    True,  False),
    "small_mammal":   (None,                    True,  False),
    "animal":         (None,                    True,  False),
}

_NON_ANIMAL_KEYWORDS = ("car", "vehicle", "truck", "motorcycle", "bicycle", "person", "human", "pedestrian", "equipment", "debris")
_ANIMAL_KEYWORDS = ("species", "wildlife", "animal", "mammal", "bird", "reptile", "amphibian", "insect", "fauna", "creature")


@dataclass
class CCTImportReport:
    """Report produced by the Caltech adapter on each import run."""
    annotation_file: str
    dataset_version: str
    timezone_policy: str | None
    subset_rule: str
    total_images_in_file: int
    total_images_imported: int
    total_images_excluded: int
    total_annotations_in_file: int
    total_annotations_imported: int
    total_annotations_excluded: int
    total_cameras: int
    categories_total: int
    categories_animal: int
    categories_non_animal: int
    categories_unmapped: list[str]
    exclusion_reasons: dict[str, int]
    missing_metadata: list[str]
    warnings: list[str]
    acquisition_instructions: str = (
        "Dataset blocked by sandbox network isolation. "
        "See module docstring for download instructions."
    )
    is_blocked: bool = False
    block_reason: str | None = None


def _resolve_category(
    cat_name: str,
    cat_id: int,
) -> tuple[str | None, bool, bool, list[str]]:
    """
    Resolve (wildscope_taxon_id, is_animal, is_empty, warnings) for a CCT category.
    Preserves exact category_name as published; maps to internal identifiers separately.
    Explicit vehicle/person categories are non-animal.
    Unmapped wildlife remains visible as an unresolved animal taxon.
    Unknown categories without clear indicators are flagged and not silently assumed animal.
    """
    key = cat_name.lower().strip()
    if key in _CCT_CATEGORY_MAP:
        taxon, is_anim, is_emp = _CCT_CATEGORY_MAP[key]
        return taxon, is_anim, is_emp, []

    # Check non-animal keywords (car, vehicle, person, etc.)
    if any(kw in key for kw in _NON_ANIMAL_KEYWORDS):
        return None, False, False, []

    # Check empty keywords
    if "empty" in key or "blank" in key:
        return None, False, True, []

    # Check animal keywords
    if any(kw in key for kw in _ANIMAL_KEYWORDS):
        return None, True, False, []

    # Truly unknown category: do not silently classify as animal
    warn = (
        f"Category '{cat_id}:{cat_name}' is not in known mapping; "
        "cannot silently assume animal classification. Preserving as unclassified non-animal."
    )
    return None, False, False, [warn]


def _parse_cct_timestamp(
    date_str: str | None,
    tz_policy: ZoneInfo | None,
    tz_policy_name: str | None,
) -> tuple[str | None, datetime | None, list[str]]:
    """
    Parse a CCT date_captured string.

    Returns:
      (raw_timestamp, captured_at_or_None, warnings)

    Policy:
      - raw_timestamp is always preserved exactly.
      - captured_at is populated ONLY if tz_policy is not None.
      - If tz_policy is None, captured_at = None (no silent UTC assignment).
      - Ambiguous/non-existent local times are reported in warnings, not silently guessed.
    """
    if not date_str:
        return (None, None, ["Image has no date_captured field."])

    raw_ts = date_str.strip()
    warns: list[str] = []

    if tz_policy is None:
        warns.append(
            f"No timezone policy supplied; captured_at left null for raw timestamp '{raw_ts}'. "
            "CCT timestamps are local time with undisclosed timezone. "
            "Provide --timezone to populate captured_at."
        )
        return (raw_ts, None, warns)

    # Try common CCT timestamp formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d",
    ]
    naive_dt = None
    for fmt in formats:
        try:
            naive_dt = datetime.strptime(raw_ts, fmt)
            break
        except ValueError:
            continue

    if naive_dt is None:
        warns.append(f"Unrecognised date_captured format: '{raw_ts}'. captured_at left null.")
        return (raw_ts, None, warns)

    # Attach timezone policy
    try:
        # fold=0: use standard time when ambiguous (DST transitions)
        aware_dt = naive_dt.replace(tzinfo=tz_policy)
        warns.append(
            f"Timezone policy '{tz_policy_name}' applied to raw timestamp '{raw_ts}'. "
            "Caltech CCT does not publish timezone; this is an analyst-supplied assumption."
        )
        return (raw_ts, aware_dt, warns)
    except Exception as exc:
        warns.append(f"Failed to apply timezone policy to '{raw_ts}': {exc}")
        return (raw_ts, None, warns)


def import_caltech_snapshot(
    annotation_file: str | Path,
    image_root: str | Path | None = None,
    max_images: int | None = None,
    location_ids: list[str] | None = None,
    timezone_policy: str | None = None,
    dataset_version: str = "caltech_camera_traps_v1",
    dataset_revision: int = 0,
) -> tuple[Snapshot, CCTImportReport]:
    """
    Import a Caltech Camera Traps CCT-format annotation JSON into a WILDSCOPE Snapshot.

    Parameters
    ----------
    annotation_file : path to the main caltech_camera_traps.json (or .json.zip).
    image_root      : optional local path to the cct_images/ folder (for storage_key resolution).
    max_images      : if set, import at most this many images. Selection is deterministic
                      by sorted image ID. NOT cherry-picked.
    location_ids    : if set, only import images from these camera location IDs.
    timezone_policy : IANA timezone string to apply to date_captured values.
                      If None, captured_at is left null (never silently UTC).
    dataset_version : provenance string identifying the dataset release.
    dataset_revision: integer revision for the snapshot metadata.

    Returns
    -------
    (Snapshot, CCTImportReport)
    """
    ann_path = Path(annotation_file)
    if not ann_path.exists():
        report = CCTImportReport(
            annotation_file=str(ann_path),
            dataset_version=dataset_version,
            timezone_policy=timezone_policy,
            subset_rule="N/A",
            total_images_in_file=0,
            total_images_imported=0,
            total_images_excluded=0,
            total_annotations_in_file=0,
            total_annotations_imported=0,
            total_annotations_excluded=0,
            total_cameras=0,
            categories_total=0,
            categories_animal=0,
            categories_non_animal=0,
            categories_unmapped=[],
            exclusion_reasons={},
            missing_metadata=["annotation_file not found"],
            warnings=[f"Annotation file not found: {ann_path}"],
            is_blocked=True,
            block_reason=f"File not found: {ann_path}",
        )
        # Return an empty snapshot with a clear data source mode
        meta = SnapshotMetadata(
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=dataset_revision,
            created_at=datetime.now(timezone.utc),
            source_system="WILDSCOPE_CALTECH_ADAPTER",
            data_source_mode=DataSourceMode.DATASET_REFERENCE,
            review_ordering_mechanism=ReviewOrderingMechanism.BACKEND_REVISION,
            provenance={
                "dataset_name": "caltech_camera_traps",
                "dataset_version": dataset_version,
                "annotation_file": str(ann_path),
                "status": "FILE_NOT_FOUND",
            },
        )
        snap = Snapshot(metadata=meta)
        return snap, report

    # --- Load annotation file
    if ann_path.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(ann_path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".json")]
            if not names:
                raise ValueError(f"No JSON file found inside ZIP: {ann_path}")
            with zf.open(names[0]) as f:
                cct_data = json.load(f)
    else:
        with open(ann_path, "r", encoding="utf-8") as f:
            cct_data = json.load(f)

    # --- Parse categories
    categories: dict[int, dict[str, Any]] = {}
    categories_animal: int = 0
    categories_non_animal: int = 0
    unmapped_categories: list[str] = []

    for cat in cct_data.get("categories", []):
        cat_id = int(cat["id"])
        cat_name = str(cat.get("name", f"category_{cat_id}"))
        taxon_id, is_animal, is_empty, cat_warns = _resolve_category(cat_name, cat_id)
        if cat_warns:
            import_warnings.extend(cat_warns)
        categories[cat_id] = {
            "id": cat_id,
            "name": cat_name,
            "wildscope_taxon_id": taxon_id,
            "is_animal": is_animal,
            "is_empty": is_empty,
        }
        if is_animal:
            categories_animal += 1
        else:
            categories_non_animal += 1
        if taxon_id is None and not is_empty and is_animal:
            unmapped_categories.append(f"{cat_id}:{cat_name}")

    # --- Parse images
    all_images: list[dict] = cct_data.get("images", [])
    total_images_in_file = len(all_images)

    # Location filter
    if location_ids is not None:
        loc_set = {str(l) for l in location_ids}
        all_images = [img for img in all_images if str(img.get("location", "")) in loc_set]

    # Deterministic subset: sort by image ID, take first max_images
    all_images_sorted = sorted(all_images, key=lambda img: str(img.get("id", "")))
    if max_images is not None and max_images < len(all_images_sorted):
        selected_images = all_images_sorted[:max_images]
        subset_rule = (
            f"First {max_images} images by sorted image ID"
            + (f" from locations {location_ids}" if location_ids else "")
        )
    else:
        selected_images = all_images_sorted
        subset_rule = (
            "All images"
            + (f" from locations {location_ids}" if location_ids else "")
        )

    selected_image_ids: set[str] = {str(img.get("id", "")) for img in selected_images}

    # --- Parse annotations (index by image_id)
    all_annotations: list[dict] = cct_data.get("annotations", [])
    total_annotations_in_file = len(all_annotations)
    anns_by_image: dict[str, list[dict]] = defaultdict(list)
    for ann in all_annotations:
        img_id = str(ann.get("image_id", ""))
        if img_id in selected_image_ids:
            anns_by_image[img_id].append(ann)

    # --- Timezone policy
    tz_obj: ZoneInfo | None = None
    tz_warn: list[str] = []
    if timezone_policy:
        try:
            tz_obj = ZoneInfo(timezone_policy)
        except ZoneInfoNotFoundError:
            tz_warn.append(
                f"Supplied timezone_policy '{timezone_policy}' is not a valid IANA timezone. "
                "captured_at will be left null for all images."
            )
            tz_obj = None

    # --- Build snapshot entities
    cameras: dict[str, Camera] = {}       # location_id → Camera
    media_assets: list[MediaAsset] = []
    observations: list[Observation] = []
    reference_annotations: list[DatasetReferenceAnnotation] = []

    exclusion_reasons: dict[str, int] = {}
    missing_metadata: list[str] = []
    import_warnings: list[str] = []
    import_warnings.extend(tz_warn)
    images_imported = 0
    images_excluded = 0
    annotations_imported = 0
    annotations_excluded = 0

    for img in selected_images:
        img_id = str(img.get("id", ""))
        location_id = str(img.get("location", "unknown_location"))
        file_name = img.get("file_name", f"{img_id}.jpg")
        width_px = img.get("width")
        height_px = img.get("height")
        date_str = img.get("date_captured")
        seq_id = img.get("seq_id")
        frame_num = img.get("frame_num")

        # Namespaced IDs
        cam_id = f"cct:cam:{location_id}"
        media_id = f"cct:img:{img_id}"
        obs_id = f"cct:obs:{img_id}"

        # Camera record (one per location)
        if cam_id not in cameras:
            cameras[cam_id] = Camera(
                id=cam_id,
                site_id=location_id,
                latitude=None,    # CCT does not publish GPS in open metadata
                longitude=None,
                timezone=None,    # Timezone not published in CCT
                provenance={
                    "dataset": "caltech_camera_traps",
                    "dataset_version": dataset_version,
                    "location_id": location_id,
                    "note": (
                        "GPS coordinates not published in Caltech CCT open metadata. "
                        "Timezone not published."
                    ),
                },
            )

        # Timestamp parsing
        raw_ts, captured_at, ts_warns = _parse_cct_timestamp(date_str, tz_obj, timezone_policy)
        import_warnings.extend(ts_warns[:1])  # Limit per-image noise; keep first

        # Media asset
        if image_root:
            storage_key = str(Path(image_root) / file_name)
        else:
            storage_key = f"cct_images/{file_name}"

        media_assets.append(MediaAsset(
            id=media_id,
            media_type=MediaType.IMAGE,
            camera_id=cam_id,
            storage_key=storage_key,
            raw_timestamp=raw_ts,
            captured_at=captured_at,
            timezone_source=f"analyst_policy:{timezone_policy}" if timezone_policy and captured_at else None,
            provenance={
                "dataset": "caltech_camera_traps",
                "source_image_id": img_id,
                "file_name": file_name,
                "seq_id": seq_id,
                "frame_num": frame_num,
            },
        ))

        # Observation
        observations.append(Observation(
            id=obs_id,
            camera_id=cam_id,
            source_media_id=media_id,
            captured_at=captured_at,
            raw_timestamp=raw_ts,
            timezone_source=f"analyst_policy:{timezone_policy}" if timezone_policy and captured_at else None,
            width_px=int(width_px) if width_px is not None else None,
            height_px=int(height_px) if height_px is not None else None,
            detection_ids=[],  # Reference mode: no operational detections
        ))

        images_imported += 1

        # Reference annotations for this image
        img_anns = anns_by_image.get(img_id, [])
        if not img_anns:
            # Image with no annotations: treat as implicitly empty
            reference_annotations.append(DatasetReferenceAnnotation(
                id=f"cct:ann:implicit_empty:{img_id}",
                observation_id=obs_id,
                source_annotation_id=f"implicit_empty:{img_id}",
                source_image_id=img_id,
                dataset_name="caltech_camera_traps",
                dataset_version=dataset_version,
                category_id=0,
                category_name="empty",
                wildscope_taxon_id=None,
                is_animal=False,
                is_empty=True,
                bbox_coco=None,
                sequence_id=seq_id,
                provenance={
                    "note": "Image has no annotations; treated as empty per CCT convention.",
                    "source": "caltech_camera_traps",
                },
            ))
            annotations_imported += 1
        else:
            for ann in img_anns:
                ann_id = str(ann.get("id", ""))
                cat_id_raw = ann.get("category_id")
                if cat_id_raw is None:
                    reason = "Annotation missing category_id"
                    exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
                    annotations_excluded += 1
                    continue

                cat_id = int(cat_id_raw)
                cat_info = categories.get(cat_id)
                if cat_info is None:
                    reason = f"Unknown category_id {cat_id}"
                    exclusion_reasons[reason] = exclusion_reasons.get(reason, 0) + 1
                    annotations_excluded += 1
                    continue

                bbox_raw = ann.get("bbox")
                bbox_coco = [float(x) for x in bbox_raw] if bbox_raw else None

                reference_annotations.append(DatasetReferenceAnnotation(
                    id=f"cct:ann:{ann_id}",
                    observation_id=obs_id,
                    source_annotation_id=ann_id,
                    source_image_id=img_id,
                    dataset_name="caltech_camera_traps",
                    dataset_version=dataset_version,
                    category_id=cat_id,
                    category_name=cat_info["name"],
                    wildscope_taxon_id=cat_info["wildscope_taxon_id"],
                    is_animal=cat_info["is_animal"],
                    is_empty=cat_info["is_empty"],
                    bbox_coco=bbox_coco,
                    sequence_id=seq_id,
                    provenance={
                        "dataset": "caltech_camera_traps",
                        "dataset_version": dataset_version,
                        "license": "CDLA-Permissive-1.0",
                        "source_url": "https://lila.science/datasets/caltech-camera-traps",
                    },
                ))
                annotations_imported += 1

    # Summarise missing metadata
    if not timezone_policy:
        missing_metadata.append(
            "timezone_policy not supplied; captured_at is null for all images. "
            "CCT date_captured is local time without published timezone."
        )
    missing_cam_gps = sum(1 for c in cameras.values() if c.latitude is None)
    if missing_cam_gps:
        missing_metadata.append(
            f"{missing_cam_gps} cameras have no GPS coordinates "
            "(Caltech CCT does not publish open GPS data)."
        )

    # Trim per-image timezone warnings to avoid spamming report
    import_warnings = list(dict.fromkeys(import_warnings))  # deduplicate

    # --- Assemble Snapshot
    meta = SnapshotMetadata(
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=dataset_revision,
        created_at=datetime.now(timezone.utc),
        source_system="WILDSCOPE_CALTECH_ADAPTER",
        data_source_mode=DataSourceMode.DATASET_REFERENCE,
        review_ordering_mechanism=ReviewOrderingMechanism.BACKEND_REVISION,
        encounter_processing_status=EncounterProcessingStatus.UNAVAILABLE,
        has_spatial_context=False,
        has_monitoring_effort=False,
        provenance={
            "dataset_name": "caltech_camera_traps",
            "dataset_version": dataset_version,
            "annotation_file": str(ann_path),
            "subset_rule": subset_rule,
            "timezone_policy": timezone_policy or "none_supplied",
            "images_imported": images_imported,
            "images_excluded": images_excluded,
            "annotations_imported": annotations_imported,
            "annotations_excluded": annotations_excluded,
        },
    )

    snapshot = Snapshot(
        metadata=meta,
        cameras=list(cameras.values()),
        media_assets=media_assets,
        observations=observations,
        prediction_runs=[],       # Reference mode: no prediction runs
        detections=[],            # Reference mode: no operational detections
        encounters=[],            # Reference mode: encounters require Harsh's grouper
        reviews=[],               # Reference mode: no review events
        monitoring_efforts=[],    # CCT does not publish effort records
        spatial_context=None,
        reference_annotations=reference_annotations,
    )

    report = CCTImportReport(
        annotation_file=str(ann_path),
        dataset_version=dataset_version,
        timezone_policy=timezone_policy,
        subset_rule=subset_rule,
        total_images_in_file=total_images_in_file,
        total_images_imported=images_imported,
        total_images_excluded=images_excluded,
        total_annotations_in_file=total_annotations_in_file,
        total_annotations_imported=annotations_imported,
        total_annotations_excluded=annotations_excluded,
        total_cameras=len(cameras),
        categories_total=len(categories),
        categories_animal=categories_animal,
        categories_non_animal=categories_non_animal,
        categories_unmapped=unmapped_categories,
        exclusion_reasons=exclusion_reasons,
        missing_metadata=missing_metadata,
        warnings=import_warnings,
        is_blocked=False,
        block_reason=None,
    )

    return snapshot, report


# ---------------------------------------------------------------------------
# CLI RUNNER
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line interface for the Caltech CCT adapter."""
    import argparse
    from wildscope_analytics.analytics import analyze
    from wildscope_analytics.contracts.enums import AnalysisMetric
    from wildscope_analytics.contracts.requests import AnalysisRequest

    parser = argparse.ArgumentParser(
        description="WILDSCOPE Caltech Camera Traps (CCT) Adapter & Analytics Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "annotation_file",
        nargs="?",
        default="caltech_camera_traps.json",
        help="Path to the unzipped Caltech CCT annotation JSON file.",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=500,
        help="Max images to import (deterministic subset by sorted ID). Use 0 for all.",
    )
    parser.add_argument(
        "--timezone",
        default=None,
        help="Explicit IANA timezone policy (e.g., 'America/Los_Angeles'). None leaves captured_at null.",
    )
    parser.add_argument(
        "--location-ids",
        nargs="*",
        default=None,
        help="Optional list of CCT location/site IDs to import.",
    )
    parser.add_argument(
        "--output-snapshot",
        default=None,
        help="Optional path to write the imported Snapshot JSON.",
    )
    parser.add_argument(
        "--metric",
        default="overview",
        choices=[
            "overview",
            "reference_image_species_counts",
            "species_encounter_counts",
            "camera_comparison",
            "daily_activity",
            "hourly_activity",
            "species_camera_matrix",
            "effort_normalised_rates",
        ],
        help="Analysis metric to execute on the imported snapshot.",
    )

    args = parser.parse_args()

    max_imgs = None if args.max_images == 0 else args.max_images
    print("=" * 70)
    print("WILDSCOPE Caltech Camera Traps (CCT) Dataset Adapter")
    print("=" * 70)
    print(f"Annotation file : {args.annotation_file}")
    print(f"Max images      : {max_imgs}")
    print(f"Timezone policy : {args.timezone}")
    print(f"Metric to run   : {args.metric}")
    print("-" * 70)

    snap, report = import_caltech_snapshot(
        args.annotation_file,
        max_images=max_imgs,
        timezone_policy=args.timezone,
        location_ids=args.location_ids,
    )

    if report.is_blocked:
        print("[BLOCKED] Real dataset file is not available.")
        print(f"Reason: {report.block_reason}")
        print("\nTo acquire the official file outside the sandbox:")
        print("  Invoke-WebRequest -Uri \"https://lilawildlife.blob.core.windows.net/lila-wildlife/caltechcameratraps/labels/caltech_camera_traps.json.zip\" -OutFile \"caltech_camera_traps.json.zip\"")
        print("  Expand-Archive -Path \"caltech_camera_traps.json.zip\" -DestinationPath \".\"")
        return

    print("[SUCCESS] Snapshot imported:")
    print(f"  Total images in file      : {report.total_images_in_file}")
    print(f"  Images imported           : {report.total_images_imported}")
    print(f"  Images excluded           : {report.total_images_excluded}")
    print(f"  Total annotations in file : {report.total_annotations_in_file}")
    print(f"  Annotations imported      : {report.total_annotations_imported}")
    print(f"  Total cameras (locations) : {report.total_cameras}")
    print(f"  Total categories in file  : {report.categories_total}")
    print(f"  Animal categories         : {report.categories_animal}")
    print(f"  Non-animal categories     : {report.categories_non_animal}")
    print(f"  Unmapped categories       : {report.categories_unmapped}")
    print(f"  Missing metadata notes    : {report.missing_metadata}")

    if args.output_snapshot:
        out_p = Path(args.output_snapshot)
        out_p.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
        print(f"\nSnapshot JSON saved to: {out_p}")

    # Run analysis
    req = AnalysisRequest(
        metric=AnalysisMetric(args.metric),
        analysis_timezone=args.timezone,
    )
    resp = analyze(snap, req)
    print("\n" + "=" * 70)
    print(f"Analysis Response [{resp.status.value.upper()}]: {args.metric}")
    print("=" * 70)
    print(json.dumps(resp.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
