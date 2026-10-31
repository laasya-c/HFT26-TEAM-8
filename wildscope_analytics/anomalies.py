"""
WILDSCOPE Decision Intelligence & Analytics Module
Phase 5: Activity Anomaly Indicators (Feature F12)

Identifies unusual recorded encounter activity for focal species at individual camera
traps relative to an adequate historical baseline.

CRITICAL INTERPRETATION:
Outputs are reviewable statistical indicators—not proof of population change,
migration, poaching, camera failure, or ecological causes. Unmonitored intervals,
seasonality, and detection probability variation must be evaluated before drawing
operational conclusions.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wildscope_analytics.contracts.entities import (
    BaseContractModel,
    Camera,
    Encounter,
    MonitoringEffort,
    TimeInterval,
)
from wildscope_analytics.contracts.enums import (
    AnalysisMetric,
    AnomalyOutcome,
    ComparabilityAssessment,
    DataSourceMode,
    EncounterProcessingStatus,
    InclusionPolicy,
    ResponseStatus,
    ValidationErrorCode,
)
from wildscope_analytics.contracts.requests import (
    ActivityAnomalyRequest,
    AnalysisRequest,
)
from wildscope_analytics.contracts.responses import (
    ActivityAnomaliesResult,
    ActivityAnomalySeriesResult,
    AnalysisResponseEnvelope,
    BaselineDailyBin,
    ValidationErrorDetail,
)
from wildscope_analytics.contracts.snapshot import CURRENT_SCHEMA_VERSION, Snapshot
from wildscope_analytics.validation import validate_snapshot_data


# ---------------------------------------------------------------------------
# HELPERS & PUBLIC INGESTION NORMALIZATION
# ---------------------------------------------------------------------------

def _encounter_timestamp(enc: Encounter) -> datetime | None:
    """Best available timestamp for an encounter (start preferred, else end)."""
    return enc.start_time or enc.end_time


def _diff_seconds(t2: datetime, t1: datetime) -> float:
    """Return physical duration between two timezone-aware datetimes in seconds (handles DST changes)."""
    return (t2.astimezone(timezone.utc) - t1.astimezone(timezone.utc)).total_seconds()


def _merge_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """Sort and merge overlapping or contiguous active monitoring intervals."""
    if not intervals:
        return []
    sorted_ivs = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = []
    for s, e in sorted_ivs:
        if e <= s:
            continue
        if not merged:
            merged.append((s, e))
        else:
            last_s, last_e = merged[-1]
            if s <= last_e:
                merged[-1] = (last_s, max(last_e, e))
            else:
                merged.append((s, e))
    return merged


def normalize_snapshot_efforts(snapshot: Snapshot) -> Snapshot:
    """
    Public ingestion normalization step:
    Resolves overlapping and contiguous active monitoring effort intervals for each camera
    into valid, disjoint MonitoringEffort records conforming to Phase 1 validation contracts.
    Preserves snapshot immutability by returning a new normalized Snapshot instance.
    """
    efforts_by_cam: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    source_by_cam: dict[str, str | None] = {}
    for eff in snapshot.monitoring_efforts:
        source_by_cam[eff.camera_id] = eff.source
        for iv in eff.active_intervals:
            if iv.end > iv.start:
                efforts_by_cam[eff.camera_id].append((iv.start, iv.end))

    new_efforts = []
    for idx, (cam_id, ivs) in enumerate(sorted(efforts_by_cam.items())):
        merged = _merge_intervals(ivs)
        new_eff = MonitoringEffort(
            id=f"norm_eff_{cam_id}_{idx}",
            camera_id=cam_id,
            active_intervals=[TimeInterval(start=s, end=e) for s, e in merged],
            source=source_by_cam.get(cam_id),
            completeness_notes="Normalized from raw monitoring logs by merge_intervals.",
        )
        new_efforts.append(new_eff)

    return snapshot.model_copy(update={"monitoring_efforts": new_efforts}, deep=True)


def _is_in_active_intervals(ts: datetime, intervals: list[tuple[datetime, datetime]]) -> bool:
    """Check if a timestamp falls within any active interval [s, e)."""
    for s, e in intervals:
        if s <= ts < e:
            return True
    return False


def _check_revision(
    snapshot: Snapshot,
    request: ActivityAnomalyRequest | AnalysisRequest,
) -> AnalysisResponseEnvelope | None:
    """Optimistic concurrency check against expected dataset revision."""
    if request.expected_revision is not None:
        actual_rev = snapshot.metadata.dataset_revision
        if actual_rev != request.expected_revision:
            return AnalysisResponseEnvelope(
                status=ResponseStatus.INVALID_REQUEST,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=actual_rev,
                metric=AnalysisMetric.ACTIVITY_ANOMALY,
                applied_filters={"expected_revision": request.expected_revision},
                errors=[
                    ValidationErrorDetail(
                        code=ValidationErrorCode.SCHEMA_VIOLATION,
                        message=(
                            f"Optimistic revision conflict: request expected revision "
                            f"{request.expected_revision}, but snapshot is at revision {actual_rev}."
                        ),
                        field_path="expected_revision",
                        entity_type="SnapshotMetadata",
                    )
                ],
                limitations=["Snapshot revision does not match expected_revision."],
            )
    return None


def _normalize_request(
    request: ActivityAnomalyRequest | AnalysisRequest | dict,
) -> tuple[ActivityAnomalyRequest | None, AnalysisResponseEnvelope | None]:
    """
    Normalizes an ActivityAnomalyRequest, AnalysisRequest, or dict into an ActivityAnomalyRequest.
    Returns (normalized_request, error_envelope).
    """
    if isinstance(request, ActivityAnomalyRequest):
        return request, None

    # AnalysisRequest or dict dispatch
    if isinstance(request, dict):
        params = request.get("parameters") or request
        req_start = request.get("start_time")
        req_end = request.get("end_time")
        species_ids = request.get("species_ids")
        camera_ids = request.get("camera_ids")
        site_ids = request.get("site_ids")
        metric_val = request.get("metric", AnalysisMetric.ACTIVITY_ANOMALY)
        inclusion_policy = request.get("inclusion_policy", InclusionPolicy.ALL_PROVISIONAL)
        min_confidence = request.get("min_confidence", 0.0)
        expected_revision = request.get("expected_revision")
    else:
        params = request.parameters or {}
        req_start = request.start_time
        req_end = request.end_time
        species_ids = request.species_ids
        camera_ids = request.camera_ids
        site_ids = request.site_ids
        metric_val = request.metric
        inclusion_policy = request.inclusion_policy
        min_confidence = request.min_confidence
        expected_revision = request.expected_revision

    b_start = params.get("baseline_start_time") or req_start
    b_end = params.get("baseline_end_time")
    e_start = params.get("evaluation_start_time")
    e_end = params.get("evaluation_end_time") or req_end

    missing = []
    if b_start is None:
        missing.append("baseline_start_time")
    if b_end is None:
        missing.append("baseline_end_time")
    if e_start is None:
        missing.append("evaluation_start_time")
    if e_end is None:
        missing.append("evaluation_end_time")

    if missing:
        err = ValidationErrorDetail(
            code=ValidationErrorCode.SCHEMA_VIOLATION,
            message=(
                f"Activity anomaly analysis requires explicit window boundaries. "
                f"Missing parameter(s): {', '.join(missing)}."
            ),
            field_path="parameters",
        )
        metric_enum = metric_val if isinstance(metric_val, AnalysisMetric) else AnalysisMetric.ACTIVITY_ANOMALY
        env = AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=0,
            metric=metric_enum,
            applied_filters={"metric": metric_enum.value},
            errors=[err],
            limitations=["Activity anomaly request missing window boundaries."],
        )
        return None, env

    # Parse ISO strings if provided as strings
    def _parse_ts(val: Any) -> datetime:
        if isinstance(val, str):
            return datetime.fromisoformat(val)
        return val

    try:
        norm_req = ActivityAnomalyRequest(
            metric=AnalysisMetric.ACTIVITY_ANOMALY,
            baseline_start_time=_parse_ts(b_start),
            baseline_end_time=_parse_ts(b_end),
            evaluation_start_time=_parse_ts(e_start),
            evaluation_end_time=_parse_ts(e_end),
            analysis_timezone=params.get("analysis_timezone", "UTC"),
            species_ids=species_ids,
            camera_ids=camera_ids,
            site_ids=site_ids,
            min_baseline_days=params.get("min_baseline_days", 7),
            min_baseline_active_effort_days=params.get("min_baseline_active_effort_days", 5.0),
            min_evaluation_active_effort_days=params.get("min_evaluation_active_effort_days", 1.0),
            min_day_coverage_ratio=params.get("min_day_coverage_ratio", 0.5),
            anomaly_threshold_sigmas=params.get("anomaly_threshold_sigmas", 3.0),
            min_absolute_rate_change=params.get("min_absolute_rate_change", 0.2),
            allow_zero_dispersion_absolute_fallback=params.get("allow_zero_dispersion_absolute_fallback", True),
            allow_suspect_comparability=params.get("allow_suspect_comparability", False),
            inclusion_policy=inclusion_policy,
            min_confidence=min_confidence,
            expected_revision=expected_revision,
            parameters=params,
        )
        return norm_req, None
    except Exception as exc:
        err = ValidationErrorDetail(
            code=ValidationErrorCode.SCHEMA_VIOLATION,
            message=str(exc),
            field_path="parameters",
        )
        metric_enum = metric_val if isinstance(metric_val, AnalysisMetric) else AnalysisMetric.ACTIVITY_ANOMALY
        env = AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=0,
            metric=metric_enum,
            applied_filters={"metric": metric_enum.value},
            errors=[err],
            limitations=["Activity anomaly request failed validation."],
        )
        return None, env


# ---------------------------------------------------------------------------
# CORE COMPUTATION ENGINE
# ---------------------------------------------------------------------------

def compute_activity_anomalies(
    snapshot: Snapshot,
    request: ActivityAnomalyRequest | AnalysisRequest,
) -> AnalysisResponseEnvelope:
    """
    Computes activity anomaly indicators for independent camera/species series (Feature F12).
    """
    # 1. Snapshot contract validation
    snap_report = validate_snapshot_data(snapshot)
    if not snap_report.is_valid:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.ACTIVITY_ANOMALY,
            applied_filters={"metric": AnalysisMetric.ACTIVITY_ANOMALY.value},
            errors=snap_report.errors,
            warnings=snap_report.warnings,
            limitations=["Snapshot failed contract validation."],
        )

    # 2. Source mode check: dataset_reference is UNAVAILABLE
    if snapshot.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.ACTIVITY_ANOMALY,
            applied_filters={
                "metric": AnalysisMetric.ACTIVITY_ANOMALY.value,
                "data_source_mode": snapshot.metadata.data_source_mode.value,
            },
            limitations=[
                "Activity anomaly indicators are UNAVAILABLE for raw reference datasets (DATASET_REFERENCE). "
                "Reference annotations lack operational encounters and verified monitoring effort intervals."
            ],
            warnings=snap_report.warnings,
        )

    # 3. Normalize request
    norm_request, err_env = _normalize_request(request)
    if err_env is not None:
        err_env.dataset_revision = snapshot.metadata.dataset_revision
        return err_env
    assert norm_request is not None

    # 4. Revision check
    rev_err = _check_revision(snapshot, norm_request)
    if rev_err is not None:
        return rev_err

    # 5. Monitoring effort check: must have verified effort records
    if not snapshot.monitoring_efforts:
        return AnalysisResponseEnvelope(
            status=ResponseStatus.UNAVAILABLE,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.ACTIVITY_ANOMALY,
            applied_filters={"metric": AnalysisMetric.ACTIVITY_ANOMALY.value},
            limitations=[
                "No monitoring effort records found in snapshot. "
                "Activity anomaly indicators are UNAVAILABLE without verified active intervals from Santosh. "
                "Effort is never inferred from image frequency or timestamps."
            ],
            warnings=snap_report.warnings,
        )

    # 6. Encounter grouping status check
    if not snapshot.encounters:
        status = snapshot.metadata.encounter_processing_status
        if status != EncounterProcessingStatus.COMPLETED:
            reason = "pending" if status == EncounterProcessingStatus.PENDING else "failed or unavailable"
            return AnalysisResponseEnvelope(
                status=ResponseStatus.UNAVAILABLE,
                schema_version=CURRENT_SCHEMA_VERSION,
                dataset_revision=snapshot.metadata.dataset_revision,
                metric=AnalysisMetric.ACTIVITY_ANOMALY,
                applied_filters={"metric": AnalysisMetric.ACTIVITY_ANOMALY.value},
                limitations=[f"Encounter grouping is {reason} in Harsh's pipeline; cannot evaluate activity anomalies."],
                warnings=snap_report.warnings,
            )

    # 7. Timezone setup
    try:
        tz = ZoneInfo(norm_request.analysis_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return AnalysisResponseEnvelope(
            status=ResponseStatus.INVALID_REQUEST,
            schema_version=CURRENT_SCHEMA_VERSION,
            dataset_revision=snapshot.metadata.dataset_revision,
            metric=AnalysisMetric.ACTIVITY_ANOMALY,
            applied_filters={"analysis_timezone": norm_request.analysis_timezone},
            errors=[
                ValidationErrorDetail(
                    code=ValidationErrorCode.SCHEMA_VIOLATION,
                    message=f"Unknown or invalid IANA timezone: '{norm_request.analysis_timezone}'.",
                    field_path="analysis_timezone",
                )
            ],
            limitations=["Invalid analysis_timezone."],
        )

    # 8. Resolve effective labels and scoped entities
    from wildscope_analytics.analytics import resolve_effective_labels
    labels = resolve_effective_labels(snapshot)
    det_map = {d.id: d for d in snapshot.detections}
    cam_map = {c.id: c for c in snapshot.cameras}

    # Camera scoping
    scoped_camera_ids: set[str] = set(cam_map.keys())
    if norm_request.site_ids is not None:
        site_cams = {c.id for c in snapshot.cameras if c.site_id in norm_request.site_ids}
        scoped_camera_ids &= site_cams
    if norm_request.camera_ids is not None:
        scoped_camera_ids &= set(norm_request.camera_ids)

    # Index active monitoring effort by camera
    camera_raw_efforts: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for eff in snapshot.monitoring_efforts:
        if eff.camera_id in scoped_camera_ids:
            for iv in eff.active_intervals:
                if iv.end > iv.start:
                    camera_raw_efforts[eff.camera_id].append((iv.start, iv.end))

    camera_merged_efforts: dict[str, list[tuple[datetime, datetime]]] = {
        cid: _merge_intervals(ivs) for cid, ivs in camera_raw_efforts.items()
    }

    # 9. Encounter indexing & species attribution per encounter
    # encounter_id -> set of focal species
    # encounter_id -> encounter
    enc_map: dict[str, Encounter] = {}
    enc_species_map: dict[str, set[str]] = defaultdict(set)
    discovered_species: set[str] = set()

    for enc in snapshot.encounters:
        if enc.camera_id not in scoped_camera_ids:
            continue
        enc_map[enc.id] = enc

        for det_id in enc.member_detection_ids:
            det = det_map.get(det_id)
            if det is None:
                continue
            lbl = labels.get(det_id)
            if lbl is None or lbl.is_rejected or lbl.is_empty or lbl.is_unresolved:
                continue
            if norm_request.inclusion_policy == InclusionPolicy.REVIEWED_ONLY and lbl.review_id is None:
                continue
            if norm_request.min_confidence > 0.0:
                conf = det.classification_confidence
                if conf is not None and conf < norm_request.min_confidence:
                    continue
            if lbl.taxon_id:
                enc_species_map[enc.id].add(lbl.taxon_id)
                discovered_species.add(lbl.taxon_id)

    # Determine species list to evaluate
    if norm_request.species_ids is not None:
        focal_species_list = sorted(set(norm_request.species_ids))
    else:
        focal_species_list = sorted(discovered_species)

    # Group encounters by camera
    encounters_by_camera: dict[str, list[Encounter]] = defaultdict(list)
    for enc in enc_map.values():
        encounters_by_camera[enc.camera_id].append(enc)

    # 10. Generate calendar days for baseline window
    b_start_local = norm_request.baseline_start_time.astimezone(tz)
    b_end_local = norm_request.baseline_end_time.astimezone(tz)
    cur_date = b_start_local.date()
    end_date = b_end_local.date()

    calendar_days: list[tuple[datetime, datetime, str, float]] = []
    while cur_date <= end_date:
        d_start = datetime(cur_date.year, cur_date.month, cur_date.day, 0, 0, 0, tzinfo=tz)
        next_d = cur_date + timedelta(days=1)
        d_end = datetime(next_d.year, next_d.month, next_d.day, 0, 0, 0, tzinfo=tz)

        # Full calendar day physical duration in seconds (exact for DST, e.g. 23h, 24h, 25h)
        full_day_nominal_s = _diff_seconds(d_end, d_start)

        # Slice to baseline window
        s_start = max(d_start, norm_request.baseline_start_time)
        s_end = min(d_end, norm_request.baseline_end_time)
        if s_end > s_start:
            calendar_days.append((s_start, s_end, cur_date.isoformat(), full_day_nominal_s))
        cur_date = next_d

    baseline_total_cal_days = len(calendar_days)

    # 11. Evaluate each independent camera/species series
    series_results: list[ActivityAnomalySeriesResult] = []
    global_warnings: list[str] = list(snap_report.warnings)

    for cam_id in sorted(scoped_camera_ids):
        cam = cam_map.get(cam_id)
        site_id = cam.site_id if cam else None
        active_intervals = camera_merged_efforts.get(cam_id, [])
        cam_encs = encounters_by_camera.get(cam_id, [])

        # Comparability assessment for this camera and snapshot
        comp_assessment, comp_notes = _assess_camera_comparability(cam, snapshot)

        for sp_id in focal_species_list:
            # Baseline daily binning
            daily_bins: list[BaselineDailyBin] = []
            out_of_effort_encs = 0

            # Find all encounters of this species at this camera
            sp_encs = [e for e in cam_encs if sp_id in enc_species_map.get(e.id, set())]

            for s_start, s_end, date_str, full_day_nominal_s in calendar_days:
                # Calculate active monitoring seconds on this day
                active_s = 0.0
                for iv_s, iv_e in active_intervals:
                    overlap_s = max(iv_s, s_start)
                    overlap_e = min(iv_e, s_end)
                    if overlap_e > overlap_s:
                        active_s += _diff_seconds(overlap_e, overlap_s)

                active_cam_days = active_s / 86400.0
                # Coverage ratio is evaluated against the full local calendar-day duration
                cov_ratio = (active_s / full_day_nominal_s) if full_day_nominal_s > 0 else 0.0
                cov_ratio = min(1.0, max(0.0, cov_ratio))

                is_valid_day = (
                    cov_ratio >= norm_request.min_day_coverage_ratio and active_cam_days > 0.0
                )

                # Count encounters in this day
                day_enc_count = 0
                for enc in sp_encs:
                    ts = _encounter_timestamp(enc)
                    if ts is None:
                        continue
                    if s_start <= ts < s_end:
                        if _is_in_active_intervals(ts, active_intervals):
                            day_enc_count += 1
                        else:
                            out_of_effort_encs += 1

                if is_valid_day:
                    daily_rate = day_enc_count / active_cam_days
                else:
                    daily_rate = None

                daily_bins.append(
                    BaselineDailyBin(
                        date=date_str,
                        active_seconds=round(active_s, 3),
                        active_camera_days=round(active_cam_days, 5),
                        coverage_ratio=round(cov_ratio, 4),
                        is_valid_baseline_day=is_valid_day,
                        encounter_count=day_enc_count,
                        daily_encounter_rate=round(daily_rate, 4) if daily_rate is not None else None,
                    )
                )

            # Valid baseline statistics
            valid_bins = [b for b in daily_bins if b.is_valid_baseline_day]
            num_valid_days = len(valid_bins)
            base_total_effort_days = sum(b.active_camera_days for b in valid_bins)

            eval_notes: list[str] = []
            is_baseline_sufficient = (
                num_valid_days >= norm_request.min_baseline_days
                and base_total_effort_days >= norm_request.min_baseline_active_effort_days
            )

            if num_valid_days > 0:
                valid_rates = [b.daily_encounter_rate for b in valid_bins if b.daily_encounter_rate is not None]
                median_rate = statistics.median(valid_rates)
                deviations = [abs(r - median_rate) for r in valid_rates]
                mad = statistics.median(deviations)
                # Note: MAD = 0 indicates that at least 50% of the baseline values equal the median
                # (e.g. in [0, 0, 0, 0, 1, 2, 3], median=0, MAD=0), not that all values are identical.
                sigma = 1.4826 * mad
            else:
                median_rate = None
                mad = None
                sigma = None

            # Evaluation window calculation
            e_win_start = norm_request.evaluation_start_time
            e_win_end = norm_request.evaluation_end_time
            e_win_nominal_seconds = _diff_seconds(e_win_end, e_win_start)

            eval_active_s = 0.0
            for iv_s, iv_e in active_intervals:
                overlap_s = max(iv_s, e_win_start)
                overlap_e = min(iv_e, e_win_end)
                if overlap_e > overlap_s:
                    eval_active_s += _diff_seconds(overlap_e, overlap_s)

            eval_effort_days = eval_active_s / 86400.0
            eval_cov_ratio = (eval_active_s / e_win_nominal_seconds) if e_win_nominal_seconds > 0 else 0.0
            eval_cov_ratio = min(1.0, max(0.0, eval_cov_ratio))

            is_eval_effort_ok = eval_effort_days >= norm_request.min_evaluation_active_effort_days
            is_eval_cov_ok = eval_cov_ratio >= norm_request.min_day_coverage_ratio
            is_eval_sufficient = is_eval_effort_ok and is_eval_cov_ok

            # Count evaluation encounters
            eval_enc_count = 0
            for enc in sp_encs:
                ts = _encounter_timestamp(enc)
                if ts is None:
                    continue
                if e_win_start <= ts < e_win_end:
                    if _is_in_active_intervals(ts, active_intervals):
                        eval_enc_count += 1
                    else:
                        out_of_effort_encs += 1

            if eval_effort_days > 0.0:
                eval_rate = eval_enc_count / eval_effort_days
            else:
                eval_rate = None

            if out_of_effort_encs > 0:
                eval_notes.append(
                    f"Excluded {out_of_effort_encs} encounter(s) recorded outside verified active effort intervals."
                )

            # Anomaly Classification
            outcome: AnomalyOutcome
            abs_change: float | None = None
            rel_change: float | None = None
            anomaly_score: float | None = None

            if not is_baseline_sufficient:
                outcome = AnomalyOutcome.NOT_EVALUABLE
                eval_notes.append(
                    f"Insufficient baseline history: {num_valid_days} valid days "
                    f"(minimum {norm_request.min_baseline_days} required) or {base_total_effort_days:.2f} "
                    f"camera-days (minimum {norm_request.min_baseline_active_effort_days:.2f} required)."
                )
            elif not is_eval_sufficient:
                outcome = AnomalyOutcome.NOT_EVALUABLE
                eval_fail_reasons = []
                if not is_eval_effort_ok:
                    eval_fail_reasons.append(
                        f"{eval_effort_days:.2f} active camera-days < {norm_request.min_evaluation_active_effort_days:.2f} required"
                    )
                if not is_eval_cov_ok:
                    eval_fail_reasons.append(
                        f"coverage ratio {eval_cov_ratio:.1%} < {norm_request.min_day_coverage_ratio:.1%} required"
                    )
                eval_notes.append(f"Insufficient evaluation coverage: {'; '.join(eval_fail_reasons)}.")
            elif comp_assessment == ComparabilityAssessment.SUSPECT_OR_CHANGED and not norm_request.allow_suspect_comparability:
                outcome = AnomalyOutcome.NOT_EVALUABLE
                eval_notes.append(
                    "Series is NOT_EVALUABLE under comparability policy: stationarity is SUSPECT_OR_CHANGED "
                    "(repositioning, hardware, or model change). Historical baseline is non-comparable to evaluation period. "
                    "Set allow_suspect_comparability=True to compute qualified indicators."
                )
            else:
                assert median_rate is not None
                assert eval_rate is not None
                abs_change = eval_rate - median_rate
                if median_rate > 0.0:
                    rel_change = abs_change / median_rate

                if sigma is not None and sigma > 0.0:
                    anomaly_score = abs_change / sigma

                # Evaluate thresholds
                if sigma is not None and sigma > 0.0:
                    assert anomaly_score is not None
                    if (
                        abs_change >= norm_request.min_absolute_rate_change
                        and anomaly_score >= norm_request.anomaly_threshold_sigmas
                    ):
                        outcome = AnomalyOutcome.INCREASED
                        eval_notes.append(
                            f"Heuristic rate increase indicator: +{abs_change:.3f} encounters/day "
                            f"(+{anomaly_score:.2f} sigmas >= {norm_request.anomaly_threshold_sigmas})."
                        )
                    elif (
                        abs_change <= -norm_request.min_absolute_rate_change
                        and anomaly_score <= -norm_request.anomaly_threshold_sigmas
                    ):
                        outcome = AnomalyOutcome.DECREASED
                        eval_notes.append(
                            f"Heuristic rate decrease indicator: {abs_change:.3f} encounters/day "
                            f"({anomaly_score:.2f} sigmas <= -{norm_request.anomaly_threshold_sigmas})."
                        )
                    else:
                        outcome = AnomalyOutcome.NO_INDICATOR
                        eval_notes.append(
                            "No anomaly indicator triggered: evaluation encounter rate within normal baseline dispersion."
                        )
                else:
                    # Zero baseline dispersion (MAD == 0.0)
                    if norm_request.allow_zero_dispersion_absolute_fallback:
                        if abs_change >= norm_request.min_absolute_rate_change:
                            outcome = AnomalyOutcome.INCREASED
                            eval_notes.append(
                                f"Zero baseline dispersion; rate increase +{abs_change:.3f} encounters/day "
                                f"breached absolute threshold ({norm_request.min_absolute_rate_change})."
                            )
                        elif abs_change <= -norm_request.min_absolute_rate_change:
                            outcome = AnomalyOutcome.DECREASED
                            eval_notes.append(
                                f"Zero baseline dispersion; rate decrease {abs_change:.3f} encounters/day "
                                f"breached absolute threshold (-{norm_request.min_absolute_rate_change})."
                            )
                        else:
                            outcome = AnomalyOutcome.NO_INDICATOR
                            eval_notes.append(
                                "Zero baseline dispersion; rate change did not breach minimum absolute threshold."
                            )
                    else:
                        outcome = AnomalyOutcome.NO_INDICATOR
                        eval_notes.append(
                            "Zero baseline dispersion and absolute fallback disabled; no indicator triggered."
                        )

                if comp_assessment == ComparabilityAssessment.SUSPECT_OR_CHANGED and norm_request.allow_suspect_comparability:
                    eval_notes.insert(
                        0,
                        "QUALIFIED_INDICATOR: Stationarity is SUSPECT_OR_CHANGED. Review indicator with caution."
                    )

            series_res = ActivityAnomalySeriesResult(
                camera_id=cam_id,
                species_id=sp_id,
                site_id=site_id,
                outcome=outcome,
                baseline_start_time=norm_request.baseline_start_time,
                baseline_end_time=norm_request.baseline_end_time,
                baseline_calendar_days_total=baseline_total_cal_days,
                baseline_valid_active_days=num_valid_days,
                baseline_total_active_effort_days=round(base_total_effort_days, 4),
                baseline_median_daily_rate=round(median_rate, 4) if median_rate is not None else None,
                baseline_mad_daily_rate=round(mad, 4) if mad is not None else None,
                baseline_dispersion_sigma=round(sigma, 4) if sigma is not None else None,
                evaluation_start_time=norm_request.evaluation_start_time,
                evaluation_end_time=norm_request.evaluation_end_time,
                evaluation_active_effort_days=round(eval_effort_days, 4),
                evaluation_encounter_count=eval_enc_count,
                evaluation_encounter_rate=round(eval_rate, 4) if eval_rate is not None else None,
                absolute_rate_change=round(abs_change, 4) if abs_change is not None else None,
                relative_rate_change=round(rel_change, 4) if rel_change is not None else None,
                anomaly_score_sigmas=round(anomaly_score, 4) if anomaly_score is not None else None,
                comparability_assessment=comp_assessment,
                comparability_notes=comp_notes,
                evaluation_notes=eval_notes,
                out_of_effort_encounters_count=out_of_effort_encs,
                baseline_daily_bins=daily_bins,
            )
            series_results.append(series_res)

    # 12. Determine envelope status & aggregate counts
    total_series = len(series_results)
    inc_count = sum(1 for s in series_results if s.outcome == AnomalyOutcome.INCREASED)
    dec_count = sum(1 for s in series_results if s.outcome == AnomalyOutcome.DECREASED)
    no_ind_count = sum(1 for s in series_results if s.outcome == AnomalyOutcome.NO_INDICATOR)
    not_eval_count = sum(1 for s in series_results if s.outcome == AnomalyOutcome.NOT_EVALUABLE)

    if total_series == 0 or not_eval_count == total_series:
        envelope_status = ResponseStatus.INSUFFICIENT_DATA
    elif not_eval_count > 0:
        envelope_status = ResponseStatus.PARTIAL
    else:
        envelope_status = ResponseStatus.OK

    limitations = [
        "Activity anomaly indicators are reviewable statistical signals, not ecological proof of population change.",
        "Unmonitored periods, weather conditions, seasonality, and detection probabilities must be considered.",
    ]
    if not_eval_count > 0:
        limitations.append(f"{not_eval_count} of {total_series} series had insufficient history or active effort.")

    result_payload = ActivityAnomaliesResult(
        data_source_mode=snapshot.metadata.data_source_mode.value,
        metric="activity_anomaly",
        analysis_timezone=norm_request.analysis_timezone,
        baseline_start_time=norm_request.baseline_start_time,
        baseline_end_time=norm_request.baseline_end_time,
        evaluation_start_time=norm_request.evaluation_start_time,
        evaluation_end_time=norm_request.evaluation_end_time,
        total_series_evaluated=total_series,
        increased_count=inc_count,
        decreased_count=dec_count,
        no_indicator_count=no_ind_count,
        not_evaluable_count=not_eval_count,
        series=series_results,
    )

    applied_filters = {
        "metric": AnalysisMetric.ACTIVITY_ANOMALY.value,
        "baseline_start_time": norm_request.baseline_start_time.isoformat(),
        "baseline_end_time": norm_request.baseline_end_time.isoformat(),
        "evaluation_start_time": norm_request.evaluation_start_time.isoformat(),
        "evaluation_end_time": norm_request.evaluation_end_time.isoformat(),
        "analysis_timezone": norm_request.analysis_timezone,
        "min_baseline_days": norm_request.min_baseline_days,
        "min_baseline_active_effort_days": norm_request.min_baseline_active_effort_days,
        "min_evaluation_active_effort_days": norm_request.min_evaluation_active_effort_days,
        "min_day_coverage_ratio": norm_request.min_day_coverage_ratio,
        "anomaly_threshold_sigmas": norm_request.anomaly_threshold_sigmas,
        "min_absolute_rate_change": norm_request.min_absolute_rate_change,
        "allow_zero_dispersion_absolute_fallback": norm_request.allow_zero_dispersion_absolute_fallback,
    }
    if norm_request.species_ids:
        applied_filters["species_ids"] = norm_request.species_ids
    if norm_request.camera_ids:
        applied_filters["camera_ids"] = norm_request.camera_ids
    if norm_request.site_ids:
        applied_filters["site_ids"] = norm_request.site_ids

    return AnalysisResponseEnvelope(
        status=envelope_status,
        schema_version=CURRENT_SCHEMA_VERSION,
        dataset_revision=snapshot.metadata.dataset_revision,
        metric=AnalysisMetric.ACTIVITY_ANOMALY,
        applied_filters=applied_filters,
        result=result_payload.model_dump(mode="json"),
        metric_units="encounters per active camera-day",
        warnings=global_warnings,
        limitations=limitations,
    )


def _assess_camera_comparability(
    camera: Camera | None,
    snapshot: Snapshot,
) -> tuple[ComparabilityAssessment, list[str]]:
    """
    Evaluates whether deployment, hardware, model run, and grouping remained stationary.
    Distinguishes camera hardware telemetry from prediction-run and grouping provenance.
    """
    notes: list[str] = []
    notes.append(
        "Exploratory heuristic indicator: standardized rate deviation ratio is not a calibrated "
        "significance level or p-value. Ecological factors (seasonality, weather) and detection probability "
        "variations may influence encounter rates."
    )

    change_signals: list[str] = []

    # 1. Camera telemetry & physical deployment provenance
    if camera is not None:
        md: dict[str, Any] = {}
        if isinstance(camera.provenance, dict):
            md = camera.provenance
        elif hasattr(camera, "metadata") and isinstance(camera.metadata, dict):
            md = camera.metadata

        for key in (
            "repositioned", "reposition", "hardware_change", "serviced",
            "moved", "lens_replaced", "deployment_change"
        ):
            if key in md and md[key]:
                change_signals.append(f"camera_telemetry:{key}={md[key]}")

    # 2. Prediction-run provenance (model version / checkpoint changes across runs)
    if snapshot.prediction_runs:
        model_versions = {
            p.model_version for p in snapshot.prediction_runs if p.model_version
        }
        if len(model_versions) > 1:
            change_signals.append(f"prediction_provenance:multiple_model_versions={sorted(model_versions)}")

    # 3. Grouping provenance
    if snapshot.metadata.encounter_processing_status == EncounterProcessingStatus.FAILED:
        change_signals.append("grouping_provenance:encounter_processing_failed")

    if change_signals:
        notes.append(f"Stationarity change detected: {', '.join(change_signals)}.")
        return ComparabilityAssessment.SUSPECT_OR_CHANGED, notes

    # 4. Affirmative, scoped provenance check
    # Note: Hardware/mount verification confirms physical stationarity of the device,
    # but does not guarantee full analytical comparability because environmental factors
    # (vegetation, seasonality, weather) and model/pipeline updates can alter detection probabilities.
    if camera is not None and isinstance(camera.provenance, dict):
        if (
            camera.provenance.get("stationarity_verified") is True
            and camera.provenance.get("verification_scope")
        ):
            scope = camera.provenance.get("verification_scope")
            notes.append(f"Stationarity affirmatively verified (scope: '{scope}').")
            return ComparabilityAssessment.VERIFIED_COMPARABLE, notes

    # 5. Absence of change records remains UNASSESSED
    notes.append("Deployment and pipeline stationarity unassessed; missing hardware/reposition audit telemetry.")
    return ComparabilityAssessment.UNASSESSED, notes
