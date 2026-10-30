"""
WILDSCOPE Decision Intelligence & Analytics Module
Phase 3: Conclusion-Sensitive Review Engine (Feature F18)

Implements rank_review(snapshot, request) using deterministic marginal sensitivity analysis.
Asks for each eligible candidate detection:
  "If a reviewer resolves this detection differently, how much could the selected analytical result change?"

Design principles:
- Deterministic sensitivity analysis; no ML model or LLM required.
- Reuses the identical effective-label resolution, encounter deduplication,
  and filtering rules as analyze().
- One-candidate-at-a-time marginal evaluation (explicitly NOT additive / joint intervals).
- Original snapshot, detection records, and review history are NEVER mutated.
- Reference-only snapshots return UNAVAILABLE (reference annotations are ground-truth labels, not uncertain predictions).
- Stable tie-breaking on detection ID.
- Explanations generated dynamically from computed values.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from wildscope_analytics.contracts.entities import Detection, Encounter, TaxonAlternative
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    DataSourceMode,
    EncounterProcessingStatus,
    InclusionPolicy,
    ResponseStatus,
    ReviewDecision,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import ReviewRankingRequest
from wildscope_analytics.contracts.responses import (
    AnalysisResponseEnvelope,
    EvaluatedAlternative,
    RankedCandidateResult,
    ReviewRankingResult,
    ValidationErrorDetail,
)
from wildscope_analytics.contracts.snapshot import CURRENT_SCHEMA_VERSION, Snapshot
from wildscope_analytics.validation import validate_snapshot_data
from wildscope_analytics.analytics import (
    FilterContext,
    resolve_effective_labels,
    _check_encounter_capability,
    _encounter_timestamp,
    _is_detection_eligible,
    _is_in_time_window,
    _sample_evidence,
)


def compute_review_ranking(
    snapshot: Snapshot,
    request: ReviewRankingRequest,
) -> AnalysisResponseEnvelope:
    """
    Computes conclusion-sensitive review ranking for unreviewed/uncertain detections.

    Supported target metrics:
    1. SPECIES_ENCOUNTER_COUNTS: sensitivity of focal species encounter count.
    2. CAMERA_COMPARISON: sensitivity of focal species encounter difference (camera_a - camera_b).

    Other metrics are explicitly deferred.
    """
    # 1. Validate snapshot contracts
    snap_report = validate_snapshot_data(snapshot)
    if not snap_report.is_valid:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.target_metric,
            applied_filters={"target_metric": request.target_metric.value},
            errors=snap_report.errors,
            warnings=snap_report.warnings,
            limitations=["Snapshot failed contract validation."],
        )

    # 2. Concurrency / revision check
    if (
        request.expected_revision is not None
        and request.expected_revision != snapshot.metadata.dataset_revision
    ):
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.target_metric,
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

    # 3. Reference-only guard
    if snapshot.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.target_metric,
            applied_filters={"target_metric": request.target_metric.value},
            limitations=[
                "Conclusion-sensitive review ranking is UNAVAILABLE on dataset_reference snapshots. "
                "Reference annotations are ground-truth labels, not uncertain model predictions. "
                "Operational review prioritization applies exclusively to operational_prediction data."
            ],
        )

    # 4. Target metric support check
    supported_metrics = (
        AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
        AnalysisMetric.CAMERA_COMPARISON,
    )
    if request.target_metric not in supported_metrics:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.target_metric,
            applied_filters={"target_metric": request.target_metric.value},
            limitations=[
                f"Conclusion-sensitive review ranking for '{request.target_metric.value}' is deferred. "
                "Supported target metrics are 'species_encounter_counts' and 'camera_comparison' (two-camera difference)."
            ],
        )

    # 5. Extract and validate target parameters
    target_species_id = request.target_species_id
    if not target_species_id and request.species_ids and len(request.species_ids) == 1:
        target_species_id = request.species_ids[0]

    if not target_species_id:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=request.target_metric,
            applied_filters={"target_metric": request.target_metric.value},
            errors=[
                ValidationErrorDetail(
                    code=ValidationErrorCode.INVALID_RANKING_TARGET,
                    message=(
                        "Review ranking requires a single focal species specified via "
                        "'target_species_id' or a single-item 'species_ids' list."
                    ),
                    field_path="target_species_id",
                )
            ],
            limitations=["Focal species parameter missing."],
        )

    camera_a = request.camera_id_a
    camera_b = request.camera_id_b
    if request.target_metric == AnalysisMetric.CAMERA_COMPARISON:
        if not camera_a and request.camera_ids and len(request.camera_ids) >= 1:
            camera_a = request.camera_ids[0]
        if not camera_b and request.camera_ids and len(request.camera_ids) >= 2:
            camera_b = request.camera_ids[1]

        cam_ids_in_snapshot = {c.id for c in snapshot.cameras}
        if not camera_a or not camera_b:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INVALID_REQUEST,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=request.target_metric,
                applied_filters={"target_metric": request.target_metric.value},
                errors=[
                    ValidationErrorDetail(
                        code=ValidationErrorCode.INVALID_RANKING_TARGET,
                        message=(
                            "Review ranking for CAMERA_COMPARISON requires two distinct cameras: "
                            "'camera_id_a' and 'camera_id_b'."
                        ),
                        field_path="camera_id_a",
                    )
                ],
                limitations=["Camera comparison requires two distinct camera identifiers."],
            )

        if camera_a == camera_b:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INVALID_REQUEST,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=request.target_metric,
                applied_filters={"camera_id_a": camera_a, "camera_id_b": camera_b},
                errors=[
                    ValidationErrorDetail(
                        code=ValidationErrorCode.INVALID_RANKING_TARGET,
                        message=f"camera_id_a ('{camera_a}') and camera_id_b ('{camera_b}') must be distinct.",
                        field_path="camera_id_b",
                    )
                ],
                limitations=["Camera comparison cannot evaluate identical cameras."],
            )

        if camera_a not in cam_ids_in_snapshot or camera_b not in cam_ids_in_snapshot:
            missing = [c for c in (camera_a, camera_b) if c not in cam_ids_in_snapshot]
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INVALID_REQUEST,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=request.target_metric,
                applied_filters={"camera_id_a": camera_a, "camera_id_b": camera_b},
                errors=[
                    ValidationErrorDetail(
                        code=ValidationErrorCode.BROKEN_REFERENCE,
                        message=f"Camera IDs {missing} not found in snapshot cameras.",
                        field_path="camera_ids",
                    )
                ],
                limitations=["Specified cameras do not exist in snapshot."],
            )

    # 6. Check encounter capability
    ctx = FilterContext()
    enc_err = _check_encounter_capability(snapshot, request.target_metric, request, ctx)
    if enc_err:
        return enc_err

    # 7. Resolve baseline effective labels
    labels = resolve_effective_labels(snapshot)

    # 8. Filter in-scope encounters & compute baseline metric
    if request.target_metric == AnalysisMetric.SPECIES_ENCOUNTER_COUNTS:
        scoped_cameras = (
            set(request.camera_ids)
            if request.camera_ids
            else {c.id for c in snapshot.cameras}
        )
    else:  # CAMERA_COMPARISON
        scoped_cameras = {camera_a, camera_b}

    in_scope_encounters: list[Encounter] = []
    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_cameras:
            continue
        ts = _encounter_timestamp(enc)
        if not _is_in_time_window(ts, request.start_time, request.end_time):
            continue
        in_scope_encounters.append(enc)

    # Determine which in-scope encounters contain target_species_id under baseline
    # An encounter contains target species if AT LEAST ONE eligible detection has effective label == target_species_id
    def _encounter_has_species(enc: Encounter, active_labels: dict[str, Any]) -> bool:
        for d_id in enc.member_detection_ids:
            lbl = active_labels.get(d_id)
            if lbl and not lbl.is_rejected and not lbl.is_empty and not lbl.is_unresolved:
                if request.inclusion_policy == InclusionPolicy.REVIEWED_ONLY and lbl.review_id is None:
                    continue
                if lbl.taxon_id == target_species_id:
                    return True
        return False

    baseline_enc_has_target: dict[str, bool] = {
        enc.id: _encounter_has_species(enc, labels) for enc in in_scope_encounters
    }

    if request.target_metric == AnalysisMetric.SPECIES_ENCOUNTER_COUNTS:
        baseline_value = float(sum(1 for has_target in baseline_enc_has_target.values() if has_target))
        metric_units = f"encounters of {target_species_id}"
    else:  # CAMERA_COMPARISON
        count_a = sum(
            1 for enc in in_scope_encounters
            if enc.camera_id == camera_a and baseline_enc_has_target[enc.id]
        )
        count_b = sum(
            1 for enc in in_scope_encounters
            if enc.camera_id == camera_b and baseline_enc_has_target[enc.id]
        )
        baseline_value = float(count_a - count_b)
        metric_units = f"encounter difference ({camera_a} - {camera_b}) for {target_species_id}"

    # 9. Evaluate candidate detections
    # Map detection_id → in-scope encounters containing it
    det_to_encounters: dict[str, list[Encounter]] = defaultdict(list)
    for enc in in_scope_encounters:
        for d_id in enc.member_detection_ids:
            det_to_encounters[d_id].append(enc)

    all_encounter_det_ids = {
        d_id for enc in snapshot.encounters for d_id in enc.member_detection_ids
    }

    evaluated_candidates: list[tuple[float, str, RankedCandidateResult]] = []
    total_detections_in_scope = 0
    excluded_candidates_count = 0

    for det in snapshot.detections:
        lbl = labels.get(det.id)
        if lbl is None:
            ctx.exclude("Detection not resolved in snapshot")
            excluded_candidates_count += 1
            continue

        # Exclude rejected, empty, or unresolvable detections
        if lbl.is_rejected or lbl.is_empty:
            excluded_candidates_count += 1
            continue
        if lbl.is_unresolved:
            ctx.exclude("Detection has ambiguous review conflict requiring backend sequence resolution")
            excluded_candidates_count += 1
            continue

        # Exclude finally resolved detections (confirm, correct, mark_unknown)
        if lbl.decision in (
            ReviewDecision.CONFIRM_SPECIES.value,
            ReviewDecision.CORRECT_SPECIES.value,
            ReviewDecision.MARK_UNKNOWN.value,
        ):
            excluded_candidates_count += 1
            continue

        # Check encounter membership
        member_encs = det_to_encounters.get(det.id, [])
        if not member_encs:
            excluded_candidates_count += 1
            continue

        total_detections_in_scope += 1

        # Check documented alternatives or parameter-enabled actions
        allow_unknown = bool(request.parameters.get("allow_unknown_alternative", False))
        allow_rejection = bool(request.parameters.get("allow_rejection_alternative", False))

        if not det.alternatives and not (allow_unknown or allow_rejection):
            excluded_candidates_count += 1
            continue

        # Check ambiguity margin threshold
        conf = det.classification_confidence
        if (
            conf is not None
            and det.alternatives
            and request.score_margin_threshold < 1.0
            and conf >= (1.0 - request.score_margin_threshold)
            and lbl.decision != ReviewDecision.FLAG_FOR_EXPERT.value
        ):
            sorted_alts = sorted(det.alternatives, key=lambda a: a.score, reverse=True)
            top_alt_score = sorted_alts[0].score if sorted_alts else 0.0
            margin = conf - top_alt_score
            if margin > request.score_margin_threshold:
                excluded_candidates_count += 1
                continue

        # Extract distinct alternative candidate outcomes
        seen_taxa = {lbl.taxon_id}
        valid_alts = []
        if det.alternatives:
            for alt in det.alternatives[:request.top_k_candidates]:
                t_id = alt.taxon_id
                if t_id and t_id.strip() != "" and t_id not in seen_taxa:
                    seen_taxa.add(t_id)
                    valid_alts.append(alt)

        # Allow explicit unknown or rejection alternatives if requested via parameters
        if allow_unknown:
            if "__unknown__" not in seen_taxa:
                seen_taxa.add("__unknown__")
                valid_alts.append(TaxonAlternative(taxon_id="__unknown__", score=0.0))

        if allow_rejection:
            if "__rejected__" not in seen_taxa:
                seen_taxa.add("__rejected__")
                valid_alts.append(TaxonAlternative(taxon_id="__rejected__", score=0.0))

        if not valid_alts:
            excluded_candidates_count += 1
            continue

        # 10. Perform isolated counterfactual sensitivity analysis for this candidate
        primary_enc = member_encs[0]
        evaluated_alts: list[EvaluatedAlternative] = []

        for alt in valid_alts:
            hypothetical_taxon = alt.taxon_id

            # Evaluate net change in encounter presence across candidate's member encounters
            net_enc_gain = 0
            for enc in member_encs:
                baseline_has = baseline_enc_has_target[enc.id]
                # In counterfactual: does enc contain target_species_id if det takes hypothetical_taxon?
                det_is_target = (hypothetical_taxon == target_species_id)
                other_has = any(
                    d_id != det.id
                    and _is_detection_eligible(d_id, labels, request)
                    and labels[d_id].taxon_id == target_species_id
                    for d_id in enc.member_detection_ids
                )
                cf_has = det_is_target or other_has

                if not baseline_has and cf_has:
                    net_enc_gain += 1
                elif baseline_has and not cf_has:
                    net_enc_gain -= 1

            # Compute counterfactual metric value and signed/absolute deltas
            if request.target_metric == AnalysisMetric.SPECIES_ENCOUNTER_COUNTS:
                cf_metric_val = baseline_value + net_enc_gain
                signed_delta = float(net_enc_gain)
            else:  # CAMERA_COMPARISON
                if primary_enc.camera_id == camera_a:
                    cf_metric_val = baseline_value + net_enc_gain
                    signed_delta = float(net_enc_gain)
                elif primary_enc.camera_id == camera_b:
                    cf_metric_val = baseline_value - net_enc_gain
                    signed_delta = float(-net_enc_gain)
                else:
                    cf_metric_val = baseline_value
                    signed_delta = 0.0

            abs_delta = abs(signed_delta)

            # Impact summary
            if signed_delta > 0:
                summary = (
                    f"Confirming as '{hypothetical_taxon}' increases metric by +{int(signed_delta)} "
                    f"({int(baseline_value)} -> {int(cf_metric_val)})"
                )
            elif signed_delta < 0:
                summary = (
                    f"Confirming as '{hypothetical_taxon}' decreases metric by {int(signed_delta)} "
                    f"({int(baseline_value)} -> {int(cf_metric_val)})"
                )
            else:
                summary = (
                    f"Confirming as '{hypothetical_taxon}' has 0 marginal impact on metric "
                    f"(remains {int(baseline_value)})"
                )

            evaluated_alts.append(
                EvaluatedAlternative(
                    taxon_id=hypothetical_taxon,
                    alternative_score=alt.score,
                    counterfactual_value=cf_metric_val,
                    signed_delta=signed_delta,
                    absolute_delta=abs_delta,
                    impact_summary=summary,
                )
            )

        max_impact = max(a.absolute_delta for a in evaluated_alts) if evaluated_alts else 0.0

        # Dynamic deterministic explanation
        best_alt = max(evaluated_alts, key=lambda a: (a.absolute_delta, a.signed_delta)) if evaluated_alts else None
        if best_alt and best_alt.absolute_delta > 0:
            change_dir = "add" if best_alt.signed_delta > 0 else "remove"
            explanation = (
                f"Resolving this detection as '{best_alt.taxon_id}' would {change_dir} an encounter "
                f"at Camera '{primary_enc.camera_id}' and change the selected metric from "
                f"{int(baseline_value)} to {int(best_alt.counterfactual_value)} (delta: {best_alt.signed_delta:+g})."
            )
        else:
            explanation = (
                f"Relabelling this detection across all evaluated alternatives has 0 marginal effect on the metric "
                f"(current encounter is already established by other detections or does not affect target species)."
            )

        candidate_obj = RankedCandidateResult(
            rank=1,  # updated to true final rank after sorting below
            detection_id=det.id,
            encounter_id=primary_enc.id,
            observation_id=det.observation_id,
            camera_id=primary_enc.camera_id,
            current_effective_label=lbl.taxon_id,
            current_prediction=det.predicted_taxon_id,
            current_confidence=det.classification_confidence,
            score_type=det.score_type.value if det.score_type else None,
            alternatives_evaluated=evaluated_alts,
            max_absolute_impact=max_impact,
            explanation=explanation,
        )

        evaluated_candidates.append((max_impact, det.id, candidate_obj))

    eligible_candidates_count = len(evaluated_candidates)

    # 11. Filter zero impact and rank descending by impact, with stable ID tie-break
    if not request.include_zero_impact:
        filtered_for_ranking = [c for c in evaluated_candidates if c[0] > 0]
    else:
        filtered_for_ranking = evaluated_candidates

    # Sort key: (-max_impact, detection_id ascending)
    filtered_for_ranking.sort(key=lambda item: (-item[0], item[1]))

    # Truncate by max_records_to_rank
    is_truncated = len(filtered_for_ranking) > request.max_records_to_rank
    returned_candidates_raw = filtered_for_ranking[:request.max_records_to_rank]

    final_candidates: list[RankedCandidateResult] = []
    for rank_idx, (_, _, cand) in enumerate(returned_candidates_raw, start=1):
        cand.rank = rank_idx
        final_candidates.append(cand)

    # Assemble response
    evidence_refs: list[str] = []
    for c in final_candidates:
        evidence_refs.append(c.detection_id)
        evidence_refs.append(c.encounter_id)
    evidence_sample = _sample_evidence(evidence_refs)

    ranking_result = ReviewRankingResult(
        target_metric=request.target_metric.value,
        target_species_id=target_species_id,
        metric_units=metric_units,
        baseline_value=baseline_value,
        camera_id_a=camera_a,
        camera_id_b=camera_b,
        total_detections_in_scope=total_detections_in_scope,
        eligible_candidates_count=eligible_candidates_count,
        ranked_candidates_count=len(final_candidates),
        excluded_candidates_count=excluded_candidates_count,
        candidates=final_candidates,
    )

    status = ResponseStatus.OK
    if is_truncated or ctx.excluded_count > 0:
        status = ResponseStatus.PARTIAL

    applied_filters = {
        "target_metric": request.target_metric.value,
        "target_species_id": target_species_id,
        "camera_id_a": camera_a,
        "camera_id_b": camera_b,
        "top_k_candidates": request.top_k_candidates,
        "score_margin_threshold": request.score_margin_threshold,
        "max_records_to_rank": request.max_records_to_rank,
        "include_zero_impact": request.include_zero_impact,
        "start_time": request.start_time.isoformat() if request.start_time else None,
        "end_time": request.end_time.isoformat() if request.end_time else None,
    }

    limitations = [
        "One-candidate-at-a-time marginal sensitivity analysis. Does NOT represent a joint uncertainty interval.",
        "Changes from multiple candidates are NOT additive due to encounter deduplication.",
        "Prioritization reflects potential impact on the selected metric only; not an intrinsic classification quality score.",
    ]
    if is_truncated:
        limitations.append(
            f"Results truncated to top {request.max_records_to_rank} records by max_records_to_rank."
        )

    return AnalysisResponseEnvelope(
        status=status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=request.target_metric,
        applied_filters=applied_filters,
        result=ranking_result.model_dump(mode="json"),
        metric_units=metric_units,
        evidence_references=evidence_sample,
        excluded_records_count=ctx.excluded_count,
        exclusion_reasons=ctx.exclusion_reasons,
        warnings=ctx.warnings,
        limitations=limitations,
    )
