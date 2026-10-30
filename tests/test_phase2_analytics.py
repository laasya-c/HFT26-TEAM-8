"""
WILDSCOPE Phase 2 Analytics Tests
===================================
Comprehensive test coverage for:
  - Effective-label resolver (confirm, correct, reject, unknown, multi-review, ambiguous ordering)
  - Overview metric
  - Species encounter counts (deduplication, multi-species, unknown, rejected)
  - Camera comparison
  - Daily activity (timezone conversion)
  - Hourly activity (0–23 bins)
  - Species × camera matrix
  - Effort-normalised rates (clipping, zero-division guard, missing effort)
  - Revision mismatch
  - Reference annotations (dataset_reference mode)
  - Empty valid dataset
  - Missing timestamps / unknown timezones
  - rank_review() unavailability (Phase 3)
  - JSON serialisation round-trip

All fixtures are hand-calculated SYNTHETIC TEST FIXTUREs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import pytest

from wildscope_analytics import (
    AnalysisMetric,
    AnalysisRequest,
    AnalysisResponseEnvelope,
    Camera,
    DatasetReferenceAnnotation,
    DataSourceMode,
    Detection,
    Encounter,
    InclusionPolicy,
    MediaAsset,
    MonitoringEffort,
    Observation,
    PredictionRun,
    ResponseStatus,
    ReviewDecision,
    ReviewEvent,
    ReviewRankingRequest,
    Snapshot,
    SnapshotMetadata,
    TimeInterval,
    TriageState,
    analyze,
    rank_review,
    load_and_validate_snapshot,
)
from wildscope_analytics.analytics import (
    resolve_effective_labels,
    _REJECTED_TAXON,
    _UNKNOWN_TAXON,
    _EMPTY_TAXON,
    _UNRESOLVED_TAXON,
)
from wildscope_analytics.contracts.enums import ReviewOrderingMechanism
from wildscope_analytics.caltech_adapter import import_caltech_snapshot

# ---------------------------------------------------------------------------
# FIXTURES / HELPERS
# ---------------------------------------------------------------------------

UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")  # UTC+5:30

SYNTHETIC_LABEL = "SYNTHETIC TEST FIXTURE"


def _meta(revision: int = 1, mode: DataSourceMode = DataSourceMode.OPERATIONAL_PREDICTION,
          ordering: ReviewOrderingMechanism = ReviewOrderingMechanism.BACKEND_REVISION) -> SnapshotMetadata:
    return SnapshotMetadata(
        schema_version="1.1.0",
        dataset_revision=revision,
        created_at=datetime.now(UTC),
        source_system="WILDSCOPE_TEST",
        data_source_mode=mode,
        review_ordering_mechanism=ordering,
        provenance=SYNTHETIC_LABEL,
    )


def _cam(cam_id: str, site_id: str | None = None) -> Camera:
    return Camera(id=cam_id, site_id=site_id, provenance=SYNTHETIC_LABEL)


def _media(media_id: str, cam_id: str, captured_at: datetime | None = None) -> MediaAsset:
    return MediaAsset(
        id=media_id,
        camera_id=cam_id,
        storage_key=f"test/{media_id}.jpg",
        captured_at=captured_at,
        raw_timestamp=captured_at.isoformat() if captured_at else None,
        provenance=SYNTHETIC_LABEL,
    )


def _obs(obs_id: str, cam_id: str, media_id: str, det_ids: list[str],
         captured_at: datetime | None = None) -> Observation:
    return Observation(
        id=obs_id,
        camera_id=cam_id,
        source_media_id=media_id,
        detection_ids=det_ids,
        captured_at=captured_at,
        raw_timestamp=captured_at.isoformat() if captured_at else None,
    )


def _det(det_id: str, obs_id: str, taxon: str | None = "panthera_tigris",
         confidence: float = 0.9, triage: TriageState = TriageState.ANIMAL_DETECTED) -> Detection:
    return Detection(
        id=det_id,
        observation_id=obs_id,
        triage_state=triage,
        animal_detection_confidence=confidence,
        predicted_taxon_id=taxon,
        classification_confidence=confidence if taxon else None,
    )


def _enc(enc_id: str, cam_id: str, det_ids: list[str], obs_ids: list[str] | None = None,
         start: datetime | None = None, end: datetime | None = None) -> Encounter:
    return Encounter(
        id=enc_id,
        camera_id=cam_id,
        member_detection_ids=det_ids,
        member_observation_ids=obs_ids or [],
        start_time=start,
        end_time=end,
        rule_version="v1_time_gap_30min",
        provenance=SYNTHETIC_LABEL,
    )


def _rev(rev_id: str, target_id: str, decision: ReviewDecision,
         corrected: str | None = None, seq: int | None = None,
         created_offset_seconds: float = 0.0) -> ReviewEvent:
    # NOTE: ReviewEvent has extra="forbid"; provenance is not a ReviewEvent field.
    return ReviewEvent(
        id=rev_id,
        target_id=target_id,
        decision=decision,
        corrected_taxon_id=corrected,
        reviewer="test_reviewer",
        created_at=datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=created_offset_seconds),
        sequence_number=seq,
        reason=f"SYNTHETIC TEST FIXTURE - {rev_id}",
    )


def _effort(eff_id: str, cam_id: str, start: datetime, end: datetime) -> MonitoringEffort:
    return MonitoringEffort(
        id=eff_id,
        camera_id=cam_id,
        active_intervals=[TimeInterval(start=start, end=end)],
        source="test_fixture",
    )


T0 = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)   # 06:00 UTC
T1 = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)   # 07:00 UTC
T2 = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)   # next day
T3 = datetime(2026, 10, 17, 20, 0, tzinfo=UTC)  # evening


# ---------------------------------------------------------------------------
# EFFECTIVE LABEL RESOLVER TESTS
# ---------------------------------------------------------------------------

class TestEffectiveLabelResolver:
    """SYNTHETIC TEST FIXTURE: verifies the shared label resolver in isolation."""

    def _make_minimal_snap(self, det: Detection, reviews: list[ReviewEvent]) -> Snapshot:
        cam = _cam("cam_01")
        media = _media("med_01", "cam_01", T0)
        obs = _obs("obs_01", "cam_01", "med_01", [det.id], T0)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[media],
            observations=[obs],
            detections=[det],
            reviews=reviews,
        )

    def test_no_reviews_provisional_label(self):
        """No reviews → provisional label from predicted_taxon_id."""
        det = _det("det_01", "obs_01", taxon="canis_latrans")
        snap = self._make_minimal_snap(det, [])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.taxon_id == "canis_latrans"
        assert lbl.review_id is None
        assert not lbl.is_rejected
        assert not lbl.is_unknown

    def test_no_reviews_null_taxon_becomes_unknown(self):
        """No reviews + null taxon → unknown animal label."""
        det = _det("det_01", "obs_01", taxon=None)
        snap = self._make_minimal_snap(det, [])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.taxon_id == _UNKNOWN_TAXON
        assert lbl.is_unknown

    def test_empty_frame_triage_is_empty(self):
        """LIKELY_EMPTY triage → empty label, no species."""
        det = _det("det_01", "obs_01", taxon=None, triage=TriageState.LIKELY_EMPTY,
                   confidence=0.02)
        snap = self._make_minimal_snap(det, [])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.is_empty
        assert lbl.taxon_id == _EMPTY_TAXON

    def test_confirm_species_preserves_prediction(self):
        """CONFIRM_SPECIES keeps the predicted taxon."""
        det = _det("det_01", "obs_01", taxon="lynx_rufus")
        rev = _rev("rev_01", "det_01", ReviewDecision.CONFIRM_SPECIES)
        snap = self._make_minimal_snap(det, [rev])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.taxon_id == "lynx_rufus"
        assert lbl.review_id == "rev_01"
        assert lbl.decision == ReviewDecision.CONFIRM_SPECIES.value

    def test_correct_species_overrides_prediction(self):
        """CORRECT_SPECIES substitutes the corrected_taxon_id."""
        det = _det("det_01", "obs_01", taxon="canis_latrans")
        rev = _rev("rev_01", "det_01", ReviewDecision.CORRECT_SPECIES, corrected="puma_concolor")
        snap = self._make_minimal_snap(det, [rev])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.taxon_id == "puma_concolor"
        assert lbl.review_id == "rev_01"

    def test_reject_detection_marks_as_rejected(self):
        """REJECT_DETECTION → is_rejected=True, taxon=__rejected__."""
        det = _det("det_01", "obs_01", taxon="sus_scrofa")
        rev = _rev("rev_01", "det_01", ReviewDecision.REJECT_DETECTION)
        snap = self._make_minimal_snap(det, [rev])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.is_rejected
        assert lbl.taxon_id == _REJECTED_TAXON

    def test_mark_unknown_decision(self):
        """MARK_UNKNOWN → is_unknown=True."""
        det = _det("det_01", "obs_01", taxon="canis_latrans")
        rev = _rev("rev_01", "det_01", ReviewDecision.MARK_UNKNOWN)
        snap = self._make_minimal_snap(det, [rev])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.is_unknown
        assert lbl.taxon_id == _UNKNOWN_TAXON

    def test_multiple_reviews_sequence_number_ordering(self):
        """Multiple reviews with sequence_number → highest wins."""
        det = _det("det_01", "obs_01", taxon="puma_concolor")
        rev_old = _rev("rev_01", "det_01", ReviewDecision.CONFIRM_SPECIES, seq=1)
        rev_new = _rev("rev_02", "det_01", ReviewDecision.CORRECT_SPECIES,
                       corrected="lynx_rufus", seq=2)
        snap = self._make_minimal_snap(det, [rev_old, rev_new])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        # Highest sequence_number wins
        assert lbl.taxon_id == "lynx_rufus"
        assert lbl.review_id == "rev_02"

    def test_multiple_reviews_all_agree_resolves(self):
        """Multiple reviews with identical decision+corrected_taxon → resolves without ambiguity."""
        det = _det("det_01", "obs_01", taxon="canis_latrans")
        rev1 = _rev("rev_01", "det_01", ReviewDecision.CONFIRM_SPECIES)
        rev2 = _rev("rev_02", "det_01", ReviewDecision.CONFIRM_SPECIES)
        snap = self._make_minimal_snap(det, [rev1, rev2])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert not lbl.is_unresolved
        assert lbl.taxon_id == "canis_latrans"

    def test_multiple_reviews_conflicting_no_sequence_number_is_unresolved(self):
        """
        Multiple reviews with conflicting decisions and no sequence_number →
        must be marked is_unresolved; resolver MUST NOT guess.
        """
        det = _det("det_01", "obs_01", taxon="canis_latrans")
        rev1 = _rev("rev_01", "det_01", ReviewDecision.CONFIRM_SPECIES)
        rev2 = _rev("rev_02", "det_01", ReviewDecision.REJECT_DETECTION)
        snap = self._make_minimal_snap(det, [rev1, rev2])
        labels = resolve_effective_labels(snap)
        lbl = labels["det_01"]
        assert lbl.is_unresolved
        assert lbl.taxon_id == _UNRESOLVED_TAXON
        assert lbl.conflict_note is not None

    def test_raw_predictions_not_mutated(self):
        """Resolver must not mutate the original Detection object."""
        det = _det("det_01", "obs_01", taxon="puma_concolor")
        original_taxon = det.predicted_taxon_id
        rev = _rev("rev_01", "det_01", ReviewDecision.CORRECT_SPECIES, corrected="lynx_rufus")
        snap = self._make_minimal_snap(det, [rev])
        _ = resolve_effective_labels(snap)
        assert det.predicted_taxon_id == original_taxon  # unchanged


# ---------------------------------------------------------------------------
# OVERVIEW METRIC TESTS
# ---------------------------------------------------------------------------

class TestOverviewMetric:
    """SYNTHETIC TEST FIXTURE."""

    def _make_snap(self) -> Snapshot:
        cam = _cam("cam_01", site_id="site_A")
        media = _media("med_01", "cam_01", T0)
        obs = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        det = _det("det_01", "obs_01", "puma_concolor")
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], start=T0, end=T1)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[media],
            observations=[obs],
            detections=[det],
            encounters=[enc],
        )

    def test_overview_ok(self):
        snap = self._make_snap()
        req = AnalysisRequest(metric=AnalysisMetric.OVERVIEW)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        assert resp.result is not None
        assert resp.result["total_cameras_in_snapshot"] == 1
        assert resp.result["total_encounters"] == 1

    def test_overview_json_serialisable(self):
        snap = self._make_snap()
        req = AnalysisRequest(metric=AnalysisMetric.OVERVIEW)
        resp = analyze(snap, req)
        # Must round-trip to JSON without error
        json_str = resp.model_dump_json()
        assert "total_encounters" in json_str


# ---------------------------------------------------------------------------
# SPECIES ENCOUNTER COUNT TESTS
# ---------------------------------------------------------------------------

class TestSpeciesEncounterCounts:
    """
    SYNTHETIC TEST FIXTURE.
    Hand-calculated counting rules:
      - One encounter with two DIFFERENT species detections → both species get 1 encounter each.
      - One encounter with SAME species twice → species gets 1 encounter (deduplicated).
      - Rejected detections excluded.
      - Unknown animal species tracked separately.
    """

    def _make_multi_species_snap(self) -> Snapshot:
        """Encounter with puma + coyote detections."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_01", T1)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_02"], T1)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        # Multi-species encounter: both detections in one encounter
        enc = _enc("enc_01", "cam_01", ["det_01", "det_02"], ["obs_01", "obs_02"], T0, T1)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[d1, d2],
            encounters=[enc],
        )

    def _make_same_species_snap(self) -> Snapshot:
        """Encounter with two puma detections → should count as 1 puma encounter."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_01", T1)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_02"], T1)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "puma_concolor")
        enc = _enc("enc_01", "cam_01", ["det_01", "det_02"], ["obs_01", "obs_02"], T0, T1)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[d1, d2],
            encounters=[enc],
        )

    def test_multi_species_encounter_contributes_once_per_species(self):
        """
        Multi-species encounter: puma + coyote.
        Each species should have encounter_count = 1.
        Summed counts (2) may exceed total_eligible_encounters (1) — documented behaviour.
        """
        snap = self._make_multi_species_snap()
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        assert result["total_eligible_encounters"] == 1
        assert result["multi_species_encounters"] == 1
        # Both species present
        taxa = {e["taxon_id"]: e["encounter_count"] for e in result["species_entries"]}
        assert taxa.get("puma_concolor") == 1
        assert taxa.get("canis_latrans") == 1
        # Sum exceeds total (documented, not an error)
        assert sum(taxa.values()) > result["total_eligible_encounters"]

    def test_same_species_two_detections_counts_once(self):
        """
        Two puma detections in one encounter → deduplication gives 1, not 2.
        """
        snap = self._make_same_species_snap()
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        result = resp.result
        taxa = {e["taxon_id"]: e["encounter_count"] for e in result["species_entries"]}
        assert taxa.get("puma_concolor") == 1

    def test_rejected_detection_excluded(self):
        """Rejected detection must not contribute any species to encounter counts."""
        cam = _cam("cam_01")
        media = _media("med_01", "cam_01", T0)
        obs = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        det = _det("det_01", "obs_01", "puma_concolor")
        rev = _rev("rev_01", "det_01", ReviewDecision.REJECT_DETECTION)
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[media],
            observations=[obs],
            detections=[det],
            encounters=[enc],
            reviews=[rev],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        result = resp.result
        assert result["rejected_detections_excluded"] == 1
        assert result["species_entries"] == []  # no animal species remain

    def test_unknown_animal_tracked_separately(self):
        """Detection with null taxon_id → unknown_animal_encounters count."""
        cam = _cam("cam_01")
        media = _media("med_01", "cam_01", T0)
        obs = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        det = _det("det_01", "obs_01", taxon=None)
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[media],
            observations=[obs],
            detections=[det],
            encounters=[enc],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        result = resp.result
        assert result["unknown_animal_encounters"] == 1
        assert result["species_entries"] == []

    def test_empty_frame_excluded(self):
        """LIKELY_EMPTY frame does not contribute to encounter species counts."""
        cam = _cam("cam_01")
        media = _media("med_01", "cam_01", T0)
        obs = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        det = _det("det_01", "obs_01", taxon=None, triage=TriageState.LIKELY_EMPTY, confidence=0.01)
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[media],
            observations=[obs],
            detections=[det],
            encounters=[enc],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        result = resp.result
        assert result["empty_frame_detections_excluded"] == 1
        assert result["species_entries"] == []

    def test_no_encounters_returns_insufficient_data(self):
        """Snapshot with no encounters returns INSUFFICIENT_DATA, not fabricated counts."""
        cam = _cam("cam_01")
        snap = Snapshot(metadata=_meta(), cameras=[cam])
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.INSUFFICIENT_DATA
        assert resp.result is None

    def test_species_filter_applied(self):
        """species_ids filter restricts which taxa appear in results."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_01", T1)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_02"], T1)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        e2 = _enc("enc_02", "cam_01", ["det_02"], ["obs_02"], T1, T2)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[d1, d2],
            encounters=[e1, e2],
        )
        req = AnalysisRequest(
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            species_ids=["puma_concolor"],
        )
        resp = analyze(snap, req)
        result = resp.result
        taxa = {e["taxon_id"] for e in result["species_entries"]}
        assert "puma_concolor" in taxa
        assert "canis_latrans" not in taxa

    def test_reviewed_only_excludes_unreviewed(self):
        """REVIEWED_ONLY policy excludes detections without a review."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_01", T1)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_02"], T1)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        rev = _rev("rev_01", "det_01", ReviewDecision.CONFIRM_SPECIES)
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        e2 = _enc("enc_02", "cam_01", ["det_02"], ["obs_02"], T1, T2)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[d1, d2],
            encounters=[e1, e2],
            reviews=[rev],
        )
        req = AnalysisRequest(
            metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            inclusion_policy=InclusionPolicy.REVIEWED_ONLY,
        )
        resp = analyze(snap, req)
        result = resp.result
        taxa = {e["taxon_id"] for e in result["species_entries"]}
        # det_01 (reviewed) → puma included; det_02 (unreviewed) excluded
        assert "puma_concolor" in taxa
        assert "canis_latrans" not in taxa


# ---------------------------------------------------------------------------
# CAMERA COMPARISON TESTS
# ---------------------------------------------------------------------------

class TestCameraComparison:
    """SYNTHETIC TEST FIXTURE."""

    def _make_two_camera_snap(self) -> Snapshot:
        cam1 = _cam("cam_01", "site_A")
        cam2 = _cam("cam_02", "site_B")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_02", T1)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_02", "med_02", ["det_02"], T1)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], ["obs_02"], T1, T2)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam1, cam2],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

    def test_camera_comparison_ok(self):
        snap = self._make_two_camera_snap()
        req = AnalysisRequest(metric=AnalysisMetric.CAMERA_COMPARISON)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        cams = {row["camera_id"]: row for row in result["cameras"]}
        assert "cam_01" in cams
        assert "cam_02" in cams
        assert cams["cam_01"]["total_encounters"] == 1
        assert cams["cam_02"]["total_encounters"] == 1

    def test_camera_filter(self):
        """camera_ids filter restricts scope to one camera."""
        snap = self._make_two_camera_snap()
        req = AnalysisRequest(
            metric=AnalysisMetric.CAMERA_COMPARISON,
            camera_ids=["cam_01"],
        )
        resp = analyze(snap, req)
        result = resp.result
        cams = {row["camera_id"] for row in result["cameras"]}
        assert "cam_01" in cams
        assert "cam_02" not in cams


# ---------------------------------------------------------------------------
# DAILY ACTIVITY TESTS
# ---------------------------------------------------------------------------

class TestDailyActivity:
    """SYNTHETIC TEST FIXTURE."""

    def _make_snap(self) -> Snapshot:
        """Encounters on two different days."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_01", T2)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_01", "med_02", ["det_02"], T2)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "canis_latrans")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        e2 = _enc("enc_02", "cam_01", ["det_02"], ["obs_02"], T2, T3)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

    def test_daily_activity_two_days(self):
        """Two encounters on different calendar days → two date buckets."""
        snap = self._make_snap()
        req = AnalysisRequest(
            metric=AnalysisMetric.DAILY_ACTIVITY,
            analysis_timezone="UTC",
        )
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        date_counts = result["date_counts"]
        # T0 is 2026-10-15, T2 is 2026-10-16
        assert "2026-10-15" in date_counts
        assert "2026-10-16" in date_counts
        assert date_counts["2026-10-15"] == 1
        assert date_counts["2026-10-16"] == 1

    def test_daily_timezone_conversion(self):
        """
        T0 = 06:00 UTC = 11:30 IST (same day).
        T3 = 17 Oct 20:00 UTC = 18 Oct 01:30 IST (next calendar day in IST).
        """
        cam = _cam("cam_01")
        # Encounter at 17 Oct 20:00 UTC = 18 Oct 01:30 IST
        m1 = _media("med_01", "cam_01", T3)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T3)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T3, T3 + timedelta(hours=1))
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(metric=AnalysisMetric.DAILY_ACTIVITY, analysis_timezone="Asia/Kolkata")
        resp = analyze(snap, req)
        result = resp.result
        # 20:00 UTC + 5:30 = 01:30 IST next day (Oct 18 in IST)
        assert "2026-10-18" in result["date_counts"]

    def test_daily_missing_timestamps_excluded(self):
        """Encounters without timestamps are excluded and counted."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        # Encounter with no timestamps
        e1 = Encounter(
            id="enc_01",
            camera_id="cam_01",
            member_detection_ids=["det_01"],
            member_observation_ids=["obs_01"],
            rule_version="v1_time_gap_30min",
        )
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(metric=AnalysisMetric.DAILY_ACTIVITY, analysis_timezone="UTC")
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.PARTIAL
        result = resp.result
        assert result["encounters_excluded_missing_timestamp"] == 1


# ---------------------------------------------------------------------------
# HOURLY ACTIVITY TESTS
# ---------------------------------------------------------------------------

class TestHourlyActivity:
    """SYNTHETIC TEST FIXTURE."""

    def _make_snap(self) -> Snapshot:
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)  # T0 = 06:00 UTC
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )

    def test_hourly_all_24_bins_present(self):
        """All 24 hour bins must exist, even if zero."""
        snap = self._make_snap()
        req = AnalysisRequest(metric=AnalysisMetric.HOURLY_ACTIVITY, analysis_timezone="UTC")
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        assert len(result["hour_counts"]) == 24
        # Hour 06 UTC should have 1 encounter
        assert result["hour_counts"]["06"] == 1
        # Hour 00 should be 0 (zero, not unavailable)
        assert result["hour_counts"]["00"] == 0

    def test_hourly_zero_distinct_from_unavailable(self):
        """Zero in a bin is a valid observed value, not unavailable data."""
        snap = self._make_snap()
        req = AnalysisRequest(metric=AnalysisMetric.HOURLY_ACTIVITY, analysis_timezone="UTC")
        resp = analyze(snap, req)
        result = resp.result
        # All zero bins must be integers, not None
        for hour_bin, count in result["hour_counts"].items():
            assert isinstance(count, int), f"Hour {hour_bin} should be int, got {type(count)}"

    def test_hourly_no_encounters_insufficient_data(self):
        """No encounters → INSUFFICIENT_DATA, not fabricated zeros."""
        cam = _cam("cam_01")
        snap = Snapshot(metadata=_meta(), cameras=[cam])
        req = AnalysisRequest(metric=AnalysisMetric.HOURLY_ACTIVITY, analysis_timezone="UTC")
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# SPECIES × CAMERA MATRIX TESTS
# ---------------------------------------------------------------------------

class TestSpeciesCameraMatrix:
    """SYNTHETIC TEST FIXTURE."""

    def _make_snap(self) -> Snapshot:
        cam1 = _cam("cam_01")
        cam2 = _cam("cam_02")
        m1 = _media("med_01", "cam_01", T0)
        m2 = _media("med_02", "cam_02", T1)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        o2 = _obs("obs_02", "cam_02", "med_02", ["det_02"], T1)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        d2 = _det("det_02", "obs_02", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        e2 = _enc("enc_02", "cam_02", ["det_02"], ["obs_02"], T1, T2)
        return Snapshot(
            metadata=_meta(),
            cameras=[cam1, cam2],
            media_assets=[m1, m2],
            observations=[o1, o2],
            detections=[d1, d2],
            encounters=[e1, e2],
        )

    def test_matrix_shape(self):
        """Matrix dimensions are species × cameras."""
        snap = self._make_snap()
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_CAMERA_MATRIX)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        assert result["species"] == ["puma_concolor"]
        assert result["cameras"] == ["cam_01", "cam_02"]
        # 1 species, 2 cameras → 1 row, 2 cols
        assert len(result["matrix"]) == 1
        assert len(result["matrix"][0]) == 2
        assert result["matrix"][0] == [1, 1]

    def test_matrix_no_encounters(self):
        snap = Snapshot(metadata=_meta(), cameras=[_cam("cam_01")])
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_CAMERA_MATRIX)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# EFFORT-NORMALISED RATE TESTS
# ---------------------------------------------------------------------------

class TestEffortNormalisedRates:
    """
    SYNTHETIC TEST FIXTURE.
    Hand-calculated expected values:
      1 camera-day = 24 × 3600 = 86400 seconds of active monitoring.
      Rate = encounters_in_effort / active_camera_days.
    """

    def _make_snap_with_effort(
        self,
        effort_start: datetime,
        effort_end: datetime,
        enc_time: datetime,
    ) -> Snapshot:
        cam = _cam("cam_01")
        media = _media("med_01", "cam_01", enc_time)
        obs = _obs("obs_01", "cam_01", "med_01", ["det_01"], enc_time)
        det = _det("det_01", "obs_01", "puma_concolor")
        enc = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], enc_time, enc_time + timedelta(hours=1))
        effort = _effort("eff_01", "cam_01", effort_start, effort_end)
        return Snapshot(
            metadata=_meta(revision=1),
            cameras=[cam],
            media_assets=[media],
            observations=[obs],
            detections=[det],
            encounters=[enc],
            monitoring_efforts=[effort],
        )

    def test_encounter_in_effort_computes_rate(self):
        """
        1 encounter, 2 days of effort → rate = 0.5 encounters/camera-day.
        Hand-calculated: 1 / 2.0 = 0.5.
        """
        eff_start = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
        eff_end = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)  # exactly 2 days
        enc_time = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # within effort
        snap = self._make_snap_with_effort(eff_start, eff_end, enc_time)
        req = AnalysisRequest(metric=AnalysisMetric.EFFORT_NORMALISED_RATES)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        cam_row = next(r for r in result["camera_rates"] if r["camera_id"] == "cam_01")
        assert cam_row["active_camera_days_in_window"] == pytest.approx(2.0, abs=0.01)
        assert cam_row["encounters_in_effort"] == 1
        assert cam_row["rate_per_camera_day"] == pytest.approx(0.5, abs=0.001)

    def test_encounter_outside_effort_counted_separately(self):
        """Encounter before effort start → counted in encounters_outside_effort."""
        eff_start = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)  # starts after enc
        eff_end = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
        enc_time = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)  # BEFORE effort
        snap = self._make_snap_with_effort(eff_start, eff_end, enc_time)
        req = AnalysisRequest(metric=AnalysisMetric.EFFORT_NORMALISED_RATES)
        resp = analyze(snap, req)
        result = resp.result
        cam_row = next(r for r in result["camera_rates"] if r["camera_id"] == "cam_01")
        assert cam_row["encounters_in_effort"] == 0
        assert cam_row["encounters_outside_effort"] == 1

    def test_no_effort_returns_insufficient_data(self):
        """Missing effort records → INSUFFICIENT_DATA, not fabricated zeros."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(metric=AnalysisMetric.EFFORT_NORMALISED_RATES)
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.INSUFFICIENT_DATA

    def test_zero_effort_in_window_no_division(self):
        """Effort outside window → 0 camera-days → rate is None, not ZeroDivisionError."""
        eff_start = datetime(2026, 10, 1, 0, 0, tzinfo=UTC)
        eff_end = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
        enc_time = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        snap = self._make_snap_with_effort(eff_start, eff_end, enc_time)
        # Request window is outside the effort period
        req = AnalysisRequest(
            metric=AnalysisMetric.EFFORT_NORMALISED_RATES,
            start_time=datetime(2026, 10, 10, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 10, 20, 0, 0, tzinfo=UTC),
        )
        resp = analyze(snap, req)
        result = resp.result
        cam_row = next(r for r in result["camera_rates"] if r["camera_id"] == "cam_01")
        assert cam_row["active_camera_days_in_window"] == pytest.approx(0.0)
        assert cam_row["rate_per_camera_day"] is None
        assert cam_row["rate_unavailable_reason"] is not None

    def test_effort_clipped_to_window(self):
        """
        Effort: Oct 15–17 (2 days), window: Oct 16–17 (1 day).
        Clipped effort = 1 day → rate = 1 encounter / 1 day = 1.0.
        """
        eff_start = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
        eff_end = datetime(2026, 10, 17, 0, 0, tzinfo=UTC)  # 2 days
        enc_time = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)  # inside window
        snap = self._make_snap_with_effort(eff_start, eff_end, enc_time)
        req = AnalysisRequest(
            metric=AnalysisMetric.EFFORT_NORMALISED_RATES,
            start_time=datetime(2026, 10, 16, 0, 0, tzinfo=UTC),  # clip to 1 day
            end_time=datetime(2026, 10, 17, 0, 0, tzinfo=UTC),
        )
        resp = analyze(snap, req)
        result = resp.result
        cam_row = next(r for r in result["camera_rates"] if r["camera_id"] == "cam_01")
        assert cam_row["active_camera_days_in_window"] == pytest.approx(1.0, abs=0.01)
        assert cam_row["rate_per_camera_day"] == pytest.approx(1.0, abs=0.001)


# ---------------------------------------------------------------------------
# REVISION MISMATCH TESTS
# ---------------------------------------------------------------------------

class TestRevisionMismatch:
    """SYNTHETIC TEST FIXTURE."""

    def test_revision_mismatch_returns_invalid_request(self):
        snap = Snapshot(metadata=_meta(revision=5))
        req = AnalysisRequest(
            metric=AnalysisMetric.OVERVIEW,
            expected_revision=42,  # wrong revision
        )
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.INVALID_REQUEST
        assert any("revision" in err.message.lower() for err in resp.errors)
        assert resp.dataset_revision == 5

    def test_correct_revision_accepted(self):
        snap = Snapshot(metadata=_meta(revision=7))
        req = AnalysisRequest(metric=AnalysisMetric.OVERVIEW, expected_revision=7)
        resp = analyze(snap, req)
        assert resp.status != ResponseStatus.INVALID_REQUEST


# ---------------------------------------------------------------------------
# REFERENCE ANNOTATION / DATASET-REFERENCE MODE TESTS
# ---------------------------------------------------------------------------

class TestDatasetReferenceMode:
    """SYNTHETIC TEST FIXTURE: verifies reference annotation contract and analytics."""

    def _make_ref_annotation(
        self,
        ann_id: str,
        obs_id: str,
        cat_id: int,
        cat_name: str,
        taxon_id: str | None,
        is_animal: bool,
        is_empty: bool = False,
    ) -> DatasetReferenceAnnotation:
        return DatasetReferenceAnnotation(
            id=f"cct:ann:{ann_id}",
            observation_id=obs_id,
            source_annotation_id=ann_id,
            source_image_id=obs_id,
            dataset_name="caltech_camera_traps",
            dataset_version="test_fixture",
            category_id=cat_id,
            category_name=cat_name,
            wildscope_taxon_id=taxon_id,
            is_animal=is_animal,
            is_empty=is_empty,
            bbox_coco=None,
            provenance={SYNTHETIC_LABEL: True},
        )

    def _make_reference_snap(self) -> Snapshot:
        cam = _cam("cct:cam:loc_01")
        m1 = _media("cct:img:img_001", "cct:cam:loc_01")
        m2 = _media("cct:img:img_002", "cct:cam:loc_01")
        o1 = _obs("cct:obs:img_001", "cct:cam:loc_01", "cct:img:img_001", [])
        o2 = _obs("cct:obs:img_002", "cct:cam:loc_01", "cct:img:img_002", [])
        ann1 = self._make_ref_annotation("ann_001", "cct:obs:img_001", 3, "coyote",
                                          "canis_latrans", True)
        ann2 = self._make_ref_annotation("ann_002", "cct:obs:img_002", 0, "empty",
                                          None, False, is_empty=True)
        return Snapshot(
            metadata=_meta(mode=DataSourceMode.DATASET_REFERENCE),
            cameras=[cam],
            media_assets=[m1, m2],
            observations=[o1, o2],
            reference_annotations=[ann1, ann2],
        )

    def test_reference_annotation_construction(self):
        """DatasetReferenceAnnotation round-trips through Pydantic."""
        ann = self._make_ref_annotation("a01", "obs_01", 3, "coyote", "canis_latrans", True)
        assert ann.category_name == "coyote"
        assert ann.wildscope_taxon_id == "canis_latrans"
        assert ann.is_animal
        assert not ann.is_empty
        assert ann.id == "cct:ann:a01"
        assert ann.source_annotation_id == "a01"

    def test_reference_annotation_no_confidence_required(self):
        """Reference annotations never need confidence scores."""
        ann = self._make_ref_annotation("a02", "obs_01", 0, "empty", None, False, is_empty=True)
        assert ann.wildscope_taxon_id is None
        # No confidence fields — construction succeeds

    def test_reference_snapshot_species_counts(self):
        """Dataset-reference mode uses image-level counts, not encounter-based."""
        snap = self._make_reference_snap()
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        # Must be clearly labelled as reference mode
        assert result["data_source_mode"] == "dataset_reference"
        assert "annotated_images" in result["counting_unit"]
        # coyote annotation → canis_latrans present
        taxa = {e["taxon_id"] for e in result["species_entries"]}
        assert "canis_latrans" in taxa
        # empty image excluded from animal counts
        assert result["empty_images_excluded"] == 1

    def test_reference_mode_labeled_in_limitations(self):
        """Reference-mode results must be explicitly labelled as NOT model predictions."""
        snap = self._make_reference_snap()
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        # Limitations must note reference mode
        combined = " ".join(resp.limitations)
        assert "reference" in combined.lower()

    def test_reference_annotations_cannot_be_in_operational_detections(self):
        """
        Reference annotations are on a separate field.
        Operational detections list must be empty in dataset_reference mode.
        """
        snap = self._make_reference_snap()
        assert snap.detections == []
        assert len(snap.reference_annotations) == 2


# ---------------------------------------------------------------------------
# EMPTY VALID DATASET TESTS
# ---------------------------------------------------------------------------

class TestEmptyValidDataset:
    """SYNTHETIC TEST FIXTURE: empty valid snapshot with zero entities."""

    def test_empty_dataset_overview(self):
        snap = Snapshot(metadata=_meta())
        req = AnalysisRequest(metric=AnalysisMetric.OVERVIEW)
        resp = analyze(snap, req)
        # Empty dataset can produce zero counts — valid result
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        assert resp.result is not None
        assert resp.result["total_cameras_in_snapshot"] == 0
        assert resp.result["total_encounters"] is None  # no encounters

    def test_empty_dataset_species_counts(self):
        snap = Snapshot(metadata=_meta())
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        # No encounters → INSUFFICIENT_DATA (not fabricated zeros)
        assert resp.status == ResponseStatus.INSUFFICIENT_DATA

    def test_empty_dataset_hourly_activity(self):
        snap = Snapshot(metadata=_meta())
        req = AnalysisRequest(metric=AnalysisMetric.HOURLY_ACTIVITY, analysis_timezone="UTC")
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# TIMEZONE / TIMESTAMP BOUNDARY TESTS
# ---------------------------------------------------------------------------

class TestTimezoneHandling:
    """SYNTHETIC TEST FIXTURE: timezone boundary and missing timestamp behaviour."""

    def test_missing_analysis_timezone_defaults_to_utc_with_warning(self):
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(
            metric=AnalysisMetric.HOURLY_ACTIVITY,
            analysis_timezone=None,  # not supplied
        )
        resp = analyze(snap, req)
        # Must produce result with UTC default
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        # Must warn about missing timezone
        assert any("timezone" in w.lower() for w in resp.warnings)

    def test_invalid_timezone_string_produces_warning(self):
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(
            metric=AnalysisMetric.HOURLY_ACTIVITY,
            analysis_timezone="NotAValidTimezone/XYZ",
        )
        resp = analyze(snap, req)
        # Must produce result (fallback to UTC) with a warning
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        assert any("timezone" in w.lower() or "utc" in w.lower() for w in resp.warnings)

    def test_encounter_without_timestamp_excluded_from_hourly(self):
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        # Encounter with no times
        e1 = Encounter(
            id="enc_01",
            camera_id="cam_01",
            member_detection_ids=["det_01"],
            rule_version="v1_time_gap_30min",
        )
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(metric=AnalysisMetric.HOURLY_ACTIVITY, analysis_timezone="UTC")
        resp = analyze(snap, req)
        assert resp.status == ResponseStatus.PARTIAL
        result = resp.result
        assert result["encounters_excluded_missing_timestamp"] == 1


# ---------------------------------------------------------------------------
# RANK_REVIEW UNAVAILABILITY TEST (Phase 3)
# ---------------------------------------------------------------------------

class TestRankReviewUnavailable:
    """rank_review() must remain UNAVAILABLE until Phase 3."""

    def test_rank_review_returns_unavailable(self):
        snap = Snapshot(metadata=_meta())
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.UNAVAILABLE
        assert resp.result is None
        assert any("Phase 3" in lim for lim in resp.limitations)

    def test_rank_review_revision_mismatch_invalid_request(self):
        snap = Snapshot(metadata=_meta(revision=3))
        req = ReviewRankingRequest(
            target_metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS,
            expected_revision=99,
        )
        resp = rank_review(snap, req)
        assert resp.status == ResponseStatus.INVALID_REQUEST


# ---------------------------------------------------------------------------
# LEGACY METRIC ALIAS TESTS
# ---------------------------------------------------------------------------

class TestLegacyMetricAliases:
    """Phase 1 legacy metric names must still work via aliasing."""

    def test_activity_time_distribution_maps_to_hourly(self):
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(
            metric=AnalysisMetric.ACTIVITY_TIME_DISTRIBUTION,
            analysis_timezone="UTC",
        )
        resp = analyze(snap, req)
        # Should produce hourly activity result (24 bins)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        assert resp.result is not None
        # Legacy alias warning
        assert any("legacy" in w.lower() or "alias" in w.lower() for w in resp.warnings)


# ---------------------------------------------------------------------------
# JSON SERIALISATION ROUND-TRIP TESTS
# ---------------------------------------------------------------------------

class TestJSONSerialisation:
    """SYNTHETIC TEST FIXTURE: ensures result envelopes are JSON-serialisable."""

    def test_overview_json_roundtrip(self):
        cam = _cam("cam_01")
        snap = Snapshot(metadata=_meta(), cameras=[cam])
        req = AnalysisRequest(metric=AnalysisMetric.OVERVIEW)
        resp = analyze(snap, req)
        json_str = resp.model_dump_json()
        parsed = json.loads(json_str)
        assert "status" in parsed
        assert "result" in parsed
        assert parsed["dataset_revision"] == 1

    def test_species_counts_json_roundtrip(self):
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        json_str = resp.model_dump_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed["result"]["species_entries"], list)

    def test_evidence_references_are_stable(self):
        """Evidence references must be deterministic across repeated calls."""
        cam = _cam("cam_01")
        m1 = _media("med_01", "cam_01", T0)
        o1 = _obs("obs_01", "cam_01", "med_01", ["det_01"], T0)
        d1 = _det("det_01", "obs_01", "puma_concolor")
        e1 = _enc("enc_01", "cam_01", ["det_01"], ["obs_01"], T0, T1)
        snap = Snapshot(
            metadata=_meta(),
            cameras=[cam],
            media_assets=[m1],
            observations=[o1],
            detections=[d1],
            encounters=[e1],
        )
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp1 = analyze(snap, req)
        resp2 = analyze(snap, req)
        assert resp1.evidence_references == resp2.evidence_references


# ---------------------------------------------------------------------------
# CALTECH ADAPTER TESTS (local file required; blocked when file absent)
# ---------------------------------------------------------------------------

class TestCaltechAdapter:
    """
    Tests for the Caltech Camera Traps adapter.
    When the annotation file is absent (sandbox/network blocked), the adapter
    returns an empty snapshot with is_blocked=True in the report.
    Tests for blocked conditions still validate adapter interface correctness.
    """

    FAKE_CCT_DATA = {
        "info": {"year": 2019, "version": "1.0", "description": "SYNTHETIC TEST FIXTURE"},
        "categories": [
            {"id": 0, "name": "empty"},
            {"id": 3, "name": "coyote"},
            {"id": 5, "name": "bobcat"},
            {"id": 99, "name": "unknown_species_xyz"},  # unmapped
        ],
        "images": [
            {"id": "img_001", "file_name": "img_001.jpg", "location": "50",
             "seq_id": "seq_A", "date_captured": "2011-05-15 14:32:10",
             "width": 1024, "height": 768},
            {"id": "img_002", "file_name": "img_002.jpg", "location": "50",
             "seq_id": "seq_A", "date_captured": "2011-05-15 14:32:15",
             "width": 1024, "height": 768},
            {"id": "img_003", "file_name": "img_003.jpg", "location": "75",
             "seq_id": "seq_B", "date_captured": "2011-05-16 08:00:00",
             "width": 1024, "height": 768},
        ],
        "annotations": [
            {"id": "ann_001", "image_id": "img_001", "category_id": 3, "bbox": [10, 20, 100, 200]},
            {"id": "ann_002", "image_id": "img_002", "category_id": 0},
            {"id": "ann_003", "image_id": "img_003", "category_id": 5},
        ],
    }

    def _write_fixture(self, tmp_path: Path) -> Path:
        """Write a minimal synthetic CCT annotation file for local testing."""
        ann_file = tmp_path / "caltech_test.json"
        ann_file.write_text(json.dumps(self.FAKE_CCT_DATA), encoding="utf-8")
        return ann_file

    def test_missing_file_returns_empty_blocked_snapshot(self, tmp_path: Path):
        """Missing annotation file → is_blocked=True, empty snapshot."""
        snap, report = import_caltech_snapshot(tmp_path / "nonexistent.json")
        assert report.is_blocked
        assert snap.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE
        assert snap.cameras == []

    def test_import_synthetic_cct_fixture(self, tmp_path: Path):
        """SYNTHETIC TEST FIXTURE: import minimal CCT JSON and verify entity counts."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file)
        assert not report.is_blocked
        # 2 unique locations → 2 cameras
        assert len(snap.cameras) == 2
        # 3 images → 3 observations
        assert len(snap.observations) == 3
        assert len(snap.media_assets) == 3
        # No operational detections (reference mode)
        assert snap.detections == []
        assert snap.prediction_runs == []
        assert snap.reviews == []
        # Reference annotations
        assert len(snap.reference_annotations) == 3
        assert snap.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE

    def test_original_category_preserved_exactly(self, tmp_path: Path):
        """Category IDs and names must be preserved exactly as published."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file)
        coyote_anns = [a for a in snap.reference_annotations if a.category_name == "coyote"]
        assert coyote_anns
        assert coyote_anns[0].category_id == 3
        assert coyote_anns[0].wildscope_taxon_id == "canis_latrans"

    def test_empty_category_is_not_animal(self, tmp_path: Path):
        """Empty category must have is_animal=False, is_empty=True."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file)
        empty_anns = [a for a in snap.reference_annotations if a.is_empty]
        assert empty_anns
        for ann in empty_anns:
            assert not ann.is_animal

    def test_namespaced_ids_avoid_collisions(self, tmp_path: Path):
        """All IDs must have 'cct:' namespace prefix."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file)
        for cam in snap.cameras:
            assert cam.id.startswith("cct:cam:")
        for obs in snap.observations:
            assert obs.id.startswith("cct:obs:")
        for media in snap.media_assets:
            assert media.id.startswith("cct:img:")
        for ann in snap.reference_annotations:
            assert ann.id.startswith("cct:ann:")

    def test_no_timezone_captured_at_is_null(self, tmp_path: Path):
        """Without timezone_policy, captured_at must be None (no silent UTC)."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file, timezone_policy=None)
        for obs in snap.observations:
            assert obs.captured_at is None, (
                f"captured_at must be None without timezone_policy; got {obs.captured_at}"
            )
        assert any("timezone" in w.lower() for w in report.missing_metadata)

    def test_with_timezone_policy_captured_at_populated(self, tmp_path: Path):
        """With timezone_policy, captured_at is populated with the supplied tz."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file, timezone_policy="US/Pacific")
        obs_with_ts = [o for o in snap.observations if o.captured_at is not None]
        assert obs_with_ts, "Expected captured_at to be populated with timezone_policy"
        for obs in obs_with_ts:
            assert obs.captured_at.tzinfo is not None

    def test_deterministic_subset_by_sorted_id(self, tmp_path: Path):
        """max_images=2 must select first 2 by sorted image ID, deterministically."""
        ann_file = self._write_fixture(tmp_path)
        snap1, _ = import_caltech_snapshot(ann_file, max_images=2)
        snap2, _ = import_caltech_snapshot(ann_file, max_images=2)
        ids1 = sorted(o.id for o in snap1.observations)
        ids2 = sorted(o.id for o in snap2.observations)
        assert ids1 == ids2, "Subset selection must be deterministic"
        assert len(snap1.observations) == 2

    def test_location_filter(self, tmp_path: Path):
        """location_ids filter restricts to specified camera locations."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file, location_ids=["50"])
        # Only location 50 images (img_001, img_002)
        assert len(snap.observations) == 2
        for cam in snap.cameras:
            assert cam.site_id == "50"

    def test_unmapped_category_preserved_with_none_taxon(self, tmp_path: Path):
        """Unknown category 'unknown_species_xyz' → wildscope_taxon_id=None, is_animal=True."""
        ann_file = self._write_fixture(tmp_path)
        # Add annotation for the unmapped category
        data = self.FAKE_CCT_DATA.copy()
        data["annotations"] = data["annotations"] + [
            {"id": "ann_999", "image_id": "img_001", "category_id": 99}
        ]
        alt_file = tmp_path / "caltech_alt.json"
        alt_file.write_text(json.dumps(data), encoding="utf-8")
        snap, report = import_caltech_snapshot(alt_file)
        unmapped_anns = [a for a in snap.reference_annotations
                         if a.category_name == "unknown_species_xyz"]
        assert unmapped_anns
        assert unmapped_anns[0].wildscope_taxon_id is None
        assert unmapped_anns[0].is_animal is True
        assert "99:unknown_species_xyz" in report.categories_unmapped

    def test_reference_mode_species_counts_via_adapter(self, tmp_path: Path):
        """Integration: import CCT fixture and run species_encounter_counts analytics."""
        ann_file = self._write_fixture(tmp_path)
        snap, report = import_caltech_snapshot(ann_file)
        req = AnalysisRequest(metric=AnalysisMetric.SPECIES_ENCOUNTER_COUNTS)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        result = resp.result
        assert result["data_source_mode"] == "dataset_reference"
        taxa = {e["taxon_id"] for e in result["species_entries"]}
        assert "canis_latrans" in taxa   # coyote → canis_latrans
        assert "lynx_rufus" in taxa      # bobcat → lynx_rufus

    def test_report_subset_rule_documented(self, tmp_path: Path):
        """Import report must document the subset selection rule."""
        ann_file = self._write_fixture(tmp_path)
        _, report = import_caltech_snapshot(ann_file, max_images=2)
        assert "2" in report.subset_rule
        assert "sorted" in report.subset_rule.lower()


# ---------------------------------------------------------------------------
# SCHEMA VERSION COMPATIBILITY TESTS
# ---------------------------------------------------------------------------

class TestSchemaVersionCompatibility:
    """Verifies both 1.0.0 and 1.1.0 snapshots are accepted."""

    def test_schema_v100_accepted(self):
        """Existing 1.0.0 snapshots must remain valid (backward compatible)."""
        from wildscope_analytics import load_and_validate_snapshot
        examples = Path(__file__).resolve().parent.parent / "examples"
        snap, report = load_and_validate_snapshot(examples / "valid_snapshot.json")
        assert report.is_valid, f"1.0.0 snapshot rejected: {report.errors}"

    def test_schema_v110_accepted(self):
        """New 1.1.0 snapshots with Phase 2 fields are valid."""
        snap = Snapshot(
            metadata=SnapshotMetadata(
                schema_version="1.1.0",
                dataset_revision=1,
                created_at=datetime.now(UTC),
                data_source_mode=DataSourceMode.DATASET_REFERENCE,
                review_ordering_mechanism=ReviewOrderingMechanism.SEQUENCE_NUMBER,
            )
        )
        from wildscope_analytics.validation import validate_snapshot_data
        report = validate_snapshot_data(snap)
        assert report.is_valid


# ---------------------------------------------------------------------------
# PHASE 2 DATASET-REFERENCE ANALYTICS: REAL CALTECH DATASET
# (Documented as BLOCKED due to sandbox network isolation)
# ---------------------------------------------------------------------------

class TestCaltechRealDatasetBlocked:
    """
    Documents the network blocker and verifies the adapter's blocked-state behaviour.

    Network blocker: socket.gaierror [Errno 11001] getaddrinfo failed
    Source: https://lila.science/datasets/caltech-camera-traps
    Metadata file: caltech_camera_traps.json.zip
    GCP path: gs://public-datasets-lila/caltechcameratraps/labels/caltech_camera_traps.json.zip

    Acquisition instructions (run outside sandbox):
      curl -L "https://lilawildlife.blob.core.windows.net/lila-wildlife/caltechcameratraps/labels/caltech_camera_traps.json.zip" \\
           -o caltech_camera_traps.json.zip
      unzip caltech_camera_traps.json.zip
      python -m wildscope_analytics.caltech_adapter caltech_camera_traps.json \\
             --timezone US/Pacific --max-images 500

    This test verifies the adapter reports the blocker honestly rather than
    silently substituting synthetic data as real dataset results.
    """

    REAL_ANNOTATION_PATH = Path("caltech_camera_traps.json")

    def test_real_dataset_blocked_reported_honestly(self):
        """
        If the real annotation file is absent, the adapter must report is_blocked=True
        and return an empty snapshot, NOT fabricated data.
        """
        if self.REAL_ANNOTATION_PATH.exists():
            pytest.skip(
                "Real Caltech annotation file found; skipping blocked test. "
                "Run test_real_dataset_integration for actual data validation."
            )
        snap, report = import_caltech_snapshot(self.REAL_ANNOTATION_PATH)
        assert report.is_blocked, "Adapter must report is_blocked=True when file is absent"
        assert report.total_images_imported == 0
        assert snap.cameras == []
        assert snap.reference_annotations == []
        assert snap.metadata.data_source_mode == DataSourceMode.DATASET_REFERENCE

    def test_real_dataset_integration(self):
        """
        Integration test against the real Caltech annotation file.
        Skipped when file is absent (sandbox network blocked).
        """
        if not self.REAL_ANNOTATION_PATH.exists():
            pytest.skip(
                "Real Caltech annotation file not present. "
                "Exact blocker: socket.gaierror [Errno 11001] getaddrinfo failed — "
                "no outbound network access from sandbox. "
                "Acquisition: curl -L <azure_url> -o caltech_camera_traps.json.zip && unzip it."
            )
        # Run with a small deterministic subset (500 images, sorted by ID)
        snap, report = import_caltech_snapshot(
            self.REAL_ANNOTATION_PATH,
            max_images=500,
            timezone_policy=None,  # no UTC assumption
        )
        # Verify report structure
        assert not report.is_blocked
        assert report.total_images_imported <= 500
        assert report.total_images_in_file > 100_000  # full dataset ~243k
        assert report.categories_total >= 20
        assert len(snap.cameras) > 0
        assert len(snap.reference_annotations) > 0
        # Run analytics
        req = AnalysisRequest(metric=AnalysisMetric.OVERVIEW)
        resp = analyze(snap, req)
        assert resp.status in (ResponseStatus.OK, ResponseStatus.PARTIAL)
        assert resp.result["data_source_mode"] == "dataset_reference"
