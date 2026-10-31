"""
WILDSCOPE Phase 5: Activity Anomaly Indicators Tests (Feature F12)
==================================================================
Comprehensive test suite verifying statistical anomaly indicators against
historical baselines:
  1. Stable baseline without indicator (NO_INDICATOR)
  2. Injected rate increase triggering INCREASED
  3. Injected rate decrease triggering DECREASED
  4. Valid zero sightings with positive monitoring effort (rate = 0.0)
  5. Missing effort vs zero sightings (unobserved days excluded, not zero-filled)
  6. Insufficient baseline history (M < min_baseline_days) -> NOT_EVALUABLE
  7. Insufficient evaluation coverage (E_eval < min_eval_effort) -> NOT_EVALUABLE
  8. Partial monitoring days (coverage < 0.5 excluded)
  9. Overlapping effort protection (merged intervals, no double-counting)
  10. Out-of-effort observations counted and reported
  11. Zero baseline centre and zero baseline dispersion (MAD = 0 fallback)
  12. Minimum absolute change requirement preventing micro-alerts when dispersion is tiny
  13. Non-overlapping window validation
  14. Baseline leakage prevention (eval records do not alter baseline)
  15. Consistent timezone and calendar day boundaries across DST transitions
  16. Encounter/species deduplication per encounter
  17. Review correction modifying effective label at new revision
  18. Documented deployment/camera change flags -> SUSPECT_OR_CHANGED
  19. Raw reference dataset -> UNAVAILABLE
  20. Revision conflict -> INVALID_REQUEST
  21. Snapshot immutability
  22. Clean JSON serialization (no NaN or Infinity)
  23. Parity between analyze() and detect_activity_anomalies()
  24. Multiple cameras processed as independent series (no pooling)

All fixtures are hand-calculated SYNTHETIC TEST FIXTUREs.
"""

from __future__ import annotations

import copy
import json
import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pytest

from wildscope_analytics import (
    ActivityAnomaliesResult,
    ActivityAnomalyRequest,
    ActivityAnomalySeriesResult,
    AnalysisMetric,
    AnalysisRequest,
    AnalysisResponseEnvelope,
    AnomalyOutcome,
    Camera,
    ComparabilityAssessment,
    DataSourceMode,
    Detection,
    Encounter,
    EncounterProcessingStatus,
    InclusionPolicy,
    MonitoringEffort,
    Observation,
    ResponseStatus,
    ReviewDecision,
    ReviewEvent,
    Snapshot,
    SnapshotMetadata,
    TimeInterval,
    TriageState,
    ValidationErrorCode,
    analyze,
    detect_activity_anomalies,
)
from wildscope_analytics.contracts.enums import ReviewOrderingMechanism

UTC = timezone.utc
SYNTHETIC = "SYNTHETIC TEST FIXTURE"


# ---------------------------------------------------------------------------
# FIXTURE BUILDERS
# ---------------------------------------------------------------------------

def _meta(
    revision: int = 1,
    mode: DataSourceMode = DataSourceMode.OPERATIONAL_PREDICTION,
    status: EncounterProcessingStatus = EncounterProcessingStatus.COMPLETED,
) -> SnapshotMetadata:
    return SnapshotMetadata(
        schema_version="1.3.0",
        dataset_revision=revision,
        created_at=datetime.now(UTC),
        source_system="WILDSCOPE_PHASE5_TEST",
        data_source_mode=mode,
        review_ordering_mechanism=ReviewOrderingMechanism.BACKEND_REVISION,
        encounter_processing_status=status,
        provenance=SYNTHETIC,
    )


def _cam(cam_id: str, site_id: str | None = None, metadata: dict | None = None) -> Camera:
    return Camera(
        id=cam_id,
        latitude=34.0,
        longitude=-118.0,
        site_id=site_id,
        timezone="UTC",
        provenance=metadata if metadata is not None else SYNTHETIC,
    )


def _effort(cam_id: str, intervals: list[tuple[datetime, datetime]]) -> MonitoringEffort:
    return MonitoringEffort(
        id=f"eff_{cam_id}_{intervals[0][0].strftime('%Y%m%d%H%M')}",
        camera_id=cam_id,
        active_intervals=[TimeInterval(start=s, end=e) for s, e in intervals],
        source="ranger_log",
    )


def _encounter_with_species(
    enc_id: str,
    cam_id: str,
    species_id: str,
    start_time: datetime,
    end_time: datetime | None = None,
    num_detections: int = 1,
) -> tuple[Encounter, list[Observation], list[Detection]]:
    end_time = end_time or (start_time + timedelta(minutes=5))
    obs_list = []
    det_list = []
    det_ids = []

    for i in range(num_detections):
        obs_id = f"obs_{enc_id}_{i}"
        det_id = f"det_{enc_id}_{i}"
        det_ids.append(det_id)
        obs_list.append(
            Observation(
                id=obs_id,
                camera_id=cam_id,
                source_media_id=f"med_{obs_id}",
                captured_at=start_time + timedelta(seconds=i * 10),
            )
        )
        det_list.append(
            Detection(
                id=det_id,
                observation_id=obs_id,
                predicted_taxon_id=species_id,
                animal_detection_confidence=0.98,
                classification_confidence=0.95,
                triage_state=TriageState.ANIMAL_DETECTED,
            )
        )

    enc = Encounter(
        id=enc_id,
        camera_id=cam_id,
        start_time=start_time,
        end_time=end_time,
        member_detection_ids=det_ids,
        provenance=SYNTHETIC,
    )
    return enc, obs_list, det_list


# ---------------------------------------------------------------------------
# TESTS
# ---------------------------------------------------------------------------

class TestPhase5ActivityAnomalies:

    def test_stable_baseline_no_indicator(self):
        """
        1. Stable baseline without indicator:
        7 baseline days (2026-06-01 to 2026-06-08), each with 2 encounters/day.
        Evaluation day (2026-06-08 to 2026-06-09) with 2 encounters/day.
        Abs change = 0.0 -> NO_INDICATOR.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        # 8 full active days of effort
        efforts = [_effort("cam1", [(b_start, e_end)])]
        encounters = []
        observations = []
        detections = []

        # 2 encounters on each of the 7 baseline days
        for day_idx in range(7):
            d_time = b_start + timedelta(days=day_idx, hours=10)
            e1, obs1, det1 = _encounter_with_species(f"enc_b_{day_idx}_1", "cam1", "puma_concolor", d_time)
            e2, obs2, det2 = _encounter_with_species(f"enc_b_{day_idx}_2", "cam1", "puma_concolor", d_time + timedelta(hours=2))
            encounters.extend([e1, e2])
            observations.extend(obs1 + obs2)
            detections.extend(det1 + det2)

        # 2 encounters on evaluation day
        eval_time = e_start + timedelta(hours=10)
        e_ev1, o_ev1, d_ev1 = _encounter_with_species("enc_ev_1", "cam1", "puma_concolor", eval_time)
        e_ev2, o_ev2, d_ev2 = _encounter_with_species("enc_ev_2", "cam1", "puma_concolor", eval_time + timedelta(hours=2))
        encounters.extend([e_ev1, e_ev2])
        observations.extend(o_ev1 + o_ev2)
        detections.extend(d_ev1 + d_ev2)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=encounters,
            observations=observations,
            detections=detections,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            analysis_timezone="UTC",
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        assert env.status == ResponseStatus.OK
        res = ActivityAnomaliesResult.model_validate(env.result)
        assert res.total_series_evaluated == 1
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.NO_INDICATOR
        assert series.baseline_valid_active_days == 7
        assert series.baseline_median_daily_rate == 2.0
        assert series.evaluation_encounter_rate == 2.0
        assert series.absolute_rate_change == 0.0

    def test_injected_rate_increase_triggers_increased(self):
        """
        2. Injected rate increase:
        Baseline 7 days with counts [1, 1, 1, 1, 1, 1, 1] (or slight variation).
        Evaluation rate is 5.0 encounters/day. Breaches threshold -> INCREASED.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [_effort("cam1", [(b_start, e_end)])]
        encounters = []
        observations = []
        detections = []

        # 1 encounter per baseline day
        for day_idx in range(7):
            d_time = b_start + timedelta(days=day_idx, hours=12)
            e, o, d = _encounter_with_species(f"enc_b_{day_idx}", "cam1", "canis_latrans", d_time)
            encounters.append(e)
            observations.extend(o)
            detections.extend(d)

        # 5 encounters on evaluation day
        for i in range(5):
            ev_time = e_start + timedelta(hours=i * 2 + 1)
            e, o, d = _encounter_with_species(f"enc_ev_{i}", "cam1", "canis_latrans", ev_time)
            encounters.append(e)
            observations.extend(o)
            detections.extend(d)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=encounters,
            observations=observations,
            detections=detections,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["canis_latrans"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        assert env.status == ResponseStatus.OK
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.INCREASED
        assert series.baseline_median_daily_rate == 1.0
        assert series.evaluation_encounter_rate == 5.0
        assert series.absolute_rate_change == 4.0

    def test_injected_rate_decrease_triggers_decreased(self):
        """
        3. Injected rate decrease:
        Baseline has 5 encounters/day. Evaluation drops to 0 encounters/day.
        Triggers DECREASED.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [_effort("cam1", [(b_start, e_end)])]
        encounters = []
        observations = []
        detections = []

        # 5 encounters per baseline day
        for day_idx in range(7):
            for i in range(5):
                d_time = b_start + timedelta(days=day_idx, hours=i * 3 + 1)
                e, o, d = _encounter_with_species(f"enc_b_{day_idx}_{i}", "cam1", "canis_latrans", d_time)
                encounters.append(e)
                observations.extend(o)
                detections.extend(d)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=encounters,
            observations=observations,
            detections=detections,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["canis_latrans"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.DECREASED
        assert series.baseline_median_daily_rate == 5.0
        assert series.evaluation_encounter_rate == 0.0
        assert series.absolute_rate_change == -5.0

    def test_valid_zero_sightings_with_positive_monitoring_effort(self):
        """
        4. Valid zero sightings with positive monitoring effort:
        Active monitoring effort is present for all 7 baseline days and evaluation day,
        but 0 encounters recorded.
        Daily rate is 0.0 encounters/camera-day, NOT None or missing!
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["lynx_rufus"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        assert env.status == ResponseStatus.OK
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.NO_INDICATOR
        assert series.baseline_valid_active_days == 7
        assert series.baseline_median_daily_rate == 0.0
        assert series.evaluation_encounter_rate == 0.0
        # Check all bins have rate == 0.0
        for b in series.baseline_daily_bins:
            assert b.is_valid_baseline_day is True
            assert b.daily_encounter_rate == 0.0

    def test_missing_effort_vs_zero_sightings(self):
        """
        5. Missing effort vs zero sightings:
        Baseline spans 8 days. Days 1-7 have effort. Day 8 has NO effort.
        Day 8 must be excluded from baseline days (NOT imputed as zero!).
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)  # 8 days
        e_start = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

        # Effort covers days 1-7 (June 1-8), day 8 (June 8-9) is completely missing, then eval day (June 9-10) has effort
        efforts = [
            _effort("cam1", [(b_start, datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC))]),
            _effort("cam1", [(e_start, e_end)]),
        ]

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["lynx_rufus"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.baseline_calendar_days_total == 8
        assert series.baseline_valid_active_days == 7  # 7 valid days, day 8 excluded!
        day_8_bin = [b for b in series.baseline_daily_bins if b.date == "2026-06-08"][0]
        assert day_8_bin.is_valid_baseline_day is False
        assert day_8_bin.active_camera_days == 0.0
        assert day_8_bin.daily_encounter_rate is None

    def test_insufficient_baseline_history_not_evaluable(self):
        """
        6. Insufficient baseline history:
        Only 4 days in baseline (min_baseline_days default 7).
        Outcome -> NOT_EVALUABLE. Response status -> INSUFFICIENT_DATA.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 5, 0, 0, 0, tzinfo=UTC)  # 4 days
        e_start = datetime(2026, 6, 5, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 6, 0, 0, 0, tzinfo=UTC)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["lynx_rufus"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        assert env.status == ResponseStatus.INSUFFICIENT_DATA
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.NOT_EVALUABLE
        assert any("Insufficient baseline history" in note for note in series.evaluation_notes)

    def test_insufficient_evaluation_coverage_not_evaluable(self):
        """
        7. Insufficient evaluation coverage:
        Evaluation window has only 0.2 active camera-days (< min_evaluation_active_effort_days=1.0).
        Outcome -> NOT_EVALUABLE.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        # Baseline has full effort, eval has only 4.8 hours (= 0.2 camera-days)
        efforts = [
            _effort("cam1", [(b_start, b_end)]),
            _effort("cam1", [(e_start, e_start + timedelta(hours=4, minutes=48))]),
        ]

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["lynx_rufus"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.NOT_EVALUABLE
        assert any("Insufficient evaluation coverage" in note for note in series.evaluation_notes)

    def test_partial_monitoring_day_excluded(self):
        """
        8. Partial monitoring day:
        A calendar day has only 6h monitoring out of 24h (coverage ratio = 0.25 < 0.5).
        Marked is_valid_baseline_day = False and excluded from baseline statistics.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)  # 8 calendar days
        e_start = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

        # 7 days with 24h effort, day 8 (June 8) has only 6 hours
        ivs = [(b_start, datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC))]
        ivs.append((datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC), datetime(2026, 6, 8, 6, 0, 0, tzinfo=UTC)))
        ivs.append((e_start, e_end))

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", ivs)],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["lynx_rufus"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.baseline_valid_active_days == 7
        d8_bin = [b for b in series.baseline_daily_bins if b.date == "2026-06-08"][0]
        assert d8_bin.is_valid_baseline_day is False
        assert d8_bin.coverage_ratio == 0.25

    def test_overlapping_effort_protection(self):
        """
        9. Overlapping effort protection:
        Reconciled with Phase 1 validation:
        - Raw snapshots with overlapping intervals are rejected at the public entrypoint as INVALID_REQUEST.
        - Documented public normalization normalize_snapshot_efforts() resolves overlaps into clean disjoint records.
        - Contiguous adjacent intervals across records pass public validation and are unified without double-counting.
        """
        from wildscope_analytics import normalize_snapshot_efforts
        from wildscope_analytics.anomalies import _merge_intervals

        # 1. Direct algorithm verification:
        iv1 = (datetime(2026, 6, 1, 0, 0, tzinfo=UTC), datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
        iv2 = (datetime(2026, 6, 1, 6, 0, tzinfo=UTC), datetime(2026, 6, 1, 18, 0, tzinfo=UTC))
        merged = _merge_intervals([iv1, iv2])
        assert len(merged) == 1
        assert merged[0] == (datetime(2026, 6, 1, 0, 0, tzinfo=UTC), datetime(2026, 6, 1, 18, 0, tzinfo=UTC))
        assert (merged[0][1] - merged[0][0]).total_seconds() == 18 * 3600.0  # 18 hours, not 24 hours!

        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        # 2. Public entrypoint rejects raw overlapping intervals (Phase 1 contract):
        raw_eff1 = MonitoringEffort(
            id="eff1",
            camera_id="cam1",
            active_intervals=[
                TimeInterval(start=b_start, end=b_start + timedelta(hours=12)),
                TimeInterval(start=datetime(2026, 6, 2, 0, 0, tzinfo=UTC), end=e_end),
            ],
            source="ranger_log",
        )
        raw_eff2 = MonitoringEffort(
            id="eff2",
            camera_id="cam1",
            active_intervals=[
                TimeInterval(start=b_start + timedelta(hours=6), end=b_start + timedelta(hours=18)),
            ],
            source="ranger_log",
        )
        raw_snap = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[raw_eff1, raw_eff2],
            encounters=[],
            observations=[],
            detections=[],
        )
        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["lynx_rufus"],
            camera_ids=["cam1"],
        )
        rej_env = detect_activity_anomalies(raw_snap, req)
        assert rej_env.status == ResponseStatus.INVALID_REQUEST
        assert rej_env.errors[0].code == ValidationErrorCode.OVERLAPPING_EFFORT

        # 3. Documented public ingestion normalization step resolves overlap:
        norm_snap = normalize_snapshot_efforts(raw_snap)
        assert norm_snap is not raw_snap  # original snapshot immutability preserved
        norm_env = detect_activity_anomalies(norm_snap, req)
        assert norm_env.status == ResponseStatus.OK
        res_norm = ActivityAnomaliesResult.model_validate(norm_env.result)
        day1_bin = [b for b in res_norm.series[0].baseline_daily_bins if b.date == "2026-06-01"][0]
        assert day1_bin.active_seconds == 18 * 3600.0
        assert day1_bin.active_camera_days == 0.75
        assert day1_bin.coverage_ratio == 0.75

        # 4. Contiguous adjacent intervals across separate records pass public validation natively:
        contig_eff1 = MonitoringEffort(
            id="eff_c1",
            camera_id="cam1",
            active_intervals=[
                TimeInterval(start=b_start, end=b_start + timedelta(hours=12)),
                TimeInterval(start=datetime(2026, 6, 2, 0, 0, tzinfo=UTC), end=e_end),
            ],
            source="ranger_log",
        )
        contig_eff2 = MonitoringEffort(
            id="eff_c2",
            camera_id="cam1",
            active_intervals=[
                TimeInterval(start=b_start + timedelta(hours=12), end=b_start + timedelta(hours=18)),
            ],
            source="ranger_log",
        )
        contig_snap = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[contig_eff1, contig_eff2],
            encounters=[],
            observations=[],
            detections=[],
        )
        contig_env = detect_activity_anomalies(contig_snap, req)
        assert contig_env.status == ResponseStatus.OK

    def test_out_of_effort_observations_counted_and_reported(self):
        """
        10. Out-of-effort observations counted and reported:
        An encounter occurs at 23:00 on a day where monitoring ended at 18:00.
        Must contribute to out_of_effort_encounters_count, NOT daily encounter rate.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        # Day 1 active effort is only 08:00 to 18:00 (10 hours)
        efforts = [
            _effort("cam1", [(b_start + timedelta(hours=8), b_start + timedelta(hours=18))]),
            _effort("cam1", [(datetime(2026, 6, 2, 0, 0, tzinfo=UTC), e_end)]),
        ]

        # Encounter at 23:00 on day 1 (outside active effort)
        e_out, obs_out, det_out = _encounter_with_species(
            "enc_out", "cam1", "puma_concolor", b_start + timedelta(hours=23)
        )

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[e_out],
            observations=obs_out,
            detections=det_out,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.out_of_effort_encounters_count == 1
        day1_bin = [b for b in series.baseline_daily_bins if b.date == "2026-06-01"][0]
        assert day1_bin.encounter_count == 0  # not counted!
        assert any("Excluded 1 encounter(s) recorded outside" in note for note in series.evaluation_notes)

    def test_zero_baseline_dispersion_and_absolute_fallback(self):
        """
        11. Zero baseline dispersion:
        All baseline days have 0.0 encounters (median = 0, MAD = 0, sigma = 0).
        Evaluation has 1.0 encounter/day.
        With fallback=True -> triggers INCREASED via absolute threshold.
        With fallback=False -> NO_INDICATOR.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [_effort("cam1", [(b_start, e_end)])]
        # 1 encounter on evaluation day
        e_ev, o_ev, d_ev = _encounter_with_species("enc_ev", "cam1", "puma_concolor", e_start + timedelta(hours=12))

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[e_ev],
            observations=o_ev,
            detections=d_ev,
        )

        # With fallback = True
        req_fallback = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            allow_zero_dispersion_absolute_fallback=True,
        )
        env = detect_activity_anomalies(snapshot, req_fallback)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.baseline_mad_daily_rate == 0.0
        assert series.baseline_dispersion_sigma == 0.0
        assert series.anomaly_score_sigmas is None  # No division by zero!
        assert series.relative_rate_change is None  # baseline median is 0
        assert series.outcome == AnomalyOutcome.INCREASED

        # With fallback = False
        req_no_fallback = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            allow_zero_dispersion_absolute_fallback=False,
        )
        env_no = detect_activity_anomalies(snapshot, req_no_fallback)
        res_no = ActivityAnomaliesResult.model_validate(env_no.result)
        assert res_no.series[0].outcome == AnomalyOutcome.NO_INDICATOR

        # Two-sided verification: DECREASE direction under zero baseline dispersion
        # Baseline has exactly 2.0 encounters on each of the 7 days (median=2.0, MAD=0.0).
        # Evaluation day has 0 encounters (eval rate = 0.0, abs_change = -2.0 <= -0.2).
        encounters_dec = []
        observations_dec = []
        detections_dec = []
        for d in range(7):
            d_time = b_start + timedelta(days=d, hours=10)
            e1, obs1, det1 = _encounter_with_species(f"enc_b_{d}_1", "cam1", "puma_concolor", d_time)
            e2, obs2, det2 = _encounter_with_species(f"enc_b_{d}_2", "cam1", "puma_concolor", d_time + timedelta(hours=2))
            encounters_dec.extend([e1, e2])
            observations_dec.extend(obs1 + obs2)
            detections_dec.extend(det1 + det2)

        snap_dec = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=encounters_dec,
            observations=observations_dec,
            detections=detections_dec,
        )

        req_dec_fallback = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            allow_zero_dispersion_absolute_fallback=True,
        )
        env_dec = detect_activity_anomalies(snap_dec, req_dec_fallback)
        res_dec = ActivityAnomaliesResult.model_validate(env_dec.result)
        series_dec = res_dec.series[0]
        assert series_dec.baseline_mad_daily_rate == 0.0
        assert series_dec.baseline_dispersion_sigma == 0.0
        assert series_dec.anomaly_score_sigmas is None
        assert series_dec.absolute_rate_change == -2.0
        assert series_dec.outcome == AnomalyOutcome.DECREASED

        # Decrease with fallback disabled -> NO_INDICATOR
        req_dec_no_fallback = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            allow_zero_dispersion_absolute_fallback=False,
        )
        env_dec_no = detect_activity_anomalies(snap_dec, req_dec_no_fallback)
        res_dec_no = ActivityAnomaliesResult.model_validate(env_dec_no.result)
        assert res_dec_no.series[0].outcome == AnomalyOutcome.NO_INDICATOR

    def test_minimum_absolute_change_prevents_spurious_micro_alerts(self):
        """
        12. Minimum absolute change requirement:
        Baseline daily rates have very tiny variation (e.g. sigma ~ 0.0007).
        Evaluation rate increases by only 0.01 encounters/day.
        Although score is ~13 sigmas, abs change 0.01 < min_absolute_rate_change (0.2).
        Must return NO_INDICATOR!
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        # Baseline days alternate active seconds slightly: 86400 vs 86390 seconds for 1 encounter
        efforts = []
        encounters = []
        observations = []
        detections = []

        for d in range(7):
            d_s = b_start + timedelta(days=d)
            # tiny effort fluctuation
            dur = 86400 if (d % 2 == 0) else 86350
            efforts.append(_effort("cam1", [(d_s, d_s + timedelta(seconds=dur))]))
            e, o, det = _encounter_with_species(f"enc_{d}", "cam1", "puma_concolor", d_s + timedelta(hours=10))
            encounters.append(e)
            observations.extend(o)
            detections.extend(det)

        # Eval day: effort = 86400, 1 encounter -> rate = 1.0 encounters/day
        # Abs change is tiny (around 0.0003)
        eff_ev = _effort("cam1", [(e_start, e_end)])
        efforts.append(eff_ev)
        e_ev, o_ev, det_ev = _encounter_with_species("enc_ev", "cam1", "puma_concolor", e_start + timedelta(hours=10))
        encounters.append(e_ev)
        observations.extend(o_ev)
        detections.extend(det_ev)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=encounters,
            observations=observations,
            detections=detections,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            min_absolute_rate_change=0.2,
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.NO_INDICATOR

    def test_non_overlapping_window_validation(self):
        """
        13. Non-overlapping window validation:
        baseline_end > eval_start or baseline_start >= baseline_end must be rejected.
        """
        t0 = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        t1 = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 6, 7, 0, 0, 0, tzinfo=UTC)  # overlaps baseline
        t3 = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

        with pytest.raises(ValueError, match="Baseline window must precede and not overlap"):
            ActivityAnomalyRequest(
                baseline_start_time=t0,
                baseline_end_time=t1,
                evaluation_start_time=t2,
                evaluation_end_time=t3,
            )

        with pytest.raises(ValueError, match="baseline_start_time .* must precede baseline_end_time"):
            ActivityAnomalyRequest(
                baseline_start_time=t1,
                baseline_end_time=t0,
                evaluation_start_time=t1,
                evaluation_end_time=t3,
            )

    def test_baseline_leakage_prevention(self):
        """
        14. Baseline leakage prevention:
        A huge cluster of 100 encounters in the evaluation window must NOT alter
        baseline daily bins, baseline median, or baseline MAD.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [_effort("cam1", [(b_start, e_end)])]
        encounters = []
        observations = []
        detections = []

        # 1 encounter per baseline day
        for d in range(7):
            e, o, det = _encounter_with_species(f"enc_{d}", "cam1", "puma_concolor", b_start + timedelta(days=d, hours=10))
            encounters.append(e)
            observations.extend(o)
            detections.extend(det)

        # 100 encounters in evaluation window
        for i in range(100):
            ev_ts = e_start + timedelta(minutes=i * 10)
            e, o, det = _encounter_with_species(f"enc_ev_{i}", "cam1", "puma_concolor", ev_ts)
            encounters.append(e)
            observations.extend(o)
            detections.extend(det)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=encounters,
            observations=observations,
            detections=detections,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        # Baseline median must be exactly 1.0 despite the 100 eval encounters
        assert series.baseline_median_daily_rate == 1.0
        assert series.baseline_mad_daily_rate == 0.0
        assert series.evaluation_encounter_count == 100
        assert series.evaluation_encounter_rate == 100.0

    def test_dst_transition_boundary(self):
        """
        15. Consistent timezone and calendar day boundaries across DST transitions:
        America/New_York DST transition in March (23-hour day).
        Properly bins calendar days and measures active coverage.
        """
        ny_tz = "America/New_York"
        # March 2026: DST starts second Sunday (March 8, 2026)
        b_start = datetime(2026, 3, 5, 0, 0, 0, tzinfo=ZoneInfo(ny_tz))
        b_end = datetime(2026, 3, 12, 0, 0, 0, tzinfo=ZoneInfo(ny_tz))  # 7 days
        e_start = datetime(2026, 3, 12, 0, 0, 0, tzinfo=ZoneInfo(ny_tz))
        e_end = datetime(2026, 3, 13, 0, 0, 0, tzinfo=ZoneInfo(ny_tz))

        efforts = [_effort("cam1", [(b_start, e_end)])]
        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            analysis_timezone=ny_tz,
            species_ids=["lynx_rufus"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        assert env.status == ResponseStatus.OK
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.baseline_valid_active_days == 7
        dst_bin = [b for b in series.baseline_daily_bins if b.date == "2026-03-08"][0]
        # 23 hours = 82,800 seconds
        assert dst_bin.active_seconds == 23 * 3600.0
        assert dst_bin.coverage_ratio == 1.0  # covers full nominal day!

    def test_encounter_species_deduplication(self):
        """
        16. Encounter/species deduplication per encounter:
        An encounter containing 5 detections of puma_concolor must only count as 1 encounter.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [_effort("cam1", [(b_start, e_end)])]
        # Encounter with 5 member detections of puma_concolor
        e, o, det = _encounter_with_species(
            "enc_multi_det", "cam1", "puma_concolor", b_start + timedelta(days=1, hours=10), num_detections=5
        )

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[e],
            observations=o,
            detections=det,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        d1_bin = [b for b in series.baseline_daily_bins if b.date == "2026-06-02"][0]
        assert d1_bin.encounter_count == 1  # Deduplicated!

    def test_review_correction_modifies_effective_label(self):
        """
        17. Review correction modifying effective label at new revision:
        At revision 1, detection is canis_latrans.
        At revision 2, review event reclassifies it as puma_concolor.
        Evaluates under puma_concolor with 1 encounter, and canis_latrans with 0.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [_effort("cam1", [(b_start, e_end)])]
        e, o, det = _encounter_with_species("enc1", "cam1", "canis_latrans", b_start + timedelta(days=1, hours=10))

        # Add human review event reclassifying to puma_concolor
        rev = ReviewEvent(
            id="rev1",
            target_id=det[0].id,
            decision=ReviewDecision.CORRECT_SPECIES,
            corrected_taxon_id="puma_concolor",
            reviewer="human_expert",
            created_at=datetime.now(UTC),
            sequence_number=1,
        )

        snapshot = Snapshot(
            metadata=_meta(revision=2),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[e],
            observations=o,
            detections=det,
            reviews=[rev],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["canis_latrans", "puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        puma_series = [s for s in res.series if s.species_id == "puma_concolor"][0]
        canis_series = [s for s in res.series if s.species_id == "canis_latrans"][0]

        puma_d1 = [b for b in puma_series.baseline_daily_bins if b.date == "2026-06-02"][0]
        canis_d1 = [b for b in canis_series.baseline_daily_bins if b.date == "2026-06-02"][0]
        assert puma_d1.encounter_count == 1
        assert canis_d1.encounter_count == 0

    def test_camera_change_telemetry_suspect_or_changed(self):
        """
        18. Documented deployment/camera change flags -> SUSPECT_OR_CHANGED:
        Camera metadata indicates repositioned=True.
        Assessment must be SUSPECT_OR_CHANGED.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        cam_repositioned = _cam("cam1", metadata={"repositioned": True, "serviced_date": "2026-06-07"})
        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[cam_repositioned],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            allow_suspect_comparability=False,  # default policy
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.comparability_assessment == ComparabilityAssessment.SUSPECT_OR_CHANGED
        assert series.outcome == AnomalyOutcome.NOT_EVALUABLE  # Not evaluable under default policy!
        assert any("camera_telemetry:repositioned=True" in note for note in series.comparability_notes)
        assert any("Series is NOT_EVALUABLE" in note for note in series.evaluation_notes)

        # Override with allow_suspect_comparability=True
        req_allowed = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            allow_suspect_comparability=True,
        )
        env_allowed = detect_activity_anomalies(snapshot, req_allowed)
        res_allowed = ActivityAnomaliesResult.model_validate(env_allowed.result)
        series_allowed = res_allowed.series[0]
        assert series_allowed.outcome == AnomalyOutcome.NO_INDICATOR
        assert any("QUALIFIED_INDICATOR" in note for note in series_allowed.evaluation_notes)

        # Affirmative, scoped provenance yields VERIFIED_COMPARABLE
        cam_verified = _cam("cam1", metadata={"stationarity_verified": True, "verification_scope": "hardware_and_mount"})
        snap_verified = Snapshot(
            metadata=_meta(),
            cameras=[cam_verified],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )
        env_v = detect_activity_anomalies(snap_verified, req)
        res_v = ActivityAnomaliesResult.model_validate(env_v.result)
        assert res_v.series[0].comparability_assessment == ComparabilityAssessment.VERIFIED_COMPARABLE

        # Prediction-run provenance with multiple model versions yields SUSPECT_OR_CHANGED
        from wildscope_analytics.contracts.entities import PredictionRun
        from wildscope_analytics.contracts.enums import PredictionStatus
        p_run1 = PredictionRun(id="pr1", model_version="v5a", status=PredictionStatus.COMPLETED)
        p_run2 = PredictionRun(id="pr2", model_version="v5b", status=PredictionStatus.COMPLETED)
        snap_pr = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            prediction_runs=[p_run1, p_run2],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )
        env_pr = detect_activity_anomalies(snap_pr, req)
        res_pr = ActivityAnomaliesResult.model_validate(env_pr.result)
        assert res_pr.series[0].comparability_assessment == ComparabilityAssessment.SUSPECT_OR_CHANGED
        assert any("prediction_provenance:multiple_model_versions" in note for note in res_pr.series[0].comparability_notes)

    def test_raw_reference_dataset_returns_unavailable(self):
        """
        19. Raw reference dataset -> UNAVAILABLE:
        Snapshot with data_source_mode = DATASET_REFERENCE returns UNAVAILABLE.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        snapshot = Snapshot(
            metadata=_meta(mode=DataSourceMode.DATASET_REFERENCE),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
        )

        env = detect_activity_anomalies(snapshot, req)
        assert env.status == ResponseStatus.UNAVAILABLE
        assert any("DATASET_REFERENCE" in lim for lim in env.limitations)

    def test_revision_conflict_returns_invalid_request(self):
        """
        20. Revision conflict -> INVALID_REQUEST:
        Request expects revision 5, snapshot is at revision 1.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        snapshot = Snapshot(
            metadata=_meta(revision=1),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            expected_revision=5,
        )

        env = detect_activity_anomalies(snapshot, req)
        assert env.status == ResponseStatus.INVALID_REQUEST
        assert env.errors[0].code == ValidationErrorCode.SCHEMA_VIOLATION

    def test_snapshot_immutability(self):
        """
        21. Snapshot immutability:
        Original snapshot remains byte/attribute identical before and after analysis.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )
        before_dump = snapshot.model_dump_json()

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
        )
        detect_activity_anomalies(snapshot, req)

        after_dump = snapshot.model_dump_json()
        assert before_dump == after_dump

    def test_clean_json_serialization_no_nan_or_infinity(self):
        """
        22. Clean JSON serialization:
        Response serializes cleanly with standard json.dumps without NaN or Infinity.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        serialized = env.model_dump_json()
        assert "NaN" not in serialized
        assert "Infinity" not in serialized
        parsed = json.loads(serialized)
        assert parsed["metric"] == "activity_anomaly"

    def test_parity_between_analyze_and_detect_activity_anomalies(self):
        """
        23. Parity between analyze() and detect_activity_anomalies():
        Both entry points return identical results for the same request.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=[_effort("cam1", [(b_start, e_end)])],
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env1 = detect_activity_anomalies(snapshot, req)
        env2 = analyze(snapshot, req)

        assert env1.status == env2.status
        assert env1.result == env2.result
        assert env1.applied_filters == env2.applied_filters

        # Test AnalysisRequest compatibility via parameters
        analysis_req = AnalysisRequest(
            metric=AnalysisMetric.ACTIVITY_ANOMALY,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
            parameters={
                "baseline_start_time": b_start.isoformat(),
                "baseline_end_time": b_end.isoformat(),
                "evaluation_start_time": e_start.isoformat(),
                "evaluation_end_time": e_end.isoformat(),
            },
        )
        env3 = analyze(snapshot, analysis_req)
        assert env3.status == env1.status
        assert env3.result == env1.result

    def test_multiple_cameras_independent_series(self):
        """
        24. Multiple cameras processed as independent series:
        cam1 has stable baseline and stable eval -> NO_INDICATOR.
        cam2 has 0 baseline and 5 eval encounters -> INCREASED.
        Cameras must NOT be pooled!
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [
            _effort("cam1", [(b_start, e_end)]),
            _effort("cam2", [(b_start, e_end)]),
        ]
        encounters = []
        observations = []
        detections = []

        # cam1: 1 encounter/day across baseline and eval
        for d in range(7):
            e, o, det = _encounter_with_species(f"enc_c1_{d}", "cam1", "puma_concolor", b_start + timedelta(days=d, hours=10))
            encounters.append(e)
            observations.extend(o)
            detections.extend(det)
        e, o, det = _encounter_with_species("enc_c1_ev", "cam1", "puma_concolor", e_start + timedelta(hours=10))
        encounters.append(e)
        observations.extend(o)
        detections.extend(det)

        # cam2: 0 encounters in baseline, 5 encounters in eval
        for i in range(5):
            e, o, det = _encounter_with_species(f"enc_c2_ev_{i}", "cam2", "puma_concolor", e_start + timedelta(hours=i * 2 + 1))
            encounters.append(e)
            observations.extend(o)
            detections.extend(det)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1"), _cam("cam2")],
            monitoring_efforts=efforts,
            encounters=encounters,
            observations=observations,
            detections=detections,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1", "cam2"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        assert res.total_series_evaluated == 2
        assert res.increased_count == 1
        assert res.no_indicator_count == 1

        c1_res = [s for s in res.series if s.camera_id == "cam1"][0]
        c2_res = [s for s in res.series if s.camera_id == "cam2"][0]
        assert c1_res.outcome == AnomalyOutcome.NO_INDICATOR
        assert c2_res.outcome == AnomalyOutcome.INCREASED

    def test_midday_boundary_slice_excluded_and_does_not_leak_encounters(self):
        """
        25. Verify treatment of windows starting mid-day:
        Window starts at 14:00 on June 1. That day has only 10 hours (41.7% < 50%).
        It is excluded as invalid baseline day, and encounters on that day do NOT leak into
        baseline rate calculation.
        """
        b_start = datetime(2026, 6, 1, 14, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

        efforts = [_effort("cam1", [(datetime(2026, 6, 1, 0, 0, tzinfo=UTC), e_end)])]
        encounters = []
        observations = []
        detections = []

        # Put 5 encounters on June 1 afternoon (between 14:00 and 18:00)
        for i in range(5):
            e, o, d = _encounter_with_species(f"enc_b0_{i}", "cam1", "puma_concolor", b_start + timedelta(hours=i + 1))
            encounters.append(e)
            observations.extend(o)
            detections.extend(d)

        # 7 full baseline days (June 2 to June 9) each have exactly 1 encounter
        for day in range(1, 8):
            d_time = datetime(2026, 6, 1 + day, 10, 0, 0, tzinfo=UTC)
            e, o, d = _encounter_with_species(f"enc_b_{day}", "cam1", "puma_concolor", d_time)
            encounters.append(e)
            observations.extend(o)
            detections.extend(d)

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=encounters,
            observations=observations,
            detections=detections,
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        # June 1 slice is 10 hours out of 24h day -> coverage 41.7% < 50% -> invalid!
        d1_bin = [b for b in series.baseline_daily_bins if b.date == "2026-06-01"][0]
        assert d1_bin.is_valid_baseline_day is False
        assert d1_bin.daily_encounter_rate is None
        # Valid days must be 7 (June 2 through 8), and median rate must be 1.0 (the 5 encounters on June 1 were excluded!)
        assert series.baseline_valid_active_days == 7
        assert series.baseline_median_daily_rate == 1.0

    def test_evaluation_window_coverage_policy_failure(self):
        """
        26. Verify evaluation coverage policy:
        Evaluation window is 24 hours, active effort is 8 hours (coverage = 33.3% < 50%).
        Even if active effort >= min_evaluation_active_effort_days (with threshold lowered to 0.3),
        coverage failure marks series NOT_EVALUABLE.
        """
        b_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        b_end = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_start = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        e_end = datetime(2026, 6, 9, 0, 0, 0, tzinfo=UTC)

        efforts = [
            _effort("cam1", [(b_start, b_end)]),
            _effort("cam1", [(e_start, e_start + timedelta(hours=8))]),
        ]

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[],
            observations=[],
            detections=[],
        )

        req = ActivityAnomalyRequest(
            baseline_start_time=b_start,
            baseline_end_time=b_end,
            evaluation_start_time=e_start,
            evaluation_end_time=e_end,
            min_evaluation_active_effort_days=0.3,  # 8h = 0.33 days >= 0.3
            min_day_coverage_ratio=0.5,             # 8h / 24h = 0.33 < 0.5
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )

        env = detect_activity_anomalies(snapshot, req)
        res = ActivityAnomaliesResult.model_validate(env.result)
        series = res.series[0]
        assert series.outcome == AnomalyOutcome.NOT_EVALUABLE
        assert any("coverage ratio" in note for note in series.evaluation_notes)

    def test_phase2_phase5_count_and_effort_parity(self):
        """
        27. Direct parity test:
        Phase 2 compute_effort_normalised_rates and Phase 5 detect_activity_anomalies
        must agree exactly on active camera-days and in-effort encounter counts for the same window.
        """
        t_start = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)
        t_mid = datetime(2026, 6, 8, 0, 0, 0, tzinfo=UTC)
        t_end = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)

        # Effort: 36 hours active in evaluation window [t_mid, t_end)
        efforts = [
            _effort("cam1", [(t_start, t_mid)]),
            _effort("cam1", [(t_mid, t_mid + timedelta(hours=36))]),
        ]

        # 3 encounters during evaluation active effort, 1 outside effort
        e1, o1, d1 = _encounter_with_species("e1", "cam1", "puma_concolor", t_mid + timedelta(hours=5))
        e2, o2, d2 = _encounter_with_species("e2", "cam1", "puma_concolor", t_mid + timedelta(hours=15))
        e3, o3, d3 = _encounter_with_species("e3", "cam1", "puma_concolor", t_mid + timedelta(hours=25))
        e_out, o_out, d_out = _encounter_with_species("e_out", "cam1", "puma_concolor", t_mid + timedelta(hours=40))

        snapshot = Snapshot(
            metadata=_meta(),
            cameras=[_cam("cam1")],
            monitoring_efforts=efforts,
            encounters=[e1, e2, e3, e_out],
            observations=o1 + o2 + o3 + o_out,
            detections=d1 + d2 + d3 + d_out,
        )

        # 1. Phase 2 effort-normalised rates on window [t_mid, t_end)
        p2_req = AnalysisRequest(
            metric=AnalysisMetric.EFFORT_NORMALISED_RATES,
            start_time=t_mid,
            end_time=t_end,
            camera_ids=["cam1"],
        )
        p2_env = analyze(snapshot, p2_req)
        assert p2_env.status == ResponseStatus.OK
        p2_cam1 = [r for r in p2_env.result["camera_rates"] if r["camera_id"] == "cam1"][0]
        p2_effort_days = p2_cam1["active_camera_days_in_window"]
        p2_in_effort_encs = p2_cam1["encounters_in_effort"]
        p2_out_effort_encs = p2_cam1["encounters_outside_effort"]

        # 2. Phase 5 evaluation on window [t_mid, t_end)
        p5_req = ActivityAnomalyRequest(
            baseline_start_time=t_start,
            baseline_end_time=t_mid,
            evaluation_start_time=t_mid,
            evaluation_end_time=t_end,
            species_ids=["puma_concolor"],
            camera_ids=["cam1"],
        )
        p5_env = detect_activity_anomalies(snapshot, p5_req)
        p5_res = ActivityAnomaliesResult.model_validate(p5_env.result)
        p5_series = p5_res.series[0]

        # Verify strict parity:
        assert p5_series.evaluation_active_effort_days == p2_effort_days == 1.5
        assert p5_series.evaluation_encounter_count == p2_in_effort_encs == 3
        assert p5_series.out_of_effort_encounters_count == p2_out_effort_encs == 1
