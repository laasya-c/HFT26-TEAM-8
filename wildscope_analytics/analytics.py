"""
WILDSCOPE Decision Intelligence & Analytics Module
Phase 2 Analytics Engine

Implements analyze(snapshot, request) with full cross-camera activity analytics.
rank_review() remains explicitly UNAVAILABLE (Phase 3 scope).

Public entry points (unchanged signature from Phase 1):
  analyze(snapshot, request)    → AnalysisResponseEnvelope
  rank_review(snapshot, request) → AnalysisResponseEnvelope  [UNAVAILABLE]

Internal components (not public API):
  resolve_effective_labels()     — shared deterministic review resolver
  compute_overview()             — Part F.1
  compute_species_encounter_counts() — Part F.2
  compute_camera_comparison()    — Part F.3
  compute_daily_activity()       — Part F.4
  compute_hourly_activity()      — Part F.5
  compute_species_camera_matrix() — Part F.6
  compute_effort_normalised_rates() — Part F.7

Design constraints honoured:
  - Encounter grouping is Harsh's domain; reuses encounter records, no re-grouping.
  - Raw predictions are never mutated.
  - Review ordering uses sequence_number when available, falls back to
    backend_revision policy (ambiguous ordering is reported, not guessed).
  - Reference annotations never receive invented confidence scores.
  - Effort is never inferred from image frequency.
  - Zero counts are distinct from unavailable data.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from wildscope_analytics.contracts.entities import BaseContractModel
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    DataSourceMode,
    EncounterProcessingStatus,
    InclusionPolicy,
    ResponseStatus,
    ReviewDecision,
    ReviewOrderingMechanism,
    TriageState,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import AnalysisRequest, ReviewRankingRequest
from wildscope_analytics.contracts.responses import AnalysisResponseEnvelope, ValidationErrorDetail
from wildscope_analytics.contracts.snapshot import CURRENT_SCHEMA_VERSION, Snapshot
from wildscope_analytics.validation import validate_snapshot_data

# ---------------------------------------------------------------------------
# SENTINEL CONSTANTS
# ---------------------------------------------------------------------------

_REJECTED_TAXON = "__rejected__"
_UNKNOWN_TAXON = "__unknown__"
_EMPTY_TAXON = "__empty__"
_UNRESOLVED_TAXON = "__unresolved__"
_MAX_EVIDENCE_SAMPLE = 10  # bounded evidence references per result


# ---------------------------------------------------------------------------
# PART A.5 — EFFECTIVE LABEL RESOLVER
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EffectiveLabel:
    """
    The resolved effective species label for one Detection.

    Fields:
      taxon_id       — resolved taxon ID, or one of the sentinels above.
      decision       — ReviewDecision applied, or None if no review.
      review_id      — ID of the winning ReviewEvent, or None.
      is_rejected    — True if the detection was rejected by review.
      is_unknown     — True if animal detected but species unknown/unresolvable.
      is_empty       — True if triage_state == LIKELY_EMPTY.
      is_unresolved  — True if multiple conflicting reviews with ambiguous ordering.
      conflict_note  — Human-readable conflict description if is_unresolved.
    """
    taxon_id: str | None
    decision: str | None
    review_id: str | None
    is_rejected: bool
    is_unknown: bool
    is_empty: bool
    is_unresolved: bool
    conflict_note: str | None


def resolve_effective_labels(
    snapshot: Snapshot,
) -> dict[str, EffectiveLabel]:
    """
    Resolves the effective taxon label for every Detection in the snapshot.

    Algorithm (per detection):
    1. If triage_state == LIKELY_EMPTY → effective label is empty (no species).
    2. Find all ReviewEvents whose target_id == detection.id.
    3. If none → provisional label from predicted_taxon_id (or _UNKNOWN_TAXON).
    4. If one review → apply its decision deterministically.
    5. If multiple reviews:
       a. If sequence_number present on all → use highest as authoritative.
       b. If review_ordering_mechanism == BACKEND_REVISION and sequence_number
          absent → report as UNRESOLVABLE (do not guess).
       c. If all reviews agree on identical decision+corrected_taxon_id → use it.
       d. Otherwise → mark is_unresolved, do not fabricate outcome.

    Returns:
      dict mapping detection.id → EffectiveLabel
      Raw Detection records are NOT mutated.
    """
    ordering_mechanism = snapshot.metadata.review_ordering_mechanism

    # Build index: detection_id → list[ReviewEvent]
    reviews_by_target: dict[str, list] = defaultdict(list)
    for rev in snapshot.reviews:
        reviews_by_target[rev.target_id].append(rev)

    result: dict[str, EffectiveLabel] = {}

    for det in snapshot.detections:
        det_reviews = reviews_by_target.get(det.id, [])

        # 1. Empty frame
        if det.triage_state == TriageState.LIKELY_EMPTY:
            result[det.id] = EffectiveLabel(
                taxon_id=_EMPTY_TAXON,
                decision=None,
                review_id=None,
                is_rejected=False,
                is_unknown=False,
                is_empty=True,
                is_unresolved=False,
                conflict_note=None,
            )
            continue

        # 2. No reviews → provisional prediction
        if not det_reviews:
            raw_taxon = det.predicted_taxon_id
            is_unk = raw_taxon is None or raw_taxon.strip() == ""
            result[det.id] = EffectiveLabel(
                taxon_id=raw_taxon if not is_unk else _UNKNOWN_TAXON,
                decision=None,
                review_id=None,
                is_rejected=False,
                is_unknown=is_unk,
                is_empty=False,
                is_unresolved=False,
                conflict_note=None,
            )
            continue

        # 3. Single review → deterministic
        if len(det_reviews) == 1:
            rev = det_reviews[0]
            result[det.id] = _apply_review(det, rev)
            continue

        # 4. Multiple reviews → ordering required
        winner_rev, conflict_note = _select_winning_review(
            det_reviews, ordering_mechanism
        )
        if winner_rev is None:
            # Unresolvable conflict
            result[det.id] = EffectiveLabel(
                taxon_id=_UNRESOLVED_TAXON,
                decision=None,
                review_id=None,
                is_rejected=False,
                is_unknown=False,
                is_empty=False,
                is_unresolved=True,
                conflict_note=conflict_note,
            )
        else:
            result[det.id] = _apply_review(det, winner_rev)

    return result


def _apply_review(det: Any, rev: Any) -> EffectiveLabel:
    """Apply a single winning ReviewEvent to produce an EffectiveLabel."""
    decision = rev.decision

    if decision == ReviewDecision.REJECT_DETECTION:
        return EffectiveLabel(
            taxon_id=_REJECTED_TAXON,
            decision=decision.value,
            review_id=rev.id,
            is_rejected=True,
            is_unknown=False,
            is_empty=False,
            is_unresolved=False,
            conflict_note=None,
        )
    if decision == ReviewDecision.CONFIRM_SPECIES:
        raw_taxon = det.predicted_taxon_id
        is_unk = raw_taxon is None or raw_taxon.strip() == ""
        return EffectiveLabel(
            taxon_id=raw_taxon if not is_unk else _UNKNOWN_TAXON,
            decision=decision.value,
            review_id=rev.id,
            is_rejected=False,
            is_unknown=is_unk,
            is_empty=False,
            is_unresolved=False,
            conflict_note=None,
        )
    if decision == ReviewDecision.CORRECT_SPECIES:
        corrected = rev.corrected_taxon_id
        is_unk = corrected is None or corrected.strip() == ""
        return EffectiveLabel(
            taxon_id=corrected if not is_unk else _UNKNOWN_TAXON,
            decision=decision.value,
            review_id=rev.id,
            is_rejected=False,
            is_unknown=is_unk,
            is_empty=False,
            is_unresolved=False,
            conflict_note=None,
        )
    if decision == ReviewDecision.MARK_UNKNOWN:
        return EffectiveLabel(
            taxon_id=_UNKNOWN_TAXON,
            decision=decision.value,
            review_id=rev.id,
            is_rejected=False,
            is_unknown=True,
            is_empty=False,
            is_unresolved=False,
            conflict_note=None,
        )
    if decision == ReviewDecision.FLAG_FOR_EXPERT:
        # Flagged: retain provisional prediction, note as pending expert
        raw_taxon = det.predicted_taxon_id
        is_unk = raw_taxon is None or raw_taxon.strip() == ""
        return EffectiveLabel(
            taxon_id=raw_taxon if not is_unk else _UNKNOWN_TAXON,
            decision=decision.value,
            review_id=rev.id,
            is_rejected=False,
            is_unknown=is_unk,
            is_empty=False,
            is_unresolved=False,
            conflict_note="flagged_for_expert_review",
        )
    # Unknown decision value (future-proofing)
    return EffectiveLabel(
        taxon_id=_UNRESOLVED_TAXON,
        decision=str(decision),
        review_id=rev.id,
        is_rejected=False,
        is_unknown=False,
        is_empty=False,
        is_unresolved=True,
        conflict_note=f"Unhandled review decision: {decision}",
    )


def _select_winning_review(
    reviews: list,
    mechanism: ReviewOrderingMechanism,
) -> tuple[Any | None, str | None]:
    """
    Select the authoritative review among multiple candidates.

    Returns (winning_review, None) or (None, conflict_note).
    """
    # Try sequence_number ordering first (most reliable)
    if all(r.sequence_number is not None for r in reviews):
        reviews_sorted = sorted(reviews, key=lambda r: r.sequence_number)
        # Highest sequence_number wins (most recent authoritative backend write)
        max_seq = reviews_sorted[-1].sequence_number
        tied = [r for r in reviews_sorted if r.sequence_number == max_seq]
        if len(tied) > 1:
            # Tied sequence_numbers indicate a backend bug (sequence_numbers must be
            # unique per-detection).  Santosh must fix.  We do NOT guess a winner.
            ids = [r.id for r in tied]
            return None, (
                f"Duplicate sequence_number {max_seq} on ReviewEvents {ids}. "
                f"sequence_number must be unique and monotonically increasing per detection. "
                f"Santosh must resolve this backend inconsistency before re-exporting the snapshot."
            )
        return reviews_sorted[-1], None

    # Check if all reviews agree (same decision + corrected_taxon_id)
    decisions = {(r.decision, r.corrected_taxon_id) for r in reviews}
    if len(decisions) == 1:
        # All agree, use any (pick first for determinism)
        return sorted(reviews, key=lambda r: r.id)[0], None

    # Mechanism-specific fallback
    if mechanism == ReviewOrderingMechanism.TIMESTAMP:
        # Only use timestamp ordering if explicitly configured; warn about risk
        # of sub-second ties or clock skew, but proceed
        try:
            reviews_sorted = sorted(reviews, key=lambda r: r.created_at)
            # Check for tied timestamps
            if reviews_sorted[-1].created_at == reviews_sorted[-2].created_at:
                ids = [r.id for r in reviews]
                return None, (
                    f"Multiple reviews with identical created_at timestamps and "
                    f"no sequence_number; ordering is ambiguous. Review IDs: {ids}"
                )
            return reviews_sorted[-1], None
        except Exception as exc:
            return None, f"Timestamp ordering failed: {exc}"

    # BACKEND_REVISION or UNRESOLVABLE without sequence_number → report conflict
    ids = [r.id for r in reviews]
    return None, (
        f"Multiple reviews exist for the same detection with conflicting decisions "
        f"and no sequence_number to resolve ordering deterministically. "
        f"Review IDs: {ids}. Santosh must supply sequence_number on ReviewEvent "
        f"or resolve at the backend before snapshot export."
    )


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

@dataclass
class FilterContext:
    """Mutable context tracking exclusion reasons during analytics computation."""
    excluded_count: int = 0
    exclusion_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def exclude(self, reason: str, count: int = 1) -> None:
        self.excluded_count += count
        if reason not in self.exclusion_reasons:
            self.exclusion_reasons.append(reason)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def limit(self, msg: str) -> None:
        if msg not in self.limitations:
            self.limitations.append(msg)


def _resolve_timezone(tz_str: str | None) -> ZoneInfo | None:
    """Resolve an IANA timezone string; return None if invalid or absent."""
    if not tz_str:
        return None
    try:
        return ZoneInfo(tz_str)
    except (ZoneInfoNotFoundError, Exception):
        return None


def _to_analysis_tz(dt: datetime | None, tz: ZoneInfo | None) -> datetime | None:
    """Convert a timezone-aware datetime to the analysis timezone."""
    if dt is None or tz is None:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(tz)


def _build_applied_filters(request: AnalysisRequest) -> dict[str, Any]:
    """Build a canonical applied_filters dict from a request."""
    return {
        "metric": request.metric.value,
        "species_ids": request.species_ids,
        "camera_ids": request.camera_ids,
        "site_ids": request.site_ids,
        "start_time": request.start_time.isoformat() if request.start_time else None,
        "end_time": request.end_time.isoformat() if request.end_time else None,
        "analysis_timezone": request.analysis_timezone,
        "inclusion_policy": request.inclusion_policy.value,
        "min_confidence": request.min_confidence,
    }


def _check_revision(snapshot: Snapshot, request: AnalysisRequest) -> AnalysisResponseEnvelope | None:
    """Return an INVALID_REQUEST envelope if the revision doesn't match, else None."""
    if (
        request.expected_revision is not None
        and request.expected_revision != snapshot.metadata.dataset_revision
    ):
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.metric,
            applied_filters={"expected_revision": request.expected_revision},
            errors=[
                ValidationErrorDetail(
                    code=ValidationErrorCode.SCHEMA_VIOLATION,
                    message=(
                        f"Expected revision {request.expected_revision} does not match "
                        f"snapshot dataset revision {snapshot.metadata.dataset_revision}."
                    ),
                    field_path="expected_revision",
                )
            ],
            limitations=["Dataset revision conflict (optimistic lock mismatch)."],
        )
    return None


def _filter_cameras(snapshot: Snapshot, request: AnalysisRequest) -> set[str]:
    """Return the set of camera IDs in scope for this request."""
    all_ids = {c.id for c in snapshot.cameras}
    if request.camera_ids is not None:
        return all_ids & set(request.camera_ids)
    if request.site_ids is not None:
        site_set = set(request.site_ids)
        return {c.id for c in snapshot.cameras if c.site_id in site_set}
    return all_ids


def _is_detection_eligible(
    det_id: str,
    labels: dict[str, EffectiveLabel],
    request: AnalysisRequest,
) -> bool:
    """Check if a detection passes inclusion policy and confidence filters."""
    label = labels.get(det_id)
    if label is None:
        return False
    # Guard: rejected, empty, or unresolved detections never contribute to analytics.
    # Unresolved detections have taxon_id == _UNRESOLVED_TAXON; allowing them through
    # would silently inject a sentinel value into species counts.
    if label.is_rejected or label.is_empty or label.is_unresolved:
        return False
    # InclusionPolicy filter
    if request.inclusion_policy == InclusionPolicy.REVIEWED_ONLY:
        if label.review_id is None:
            return False
    return True


def _encounter_timestamp(enc: Any) -> datetime | None:
    """Best available timestamp for an encounter (start preferred, else end)."""
    return enc.start_time or enc.end_time


def _is_in_time_window(
    ts: datetime | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    """Start-inclusive, end-exclusive time window check."""
    if ts is None:
        return False
    if start is not None and ts < start:
        return False
    if end is not None and ts >= end:
        return False
    return True


def _sample_evidence(ids: list[str]) -> list[str]:
    """Return a bounded deterministic sample from a list of IDs."""
    unique = list(dict.fromkeys(ids))  # preserve insertion order, deduplicate
    return unique[:_MAX_EVIDENCE_SAMPLE]


def _check_encounter_capability(
    snapshot: Snapshot,
    metric: AnalysisMetric,
    request: AnalysisRequest | ReviewRankingRequest,
    ctx: FilterContext,
) -> AnalysisResponseEnvelope | None:
    """
    Distinguishes encounter capability states (Part A.1):
    1. snapshot.encounters has records -> completed grouping with encounters. Returns None (proceed).
    2. encounter_processing_status == COMPLETED and encounters == []:
       Grouping completed with zero encounters!
       Returns None (proceed; function will compute valid zero counts).
    3. encounter_processing_status == PENDING:
       Grouping in-progress/pending in Harsh's pipeline.
       Returns UNAVAILABLE with limitation.
    4. encounter_processing_status == FAILED:
       Grouping failed in Harsh's pipeline.
       Returns UNAVAILABLE with limitation.
    5. encounter_processing_status in (UNAVAILABLE, None) and encounters == []:
       Conservative compatibility: grouping unavailable or legacy snapshot without metadata.
       Returns UNAVAILABLE with limitation.
    """
    if snapshot.encounters:
        return None

    status = snapshot.metadata.encounter_processing_status

    if status == EncounterProcessingStatus.COMPLETED:
        # Completed with 0 encounters -> valid empty dataset
        return None

    applied_filters = (
        _build_applied_filters(request)
        if isinstance(request, AnalysisRequest)
        else {"target_metric": request.target_metric.value}
    )

    if status == EncounterProcessingStatus.PENDING:
        ctx.limit(
            "Encounter grouping is PENDING / in-progress in Harsh's pipeline. "
            "Encounter-dependent metrics are UNAVAILABLE until grouping completes."
        )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=metric if isinstance(metric, AnalysisMetric) else None,
            applied_filters=applied_filters,
            result=None,
            limitations=ctx.limitations,
            warnings=ctx.warnings,
        )

    if status == EncounterProcessingStatus.FAILED:
        ctx.limit(
            "Encounter grouping FAILED during pipeline execution in Harsh's pipeline. "
            "Encounter-dependent metrics are UNAVAILABLE."
        )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=metric if isinstance(metric, AnalysisMetric) else None,
            applied_filters=applied_filters,
            result=None,
            limitations=ctx.limitations,
            warnings=ctx.warnings,
        )

    # status is UNAVAILABLE or None (legacy compatibility)
    ctx.limit(
        "No encounter records in snapshot. "
        "Encounter-based metrics are UNAVAILABLE until Harsh's group_encounters() output "
        "is included. (Conservative compatibility: missing metadata does not declare grouping complete)."
    )
    return AnalysisResponseEnvelope(
        status=ResponseStatus.UNAVAILABLE,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=metric if isinstance(metric, AnalysisMetric) else None,
        applied_filters=applied_filters,
        result=None,
        limitations=ctx.limitations,
        warnings=ctx.warnings,
    )


# ---------------------------------------------------------------------------
# PART F.1 — OVERVIEW
# ---------------------------------------------------------------------------

class OverviewResult(BaseContractModel):
    """Overview of the snapshot: encounter/image counts, cameras, time coverage."""
    data_source_mode: str
    counting_unit: str
    total_encounters: int | None = None
    encounters_unavailable_reason: str | None = None
    total_images_or_observations: int
    total_cameras_in_scope: int
    total_cameras_in_snapshot: int
    cameras_without_gps: int
    cameras_without_timezone: int
    time_coverage_start: str | None = None
    time_coverage_end: str | None = None
    time_coverage_note: str | None = None
    total_detections: int
    total_reference_annotations: int
    total_reviews: int
    detections_classified: int
    detections_rejected: int
    detections_unknown_species: int
    detections_unresolved: int
    detections_empty_frames: int
    dataset_revision: int
    schema_version: str
    applied_filters_summary: dict[str, Any]
    limitations: list[str]
    note: str = (
        "Encounter counts represent grouped temporal sessions, not unique individual animals. "
        "Unknown/unresolved categories are overlapping indicators, not mutually exclusive partitions."
    )


def compute_overview(
    snapshot: Snapshot,
    request: AnalysisRequest,
    labels: dict[str, EffectiveLabel],
    scoped_camera_ids: set[str],
    ctx: FilterContext,
) -> AnalysisResponseEnvelope:
    """Part F.1: Compute overview summary."""
    source_mode = snapshot.metadata.data_source_mode

    # Encounter count
    scoped_encounters = [e for e in snapshot.encounters if e.camera_id in scoped_camera_ids]
    # Filter by time window
    time_filtered_encounters = []
    for enc in scoped_encounters:
        ts = _encounter_timestamp(enc)
        if request.start_time or request.end_time:
            if not _is_in_time_window(ts, request.start_time, request.end_time):
                if ts is None:
                    ctx.exclude("Encounter missing timestamp; excluded from time-windowed count")
                else:
                    ctx.exclude("Encounter outside requested time window")
                continue
        time_filtered_encounters.append(enc)

    total_encounters = len(time_filtered_encounters)
    encounters_note = None
    enc_status = snapshot.metadata.encounter_processing_status
    if not snapshot.encounters:
        if enc_status == EncounterProcessingStatus.COMPLETED:
            total_encounters = 0
            encounters_note = None
        elif enc_status == EncounterProcessingStatus.PENDING:
            total_encounters = None
            encounters_note = "Encounter grouping is PENDING in Harsh's pipeline; encounter count unavailable."
        elif enc_status == EncounterProcessingStatus.FAILED:
            total_encounters = None
            encounters_note = "Encounter grouping FAILED in Harsh's pipeline; encounter count unavailable."
        else:
            total_encounters = None
            encounters_note = "No encounter records in snapshot; encounter count unavailable."
            if source_mode == DataSourceMode.DATASET_REFERENCE:
                encounters_note = (
                    "Dataset-reference mode: CCT annotations are image-level. "
                    "Encounter count requires Harsh's group_encounters() output applied to reference images."
                )

    # Observation/image counts
    scoped_obs = [o for o in snapshot.observations if o.camera_id in scoped_camera_ids]

    # Time coverage
    timestamps = []
    for obs in snapshot.observations:
        if obs.captured_at:
            timestamps.append(obs.captured_at)
    for enc in snapshot.encounters:
        if enc.start_time:
            timestamps.append(enc.start_time)
        if enc.end_time:
            timestamps.append(enc.end_time)
    time_start = min(timestamps).isoformat() if timestamps else None
    time_end = max(timestamps).isoformat() if timestamps else None

    # Detection status summaries
    classified = rejected = unknown = unresolved = empty_frames = 0
    for det in snapshot.detections:
        lbl = labels.get(det.id)
        if lbl is None:
            continue
        if lbl.is_empty:
            empty_frames += 1
        elif lbl.is_rejected:
            rejected += 1
        elif lbl.is_unresolved:
            unresolved += 1
        elif lbl.is_unknown:
            unknown += 1
        else:
            classified += 1

    has_enc_capability = bool(snapshot.encounters) or enc_status == EncounterProcessingStatus.COMPLETED
    result = OverviewResult(
        data_source_mode=source_mode.value,
        counting_unit="encounter" if has_enc_capability else "image/observation",
        total_encounters=total_encounters if has_enc_capability else None,
        encounters_unavailable_reason=encounters_note,
        total_images_or_observations=len(scoped_obs),
        total_cameras_in_scope=len(scoped_camera_ids),
        total_cameras_in_snapshot=len(snapshot.cameras),
        cameras_without_gps=sum(1 for c in snapshot.cameras if c.latitude is None),
        cameras_without_timezone=sum(1 for c in snapshot.cameras if c.timezone is None),
        time_coverage_start=time_start,
        time_coverage_end=time_end,
        time_coverage_note=None if timestamps else "No timestamped records found.",
        total_detections=len(snapshot.detections),
        total_reference_annotations=len(snapshot.reference_annotations),
        total_reviews=len(snapshot.reviews),
        detections_classified=classified,
        detections_rejected=rejected,
        detections_unknown_species=unknown,
        detections_unresolved=unresolved,
        detections_empty_frames=empty_frames,
        dataset_revision=snapshot.metadata.dataset_revision,
        schema_version=snapshot.metadata.schema_version,
        applied_filters_summary=_build_applied_filters(request),
        limitations=ctx.limitations.copy(),
    )

    status = ResponseStatus.OK
    if ctx.excluded_count > 0:
        status = ResponseStatus.PARTIAL

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.OVERVIEW,
        applied_filters=_build_applied_filters(request),
        result=result.model_dump(mode="json"),
        metric_units="counts",
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


# ---------------------------------------------------------------------------
# PART F.2 — SPECIES ENCOUNTER COUNTS
# ---------------------------------------------------------------------------

class SpeciesEncounterEntry(BaseContractModel):
    """Per-species encounter count with evidence."""
    taxon_id: str
    display_label: str
    encounter_count: int
    evidence_encounter_ids: list[str]
    evidence_sample_note: str | None = None


class SpeciesEncounterResult(BaseContractModel):
    """Deduplicated species × encounter count result."""
    data_source_mode: str
    counting_unit: str = (
        "deduplicated encounter/species pairs; one encounter may contribute to multiple species"
    )
    species_entries: list[SpeciesEncounterEntry]
    unknown_animal_encounters: int
    rejected_detections_excluded: int
    unresolved_detections_count: int
    empty_frame_detections_excluded: int
    total_eligible_encounters: int
    multi_species_encounters: int
    note: str = (
        "Summed species encounter counts may exceed total_eligible_encounters "
        "because multi-species encounters contribute once per species. "
        "This does not imply multiple individuals."
    )


def compute_species_encounter_counts(
    snapshot: Snapshot,
    request: AnalysisRequest,
    labels: dict[str, EffectiveLabel],
    scoped_camera_ids: set[str],
    ctx: FilterContext,
) -> AnalysisResponseEnvelope:
    """Part F.2: Deduplicated species × encounter counts."""
    source_mode = snapshot.metadata.data_source_mode

    if source_mode == DataSourceMode.DATASET_REFERENCE:
        ctx.warn(
            "DEPRECATION: Calling 'species_encounter_counts' on dataset_reference data is deprecated. "
            "Use 'reference_image_species_counts' instead. Reference counts reflect annotated images, not encounters."
        )
        return _species_counts_reference_mode(
            snapshot, request, scoped_camera_ids, ctx, metric=AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS
        )

    enc_cap_err = _check_encounter_capability(snapshot, AnalysisMetric.SPECIES_ENCOUNTER_COUNTS, request, ctx)
    if enc_cap_err:
        return enc_cap_err

    # Build detection index
    det_map = {d.id: d for d in snapshot.detections}
    obs_map = {o.id: o for o in snapshot.observations}

    species_to_encounter_ids: dict[str, set[str]] = defaultdict(set)
    unknown_enc_ids: set[str] = set()
    rejected_count = 0
    unresolved_count = 0
    empty_count = 0
    eligible_encounter_ids: set[str] = set()
    multi_species_encounter_ids: set[str] = set()

    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_camera_ids:
            continue
        ts = _encounter_timestamp(enc)
        if not _is_in_time_window(ts, request.start_time, request.end_time):
            if ts is not None:
                ctx.exclude("Encounter outside requested time window")
            else:
                ctx.exclude("Encounter missing timestamp; excluded from time-windowed scope")
            continue

        eligible_encounter_ids.add(enc.id)
        # Collect effective taxon IDs for this encounter (from member detections)
        enc_taxa: set[str] = set()

        for det_id in enc.member_detection_ids:
            det = det_map.get(det_id)
            if det is None:
                continue
            lbl = labels.get(det_id)
            if lbl is None:
                continue

            # Apply inclusion policy and confidence filter
            if not _is_detection_eligible(det_id, labels, request):
                if lbl.is_unresolved:
                    unresolved_count += 1
                    ctx.exclude("Detection has unresolved conflicting review decisions")
                elif lbl.is_rejected:
                    rejected_count += 1
                elif lbl.is_empty:
                    empty_count += 1
                elif request.inclusion_policy == InclusionPolicy.REVIEWED_ONLY and lbl.review_id is None:
                    ctx.exclude("Detection excluded by REVIEWED_ONLY inclusion policy")
                continue

            if lbl.is_unknown:
                enc_taxa.add(_UNKNOWN_TAXON)
                continue

            # Apply min_confidence filter (only for operational predictions)
            if request.min_confidence > 0.0:
                conf = det.classification_confidence
                if conf is not None and conf < request.min_confidence:
                    ctx.exclude(
                        f"Detection below min_confidence threshold {request.min_confidence}"
                    )
                    continue

            # Apply species_ids filter
            if request.species_ids is not None and lbl.taxon_id not in request.species_ids:
                continue

            if lbl.taxon_id:
                enc_taxa.add(lbl.taxon_id)

        # Accumulate per-species encounter counts
        animal_taxa = {t for t in enc_taxa if t != _UNKNOWN_TAXON}
        if enc_taxa:
            if _UNKNOWN_TAXON in enc_taxa:
                unknown_enc_ids.add(enc.id)
            for taxon in animal_taxa:
                species_to_encounter_ids[taxon].add(enc.id)
            if len(animal_taxa) > 1:
                multi_species_encounter_ids.add(enc.id)

    # Build result entries
    species_entries = []
    for taxon_id in sorted(species_to_encounter_ids.keys()):
        enc_ids = sorted(species_to_encounter_ids[taxon_id])
        sample = _sample_evidence(enc_ids)
        species_entries.append(SpeciesEncounterEntry(
            taxon_id=taxon_id,
            display_label=taxon_id,
            encounter_count=len(enc_ids),
            evidence_encounter_ids=sample,
            evidence_sample_note=(
                f"Showing {len(sample)} of {len(enc_ids)} encounters."
                if len(enc_ids) > _MAX_EVIDENCE_SAMPLE else None
            ),
        ))

    result = SpeciesEncounterResult(
        data_source_mode=source_mode.value,
        species_entries=species_entries,
        unknown_animal_encounters=len(unknown_enc_ids),
        rejected_detections_excluded=rejected_count,
        unresolved_detections_count=unresolved_count,
        empty_frame_detections_excluded=empty_count,
        total_eligible_encounters=len(eligible_encounter_ids),
        multi_species_encounters=len(multi_species_encounter_ids),
    )

    status = ResponseStatus.OK
    if ctx.excluded_count > 0 or unresolved_count > 0:
        status = ResponseStatus.PARTIAL

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
        applied_filters=_build_applied_filters(request),
        result=result.model_dump(mode="json"),
        metric_units="deduplicated encounter/species pairs",
        evidence_references=_sample_evidence(sorted(eligible_encounter_ids)),
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


def _species_counts_reference_mode(
    snapshot: Snapshot,
    request: AnalysisRequest,
    scoped_camera_ids: set[str],
    ctx: FilterContext,
    metric: AnalysisMetric = AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS,
) -> AnalysisResponseEnvelope:
    """
    Species counts for dataset_reference mode.
    Uses image-level reference annotations, NOT encounters.
    Returns clearly labelled image-level reference metrics.
    """
    obs_map = {o.id: o for o in snapshot.observations}

    # Filter scoped observations
    animal_categories: dict[str, int] = defaultdict(int)  # wildscope_taxon_id → image count
    unknown_images = 0
    empty_images = 0
    non_animal_images = 0
    total_scoped_images = 0
    evidence_obs_ids: list[str] = []

    for ann in snapshot.reference_annotations:
        obs = obs_map.get(ann.observation_id)
        if obs is None:
            ctx.exclude("Reference annotation references missing observation")
            continue
        if obs.camera_id not in scoped_camera_ids:
            continue
        ts = obs.captured_at
        if request.start_time or request.end_time:
            if not _is_in_time_window(ts, request.start_time, request.end_time):
                if ts is None:
                    ctx.exclude("Reference annotation observation missing timestamp")
                else:
                    ctx.exclude("Reference annotation outside requested time window")
                continue

        total_scoped_images += 1
        evidence_obs_ids.append(ann.observation_id)

        if ann.is_empty:
            empty_images += 1
            continue
        if not ann.is_animal:
            non_animal_images += 1
            continue

        taxon = ann.wildscope_taxon_id
        if taxon is None:
            unknown_images += 1
            continue

        if request.species_ids is not None and taxon not in request.species_ids:
            continue

        animal_categories[taxon] += 1

    species_entries = [
        SpeciesEncounterEntry(
            taxon_id=taxon,
            display_label=taxon,
            encounter_count=count,  # image-level count, not encounters
            evidence_encounter_ids=[],
            evidence_sample_note="Image-level reference count (not encounter-based)",
        )
        for taxon, count in sorted(animal_categories.items())
    ]

    ctx.limit(
        "Dataset-reference mode: counts are image-level annotations, NOT encounter-based. "
        "Encounter-based counts require Harsh's group_encounters() applied to this dataset."
    )

    result = {
        "data_source_mode": DataSourceMode.DATASET_REFERENCE.value,
        "counting_unit": "annotated_images (reference annotations, not encounters)",
        "species_entries": [e.model_dump() for e in species_entries],
        "unknown_animal_images": unknown_images,
        "empty_images_excluded": empty_images,
        "non_animal_images_excluded": non_animal_images,
        "total_scoped_images": total_scoped_images,
        "note": (
            "These are ground-truth reference annotation counts from the official dataset. "
            "They are NOT model prediction accuracy metrics and NOT encounter counts."
        ),
    }

    status = ResponseStatus.PARTIAL if ctx.excluded_count > 0 else ResponseStatus.OK

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=metric,
        applied_filters=_build_applied_filters(request),
        result=result,
        metric_units="annotated images (reference mode)",
        evidence_references=_sample_evidence(evidence_obs_ids),
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


# ---------------------------------------------------------------------------
# PART F.3 — CAMERA/SITE COMPARISON
# ---------------------------------------------------------------------------

class CameraComparisonRow(BaseContractModel):
    """Per-camera encounter summary."""
    camera_id: str
    site_id: str | None
    total_encounters: int
    species_breakdown: dict[str, int]
    has_gps: bool
    has_timezone: bool


class CameraComparisonResult(BaseContractModel):
    """Camera-level species encounter comparison."""
    data_source_mode: str
    counting_unit: str
    cameras: list[CameraComparisonRow]
    cameras_missing_from_encounters: list[str]
    note: str = "Zero counts are valid observed values for cameras with no detections in scope."


def compute_camera_comparison(
    snapshot: Snapshot,
    request: AnalysisRequest,
    labels: dict[str, EffectiveLabel],
    scoped_camera_ids: set[str],
    ctx: FilterContext,
) -> AnalysisResponseEnvelope:
    """Part F.3: Per-camera/site encounter and species breakdown."""
    source_mode = snapshot.metadata.data_source_mode
    det_map = {d.id: d for d in snapshot.detections}
    cam_map = {c.id: c for c in snapshot.cameras}

    # Guard: encounter capability check
    enc_cap_err = _check_encounter_capability(snapshot, AnalysisMetric.CAMERA_COMPARISON, request, ctx)
    if enc_cap_err:
        return enc_cap_err

    camera_to_encounters: dict[str, list] = defaultdict(list)
    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_camera_ids:
            continue
        ts = _encounter_timestamp(enc)
        if not _is_in_time_window(ts, request.start_time, request.end_time):
            if ts is not None:
                ctx.exclude("Encounter outside time window (camera comparison)")
            continue
        camera_to_encounters[enc.camera_id].append(enc)

    rows = []
    cameras_with_no_encounters = []

    for cam_id in sorted(scoped_camera_ids):
        cam = cam_map.get(cam_id)
        enc_list = camera_to_encounters.get(cam_id, [])
        if not enc_list:
            cameras_with_no_encounters.append(cam_id)

        species_counts: dict[str, int] = defaultdict(int)
        for enc in enc_list:
            enc_taxa: set[str] = set()
            for det_id in enc.member_detection_ids:
                if not _is_detection_eligible(det_id, labels, request):
                    continue
                lbl = labels.get(det_id)
                if lbl and not lbl.is_unknown and not lbl.is_unresolved and lbl.taxon_id:
                    if request.species_ids is None or lbl.taxon_id in request.species_ids:
                        enc_taxa.add(lbl.taxon_id)
            for taxon in enc_taxa:
                species_counts[taxon] += 1

        rows.append(CameraComparisonRow(
            camera_id=cam_id,
            site_id=cam.site_id if cam else None,
            total_encounters=len(enc_list),
            species_breakdown=dict(species_counts),
            has_gps=cam.latitude is not None if cam else False,
            has_timezone=cam.timezone is not None if cam else False,
        ))

    result = CameraComparisonResult(
        data_source_mode=source_mode.value,
        counting_unit="deduplicated encounter/species pairs per camera",
        cameras=rows,
        cameras_missing_from_encounters=cameras_with_no_encounters,
    )

    status = ResponseStatus.OK
    if ctx.excluded_count > 0:
        status = ResponseStatus.PARTIAL

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.CAMERA_COMPARISON,
        applied_filters=_build_applied_filters(request),
        result=result.model_dump(mode="json"),
        metric_units="encounter count per camera",
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


# ---------------------------------------------------------------------------
# PART F.4 — DAILY RECORDED ACTIVITY
# ---------------------------------------------------------------------------

class DailyActivityResult(BaseContractModel):
    """Encounter counts grouped by calendar date in the analysis timezone."""
    data_source_mode: str
    analysis_timezone: str
    timestamp_policy: str = (
        "Uses encounter start_time; falls back to end_time. "
        "Encounters without timestamps are excluded and counted separately."
    )
    date_counts: dict[str, int]  # ISO date string → count
    encounters_excluded_missing_timestamp: int
    counting_unit: str = "encounters per calendar day"


def compute_daily_activity(
    snapshot: Snapshot,
    request: AnalysisRequest,
    labels: dict[str, EffectiveLabel],
    scoped_camera_ids: set[str],
    ctx: FilterContext,
) -> AnalysisResponseEnvelope:
    """Part F.4: Daily recorded encounter activity."""
    tz_str = request.analysis_timezone
    tz = _resolve_timezone(tz_str)
    if tz_str and tz is None:
        ctx.warn(f"analysis_timezone '{tz_str}' is not a valid IANA timezone; defaulting to UTC.")
        tz = ZoneInfo("UTC")
        tz_str = "UTC"
    if tz is None:
        tz = ZoneInfo("UTC")
        tz_str = "UTC (default; no analysis_timezone supplied)"
        ctx.warn(
            "No analysis_timezone supplied. Defaulting to UTC. "
            "Set request.analysis_timezone to a valid IANA timezone for local-time daily grouping."
        )

    enc_cap_err = _check_encounter_capability(snapshot, AnalysisMetric.DAILY_ACTIVITY, request, ctx)
    if enc_cap_err:
        return enc_cap_err

    date_counts: dict[str, int] = defaultdict(int)
    missing_ts = 0

    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_camera_ids:
            continue
        ts = _encounter_timestamp(enc)
        if ts is None:
            missing_ts += 1
            ctx.exclude("Encounter missing timestamp; excluded from daily activity")
            continue
        if not _is_in_time_window(ts, request.start_time, request.end_time):
            ctx.exclude("Encounter outside requested time window (daily activity)")
            continue
        local_ts = ts.astimezone(tz)
        date_key = local_ts.date().isoformat()
        date_counts[date_key] += 1

    result = DailyActivityResult(
        data_source_mode=snapshot.metadata.data_source_mode.value,
        analysis_timezone=tz_str,
        date_counts=dict(sorted(date_counts.items())),
        encounters_excluded_missing_timestamp=missing_ts,
    )

    if missing_ts > 0 and len(date_counts) == 0:
        # All scoped encounters lacked timestamps; inadequate data for temporal daily activity
        status = ResponseStatus.INSUFFICIENT_DATA
        ctx.limit("All scoped encounters lack timestamps; data is insufficient for daily activity grouping.")
    elif missing_ts > 0 or ctx.excluded_count > 0:
        status = ResponseStatus.PARTIAL
    else:
        status = ResponseStatus.OK

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.DAILY_ACTIVITY,
        applied_filters=_build_applied_filters(request),
        result=result.model_dump(mode="json"),
        metric_units="encounters per calendar day",
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


# ---------------------------------------------------------------------------
# PART F.5 — HOUR-OF-DAY RECORDED ACTIVITY
# ---------------------------------------------------------------------------

class HourlyActivityResult(BaseContractModel):
    """Encounter counts grouped by hour-of-day (0–23) in the analysis timezone."""
    data_source_mode: str
    analysis_timezone: str
    timestamp_policy: str = (
        "Uses encounter start_time; falls back to end_time. "
        "Hour bins 0–23 use the analysis timezone. Zero in a bin means zero recorded encounters."
    )
    hour_counts: dict[str, int]  # "00"–"23" → count
    encounters_excluded_missing_timestamp: int
    counting_unit: str = "encounters per hour-of-day bin"
    note: str = (
        "These counts reflect recorded encounter events, not biological activity probabilities. "
        "Camera monitoring coverage affects detectability by time-of-day."
    )


def compute_hourly_activity(
    snapshot: Snapshot,
    request: AnalysisRequest,
    labels: dict[str, EffectiveLabel],
    scoped_camera_ids: set[str],
    ctx: FilterContext,
) -> AnalysisResponseEnvelope:
    """Part F.5: Hour-of-day recorded activity bins (0–23)."""
    tz_str = request.analysis_timezone
    tz = _resolve_timezone(tz_str)
    if tz_str and tz is None:
        ctx.warn(f"analysis_timezone '{tz_str}' is not valid; defaulting to UTC.")
        tz = ZoneInfo("UTC")
        tz_str = "UTC"
    if tz is None:
        tz = ZoneInfo("UTC")
        tz_str = "UTC (default)"
        ctx.warn(
            "No analysis_timezone supplied. Defaulting to UTC. "
            "Specify request.analysis_timezone for local-time diurnal analysis."
        )

    enc_cap_err = _check_encounter_capability(snapshot, AnalysisMetric.HOURLY_ACTIVITY, request, ctx)
    if enc_cap_err:
        return enc_cap_err

    # Initialize all 24 bins to zero (zero ≠ unavailable)
    hour_counts: dict[str, int] = {f"{h:02d}": 0 for h in range(24)}
    missing_ts = 0

    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_camera_ids:
            continue
        ts = _encounter_timestamp(enc)
        if ts is None:
            missing_ts += 1
            ctx.exclude("Encounter missing timestamp; excluded from hourly activity")
            continue
        if not _is_in_time_window(ts, request.start_time, request.end_time):
            ctx.exclude("Encounter outside time window (hourly activity)")
            continue
        local_ts = ts.astimezone(tz)
        hour_key = f"{local_ts.hour:02d}"
        hour_counts[hour_key] += 1

    result = HourlyActivityResult(
        data_source_mode=snapshot.metadata.data_source_mode.value,
        analysis_timezone=tz_str,
        hour_counts=hour_counts,
        encounters_excluded_missing_timestamp=missing_ts,
    )

    if missing_ts > 0 and sum(hour_counts.values()) == 0:
        # All scoped encounters lacked timestamps; inadequate data for temporal hourly activity
        status = ResponseStatus.INSUFFICIENT_DATA
        ctx.limit("All scoped encounters lack timestamps; data is insufficient for hourly activity grouping.")
    elif missing_ts > 0 or ctx.excluded_count > 0:
        status = ResponseStatus.PARTIAL
    else:
        status = ResponseStatus.OK

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.HOURLY_ACTIVITY,
        applied_filters=_build_applied_filters(request),
        result=result.model_dump(mode="json"),
        metric_units="encounters per hour-of-day bin (0–23)",
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


# ---------------------------------------------------------------------------
# PART F.6 — SPECIES × CAMERA MATRIX
# ---------------------------------------------------------------------------

class SpeciesCameraMatrixResult(BaseContractModel):
    """Species-by-camera encounter count matrix."""
    data_source_mode: str
    counting_unit: str = "deduplicated encounter/species pairs per camera"
    cameras: list[str]
    species: list[str]
    matrix: list[list[int]]  # matrix[species_idx][camera_idx]
    note: str = (
        "Each cell is the count of encounters at that camera with at least one detection "
        "of that species (deduplicated). Multi-species encounters contribute to each column."
    )


def compute_species_camera_matrix(
    snapshot: Snapshot,
    request: AnalysisRequest,
    labels: dict[str, EffectiveLabel],
    scoped_camera_ids: set[str],
    ctx: FilterContext,
) -> AnalysisResponseEnvelope:
    """Part F.6: Species × camera count matrix."""
    enc_cap_err = _check_encounter_capability(snapshot, AnalysisMetric.SPECIES_CAMERA_MATRIX, request, ctx)
    if enc_cap_err:
        return enc_cap_err

    # Build species × camera set contributions
    species_camera: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))

    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_camera_ids:
            continue
        ts = _encounter_timestamp(enc)
        if not _is_in_time_window(ts, request.start_time, request.end_time):
            if ts is not None:
                ctx.exclude("Encounter outside time window (matrix)")
            continue

        for det_id in enc.member_detection_ids:
            if not _is_detection_eligible(det_id, labels, request):
                continue
            lbl = labels.get(det_id)
            if lbl and not lbl.is_unknown and not lbl.is_unresolved and lbl.taxon_id:
                if request.species_ids is None or lbl.taxon_id in request.species_ids:
                    species_camera[lbl.taxon_id][enc.camera_id].add(enc.id)

    sorted_species = sorted(species_camera.keys())
    sorted_cameras = sorted(scoped_camera_ids)

    matrix = []
    for sp in sorted_species:
        row = []
        for cam in sorted_cameras:
            row.append(len(species_camera[sp].get(cam, set())))
        matrix.append(row)

    result = SpeciesCameraMatrixResult(
        data_source_mode=snapshot.metadata.data_source_mode.value,
        cameras=sorted_cameras,
        species=sorted_species,
        matrix=matrix,
    )

    status = ResponseStatus.OK
    if ctx.excluded_count > 0:
        status = ResponseStatus.PARTIAL

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.SPECIES_CAMERA_MATRIX,
        applied_filters=_build_applied_filters(request),
        result=result.model_dump(mode="json"),
        metric_units="encounter count per (species, camera) pair",
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


# ---------------------------------------------------------------------------
# PART F.7 — EFFORT-NORMALISED ENCOUNTER RATES
# ---------------------------------------------------------------------------

class CameraEffortRateRow(BaseContractModel):
    """Per-camera effort-normalised encounter rate."""
    camera_id: str
    active_camera_days_in_window: float
    encounters_in_effort: int
    encounters_outside_effort: int
    rate_per_camera_day: float | None
    rate_unavailable_reason: str | None = None


class EffortNormalisedRatesResult(BaseContractModel):
    """Effort-normalised encounter rates: encounters per active camera-day."""
    data_source_mode: str
    counting_unit: str = "encounters per active camera-day (1 camera-day = 24 hours active)"
    analysis_time_window_start: str | None
    analysis_time_window_end: str | None
    camera_rates: list[CameraEffortRateRow]
    cameras_without_effort: list[str]
    total_active_camera_days: float
    total_encounters_in_effort: int
    overall_rate_per_camera_day: float | None
    note: str = (
        "Active camera-days are computed from verified monitoring effort intervals, "
        "clipped to the requested time window. Effort is NEVER inferred from image frequency."
    )


def compute_effort_normalised_rates(
    snapshot: Snapshot,
    request: AnalysisRequest,
    labels: dict[str, EffectiveLabel],
    scoped_camera_ids: set[str],
    ctx: FilterContext,
) -> AnalysisResponseEnvelope:
    """Part F.7: Effort-normalised encounter rates."""
    source_mode = snapshot.metadata.data_source_mode

    if not snapshot.monitoring_efforts:
        ctx.limit(
            "No monitoring effort records in snapshot. "
            "Effort-normalised rates are UNAVAILABLE without verified active intervals from Santosh. "
            "Never inferred from image frequency."
        )
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.EFFORT_NORMALISED_RATES,
            applied_filters=_build_applied_filters(request),
            limitations=ctx.limitations,
            warnings=ctx.warnings,
        )

    enc_cap_err = _check_encounter_capability(snapshot, AnalysisMetric.EFFORT_NORMALISED_RATES, request, ctx)
    if enc_cap_err:
        return enc_cap_err

    # Build effort index: camera_id → sorted list of (start, end) intervals
    effort_by_camera: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for eff in snapshot.monitoring_efforts:
        if eff.camera_id not in scoped_camera_ids:
            continue
        for interval in eff.active_intervals:
            effort_by_camera[eff.camera_id].append((interval.start, interval.end))

    # Sort and validate non-overlap (Phase 1 policy preserved)
    for cam_id in effort_by_camera:
        effort_by_camera[cam_id].sort(key=lambda x: x[0])

    # Build encounter index by camera
    encounters_by_camera: dict[str, list] = defaultdict(list)
    for enc in snapshot.encounters:
        if enc.camera_id in scoped_camera_ids:
            encounters_by_camera[enc.camera_id].append(enc)

    win_start = request.start_time
    win_end = request.end_time

    camera_rows = []
    cameras_without_effort = []
    total_camera_days = 0.0
    total_in_effort = 0

    for cam_id in sorted(scoped_camera_ids):
        intervals = effort_by_camera.get(cam_id, [])
        if not intervals:
            cameras_without_effort.append(cam_id)
            camera_rows.append(CameraEffortRateRow(
                camera_id=cam_id,
                active_camera_days_in_window=0.0,
                encounters_in_effort=0,
                encounters_outside_effort=len(encounters_by_camera.get(cam_id, [])),
                rate_per_camera_day=None,
                rate_unavailable_reason="No verified monitoring effort records for this camera.",
            ))
            continue

        # Clip intervals to window
        clipped_seconds = 0.0
        for (iv_start, iv_end) in intervals:
            clip_s = max(iv_start, win_start) if win_start else iv_start
            clip_e = min(iv_end, win_end) if win_end else iv_end
            if clip_e > clip_s:
                clipped_seconds += (clip_e - clip_s).total_seconds()

        camera_days = clipped_seconds / 86400.0
        total_camera_days += camera_days

        # Count encounters inside/outside effort
        in_effort = 0
        out_effort = 0
        for enc in encounters_by_camera.get(cam_id, []):
            ts = _encounter_timestamp(enc)
            if ts is None:
                ctx.exclude("Encounter missing timestamp; excluded from effort rate calculation")
                out_effort += 1
                continue
            # Check if ts falls within any clipped interval
            within = False
            for (iv_start, iv_end) in intervals:
                clip_s = max(iv_start, win_start) if win_start else iv_start
                clip_e = min(iv_end, win_end) if win_end else iv_end
                if clip_s <= ts < clip_e:
                    within = True
                    break
            if within:
                in_effort += 1
            else:
                out_effort += 1

        total_in_effort += in_effort

        if camera_days == 0.0:
            rate = None
            rate_reason = "Zero active camera-days in requested window; cannot compute rate."
        else:
            rate = in_effort / camera_days

        camera_rows.append(CameraEffortRateRow(
            camera_id=cam_id,
            active_camera_days_in_window=round(camera_days, 4),
            encounters_in_effort=in_effort,
            encounters_outside_effort=out_effort,
            rate_per_camera_day=round(rate, 4) if rate is not None else None,
            rate_unavailable_reason=rate_reason if camera_days == 0.0 else None,
        ))

    if cameras_without_effort:
        ctx.warn(
            f"Cameras without effort records (excluded from overall rate): {cameras_without_effort}"
        )

    overall_rate = (
        total_in_effort / total_camera_days
        if total_camera_days > 0 else None
    )

    result = EffortNormalisedRatesResult(
        data_source_mode=source_mode.value,
        analysis_time_window_start=win_start.isoformat() if win_start else None,
        analysis_time_window_end=win_end.isoformat() if win_end else None,
        camera_rates=camera_rows,
        cameras_without_effort=cameras_without_effort,
        total_active_camera_days=round(total_camera_days, 4),
        total_encounters_in_effort=total_in_effort,
        overall_rate_per_camera_day=round(overall_rate, 4) if overall_rate is not None else None,
    )

    if total_camera_days == 0.0:
        # Supplied effort records did not cover any active time in the analysis window
        status = ResponseStatus.INSUFFICIENT_DATA
        ctx.limit(
            "Supplied monitoring effort provides zero active camera-days in the requested analysis window; "
            "effort data is inadequate to compute encounter rates."
        )
    elif cameras_without_effort or ctx.excluded_count > 0:
        status = ResponseStatus.PARTIAL
    else:
        status = ResponseStatus.OK

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.EFFORT_NORMALISED_RATES,
        applied_filters=_build_applied_filters(request),
        result=result.model_dump(mode="json"),
        metric_units="encounters per active camera-day",
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=ctx.limitations,
    )


# ---------------------------------------------------------------------------
# MAIN DISPATCHER
# ---------------------------------------------------------------------------

_LEGACY_METRIC_MAP: dict[str, AnalysisMetric] = {
    AnalysisMetric.ACTIVITY_TIME_DISTRIBUTION.value: AnalysisMetric.HOURLY_ACTIVITY,
    AnalysisMetric.CROSS_CAMERA_ASSOCIATION.value: AnalysisMetric.CAMERA_COMPARISON,
    AnalysisMetric.CAMERA_ACTIVITY_SUMMARY.value: AnalysisMetric.OVERVIEW,
    AnalysisMetric.MONITORING_COVERAGE_SUMMARY.value: AnalysisMetric.EFFORT_NORMALISED_RATES,
}


def analyze(
    snapshot: Snapshot,
    request: AnalysisRequest,
) -> AnalysisResponseEnvelope:
    """
    Phase 2 analyze() entry point.

    Validates the snapshot, resolves effective labels, applies filters,
    and dispatches to the requested metric computation.

    Supported metrics:
      overview, species_encounter_counts, camera_comparison,
      daily_activity, hourly_activity, species_camera_matrix,
      effort_normalised_rates

    Legacy Phase 1 metric names are mapped:
      activity_time_distribution  → hourly_activity
      cross_camera_association    → camera_comparison
      camera_activity_summary     → overview
      monitoring_coverage_summary → effort_normalised_rates

    Returns AnalysisResponseEnvelope with typed result payload.
    rank_review() remains unavailable (Phase 3).
    """
    # --- Validate snapshot
    snap_report = validate_snapshot_data(snapshot)
    if not snap_report.is_valid:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.metric,
            applied_filters={"metric": request.metric.value},
            errors=snap_report.errors,
            warnings=snap_report.warnings,
            limitations=["Snapshot failed contract validation."],
        )

    # --- Revision check
    revision_error = _check_revision(snapshot, request)
    if revision_error:
        return revision_error

    # --- Resolve effective labels
    labels = resolve_effective_labels(snapshot)

    # --- Scoped cameras
    scoped_camera_ids = _filter_cameras(snapshot, request)

    # --- Resolve metric (map legacy names)
    metric = request.metric
    legacy_target = _LEGACY_METRIC_MAP.get(metric.value)
    ctx = FilterContext()
    if snap_report.warnings:
        ctx.warnings.extend(snap_report.warnings)

    if legacy_target is not None:
        ctx.warn(
            f"Metric '{metric.value}' is a Phase 1 legacy alias; "
            f"mapping to '{legacy_target.value}'."
        )
        metric = legacy_target

    # --- Dispatch
    if metric == AnalysisMetric.OVERVIEW:
        return compute_overview(snapshot, request, labels, scoped_camera_ids, ctx)
    if metric == AnalysisMetric.SPECIES_ENCOUNTER_COUNTS:
        return compute_species_encounter_counts(snapshot, request, labels, scoped_camera_ids, ctx)
    if metric == AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS:
        if snapshot.metadata.data_source_mode != DataSourceMode.DATASET_REFERENCE:
            ctx.limit("REFERENCE_IMAGE_SPECIES_COUNTS is only valid on dataset_reference snapshots.")
            return AnalysisResponseEnvelope(
                status=ResponseStatus.UNAVAILABLE,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=metric,
                applied_filters=_build_applied_filters(request),
                limitations=ctx.limitations,
                warnings=ctx.warnings,
            )
        return _species_counts_reference_mode(
            snapshot, request, scoped_camera_ids, ctx, metric=AnalysisMetric.REFERENCE_IMAGE_SPECIES_COUNTS
        )
    if metric == AnalysisMetric.CAMERA_COMPARISON:
        return compute_camera_comparison(snapshot, request, labels, scoped_camera_ids, ctx)
    if metric == AnalysisMetric.DAILY_ACTIVITY:
        return compute_daily_activity(snapshot, request, labels, scoped_camera_ids, ctx)
    if metric == AnalysisMetric.HOURLY_ACTIVITY:
        return compute_hourly_activity(snapshot, request, labels, scoped_camera_ids, ctx)
    if metric == AnalysisMetric.SPECIES_CAMERA_MATRIX:
        return compute_species_camera_matrix(snapshot, request, labels, scoped_camera_ids, ctx)
    if metric == AnalysisMetric.EFFORT_NORMALISED_RATES:
        return compute_effort_normalised_rates(snapshot, request, labels, scoped_camera_ids, ctx)

    # Unimplemented metric
    return AnalysisResponseEnvelope(
        status=ResponseStatus.UNAVAILABLE,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=request.metric,
        applied_filters=_build_applied_filters(request),
        limitations=[f"Metric '{request.metric.value}' is not implemented in Phase 2."],
    )


def rank_review(
    snapshot: Snapshot,
    request: ReviewRankingRequest,
) -> AnalysisResponseEnvelope:
    """
    Phase 3: Conclusion-sensitive review ranking entry point (Feature F18).
    Evaluates candidate detections by their marginal sensitivity on the target metric.
    """
    from wildscope_analytics.ranking import compute_review_ranking
    return compute_review_ranking(snapshot, request)
