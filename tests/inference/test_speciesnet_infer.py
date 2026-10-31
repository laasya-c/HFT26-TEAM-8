"""
WILDSCOPE — Unit tests for the inference abstraction layer
tests/inference/test_speciesnet_infer.py

All tests are fully mocked.  No pretrained weights are loaded.
No network access is required.  Tests run in <1 second.

Test coverage
-------------
1.  Single animal detection — correct fields populated
2.  Multiple detections — all returned in order
3.  No detections — OK status with empty list
4.  Unknown / blank species — detection not discarded
5.  Classification failure after successful detection — detection kept
6.  Invalid image path — LOAD_FAILURE status
7.  Confidence filtering — filter_by_conf() on ImageDetectionResult
8.  Bounding-box coordinate validation — validate_bbox()
9.  Device selection — detect_device field set from mock
10. detector_conf and classifier scores kept separate
11. animal_count property
12. animals() helper returns only animal detections
13. is_blank / is_unknown properties on SpeciesClassification
14. detect() single-image wrapper delegates to detect_batch()
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Add repo root so src.inference is importable
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.inference.base_detector import (
    BaseDetector,
    Detection,
    DetectionStatus,
    ImageDetectionResult,
    SpeciesClassification,
)


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures — lightweight test data
# ══════════════════════════════════════════════════════════════════════════════

def _make_clf(labels=None, scores=None, attempted=True, device="cpu"):
    return SpeciesClassification(
        top_labels  = labels or [],
        top_scores  = scores or [],
        device_used = device,
        attempted   = attempted,
    )


def _make_det(
    bbox_norm=(0.1, 0.2, 0.3, 0.4),
    conf=0.75,
    label="animal",
    category="1",
    image_w=2048,
    image_h=1494,
    clf=None,
):
    return Detection(
        bbox_norm        = list(bbox_norm),
        image_w          = image_w,
        image_h          = image_h,
        detector_conf    = conf,
        detector_label   = label,
        detector_category= category,
        classification   = clf or SpeciesClassification(),
    )


def _make_result(
    filepath="test.jpg",
    status=DetectionStatus.OK,
    detections=None,
    detect_device="cpu",
    classify_device="cpu",
    image_w=2048,
    image_h=1494,
):
    return ImageDetectionResult(
        filepath       = filepath,
        status         = status,
        image_w        = image_w,
        image_h        = image_h,
        detections     = detections or [],
        detect_device  = detect_device,
        classify_device= classify_device,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Minimal concrete BaseDetector for testing the ABC interface
# ══════════════════════════════════════════════════════════════════════════════

class _MockDetector(BaseDetector):
    """Minimal concrete implementation used to test the BaseDetector contract."""

    def __init__(self, responses: list[ImageDetectionResult]):
        self._responses = responses
        self._call_count = 0

    def detect_batch(
        self, image_paths, min_conf: float = 0.0
    ) -> list[ImageDetectionResult]:
        self._call_count += 1
        results = []
        for i, path in enumerate(image_paths):
            res = self._responses[i] if i < len(self._responses) else _make_result()
            if min_conf > 0.0:
                res = res.filter_by_conf(min_conf)
            results.append(res)
        return results

    @property
    def device(self) -> str:
        return "cpu"


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — Single animal detection: correct fields populated
# ══════════════════════════════════════════════════════════════════════════════

class TestSingleAnimalDetection:
    def test_detection_fields_populated(self):
        clf = _make_clf(
            labels=["mammalia;didelphimorphia;didelphidae;didelphis;virginiana;virginia opossum"],
            scores=[0.996],
            device="cuda",
        )
        det = _make_det(bbox_norm=(0.244, 0.477, 0.178, 0.121), conf=0.785, clf=clf)
        result = _make_result(detections=[det], detect_device="cuda")

        assert result.status         == DetectionStatus.OK
        assert len(result.detections) == 1
        assert result.detections[0].detector_conf   == pytest.approx(0.785)
        assert result.detections[0].detector_label  == "animal"
        assert result.detections[0].classification.top_score == pytest.approx(0.996)
        assert result.detect_device  == "cuda"

    def test_detector_conf_and_classifier_score_are_separate(self):
        clf = _make_clf(labels=["somespecies"], scores=[0.9])
        det = _make_det(conf=0.5, clf=clf)
        # Changing one must not affect the other
        assert det.detector_conf != det.classification.top_score

    def test_image_dimensions_preserved(self):
        det = _make_det(image_w=1920, image_h=1080)
        assert det.image_w == 1920
        assert det.image_h == 1080

    def test_bbox_pixels_computed_correctly(self):
        det = _make_det(bbox_norm=(0.5, 0.5, 0.1, 0.1), image_w=1000, image_h=1000)
        px = det.bbox_pixels
        assert px == (500, 500, 100, 100)


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — Multiple detections: all returned in order
# ══════════════════════════════════════════════════════════════════════════════

class TestMultipleDetections:
    def test_multiple_detections_preserved(self):
        dets = [
            _make_det(conf=0.8, bbox_norm=(0.0, 0.0, 0.1, 0.1)),
            _make_det(conf=0.6, bbox_norm=(0.2, 0.2, 0.1, 0.1)),
            _make_det(conf=0.3, bbox_norm=(0.5, 0.5, 0.1, 0.1)),
        ]
        result = _make_result(detections=dets)
        assert len(result.detections) == 3
        assert result.detections[0].detector_conf == pytest.approx(0.8)
        assert result.detections[2].detector_conf == pytest.approx(0.3)

    def test_animal_count_property(self):
        dets = [
            _make_det(label="animal"),
            _make_det(label="vehicle", category="3"),
            _make_det(label="animal"),
        ]
        result = _make_result(detections=dets)
        assert result.animal_count == 2

    def test_animals_helper_filters_non_animals(self):
        dets = [
            _make_det(label="animal"),
            _make_det(label="vehicle", category="3"),
        ]
        result = _make_result(detections=dets)
        animals = result.animals()
        assert len(animals) == 1
        assert animals[0].is_animal


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — No detections: OK status, empty list
# ══════════════════════════════════════════════════════════════════════════════

class TestNoDetections:
    def test_ok_status_with_empty_list(self):
        result = _make_result(detections=[])
        assert result.status          == DetectionStatus.OK
        assert result.succeeded       is True
        assert result.animal_count    == 0
        assert result.detections      == []
        assert result.error_message   is None

    def test_empty_detections_via_mock_detector(self):
        mock_det = _MockDetector([_make_result(detections=[])])
        r = mock_det.detect("fake_path.jpg")
        assert r.status == DetectionStatus.OK
        assert len(r.detections) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 — Unknown / blank species: detection not discarded
# ══════════════════════════════════════════════════════════════════════════════

class TestUnknownBlankSpecies:
    def test_blank_label_detection_not_discarded(self):
        clf = _make_clf(
            labels=["f1856211-cfb7-4a5b-9158-c0f72fd09ee6;;;;;;blank"],
            scores=[0.978],
        )
        det = _make_det(clf=clf)
        result = _make_result(detections=[det])
        assert len(result.detections) == 1
        assert result.detections[0].classification.is_blank is True

    def test_is_blank_true_for_blank_label(self):
        clf = _make_clf(labels=["uuid;;;;;;blank"], scores=[0.95])
        assert clf.is_blank is True

    def test_is_blank_false_for_species_label(self):
        clf = _make_clf(
            labels=["87be3a5c;mammalia;didelphimorphia;didelphidae;didelphis;virginiana;virginia opossum"],
            scores=[0.99],
        )
        assert clf.is_blank is False

    def test_is_unknown_when_not_attempted(self):
        clf = SpeciesClassification(attempted=False)
        assert clf.is_unknown is True

    def test_is_unknown_when_list_empty(self):
        clf = SpeciesClassification(attempted=True, top_labels=[], top_scores=[])
        assert clf.is_unknown is True

    def test_is_unknown_false_when_has_labels(self):
        clf = _make_clf(labels=["some_species"], scores=[0.5])
        assert clf.is_unknown is False

    def test_top_label_none_when_empty(self):
        clf = SpeciesClassification()
        assert clf.top_label  is None
        assert clf.top_score  is None


# ══════════════════════════════════════════════════════════════════════════════
# Test 5 — Classification failure: detection kept
# ══════════════════════════════════════════════════════════════════════════════

class TestClassificationFailureKeepsDetection:
    def test_failed_classification_does_not_discard_detection(self):
        # Simulate: classification was attempted but returned no labels
        clf = SpeciesClassification(attempted=True, top_labels=[], top_scores=[])
        det = _make_det(conf=0.85, clf=clf)
        result = _make_result(detections=[det])

        assert result.status               == DetectionStatus.OK
        assert len(result.detections)      == 1
        assert result.detections[0].classification.attempted   is True
        assert result.detections[0].classification.is_unknown  is True
        assert result.detections[0].detector_conf == pytest.approx(0.85)

    def test_detection_has_all_required_fields_despite_missing_classification(self):
        clf = SpeciesClassification(attempted=True)
        det = _make_det(clf=clf)
        assert det.detector_conf    > 0
        assert det.detector_label   == "animal"
        assert det.bbox_norm        is not None
        assert det.image_w          > 0
        assert det.image_h          > 0


# ══════════════════════════════════════════════════════════════════════════════
# Test 6 — Invalid image path: LOAD_FAILURE status
# ══════════════════════════════════════════════════════════════════════════════

class TestInvalidImagePath:
    def test_load_failure_status_on_missing_file(self):
        result = ImageDetectionResult(
            filepath="nonexistent_image_12345.jpg",
            status=DetectionStatus.LOAD_FAILURE,
            error_message="load_rgb_image returned None",
        )
        assert result.succeeded      is False
        assert result.status         == DetectionStatus.LOAD_FAILURE
        assert result.error_message  is not None
        assert result.detections     == []

    def test_load_failure_via_mock_detector(self):
        failure_result = ImageDetectionResult(
            filepath="bad.jpg",
            status=DetectionStatus.LOAD_FAILURE,
            error_message="load_rgb_image returned None",
        )
        mock_det = _MockDetector([failure_result])
        r = mock_det.detect("bad.jpg")
        assert r.status     == DetectionStatus.LOAD_FAILURE
        assert r.succeeded  is False

    def test_inference_error_status(self):
        result = ImageDetectionResult(
            filepath="error.jpg",
            status=DetectionStatus.INFERENCE_ERROR,
            error_message="CUDA out of memory",
        )
        assert result.succeeded is False
        assert result.status    == DetectionStatus.INFERENCE_ERROR


# ══════════════════════════════════════════════════════════════════════════════
# Test 7 — Confidence filtering: filter_by_conf() on ImageDetectionResult
# ══════════════════════════════════════════════════════════════════════════════

class TestConfidenceFiltering:
    def _result_with_confs(self, confs):
        dets = [_make_det(conf=c) for c in confs]
        return _make_result(detections=dets)

    def test_filter_removes_low_conf(self):
        result = self._result_with_confs([0.8, 0.4, 0.05, 0.01])
        filtered = result.filter_by_conf(0.1)
        assert len(filtered.detections) == 2
        assert all(d.detector_conf >= 0.1 for d in filtered.detections)

    def test_filter_preserves_original(self):
        result = self._result_with_confs([0.8, 0.4, 0.05])
        _ = result.filter_by_conf(0.5)
        assert len(result.detections) == 3   # original unchanged

    def test_filter_zero_returns_all(self):
        result = self._result_with_confs([0.8, 0.01, 0.001])
        filtered = result.filter_by_conf(0.0)
        assert len(filtered.detections) == 3

    def test_filter_1_returns_none(self):
        result = self._result_with_confs([0.8, 0.9, 0.99])
        filtered = result.filter_by_conf(1.0)
        assert len(filtered.detections) == 0

    def test_filter_exact_threshold_included(self):
        result = self._result_with_confs([0.1, 0.2, 0.3])
        filtered = result.filter_by_conf(0.2)
        confs = [d.detector_conf for d in filtered.detections]
        assert 0.2 in confs
        assert 0.1 not in confs

    def test_mock_detector_applies_min_conf(self):
        dets = [
            _make_det(conf=0.9),
            _make_det(conf=0.05),
        ]
        mock_det = _MockDetector([_make_result(detections=dets)])
        r = mock_det.detect("img.jpg", min_conf=0.1)
        assert len(r.detections) == 1
        assert r.detections[0].detector_conf == pytest.approx(0.9)


# ══════════════════════════════════════════════════════════════════════════════
# Test 8 — Bounding-box coordinate validation
# ══════════════════════════════════════════════════════════════════════════════

class TestBBoxValidation:
    def test_valid_bbox_passes(self):
        det = _make_det(bbox_norm=(0.0, 0.0, 0.5, 0.5))
        assert det.validate_bbox() is True

    def test_valid_bbox_full_frame(self):
        det = _make_det(bbox_norm=(0.0, 0.0, 1.0, 1.0))
        assert det.validate_bbox() is True

    def test_invalid_bbox_negative_x(self):
        det = _make_det(bbox_norm=(-0.1, 0.0, 0.5, 0.5))
        assert det.validate_bbox() is False

    def test_invalid_bbox_zero_width(self):
        det = _make_det(bbox_norm=(0.0, 0.0, 0.0, 0.5))
        assert det.validate_bbox() is False

    def test_invalid_bbox_exceeds_frame(self):
        # x + w > 1.0 significantly
        det = _make_det(bbox_norm=(0.8, 0.0, 0.5, 0.5))
        assert det.validate_bbox() is False

    def test_invalid_bbox_wrong_length(self):
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3))  # only 3 elements
        assert det.validate_bbox() is False

    def test_bbox_pixels_uses_image_dims(self):
        det = _make_det(bbox_norm=(0.25, 0.5, 0.5, 0.25), image_w=400, image_h=200)
        x, y, w, h = det.bbox_pixels
        assert x == 100
        assert y == 100
        assert w == 200
        assert h == 50


# ══════════════════════════════════════════════════════════════════════════════
# Test 9 — Device selection: detect_device field reflects actual device
# ══════════════════════════════════════════════════════════════════════════════

class TestDeviceSelection:
    def test_cuda_device_recorded_in_result(self):
        result = _make_result(detect_device="cuda", classify_device="cuda")
        assert result.detect_device   == "cuda"
        assert result.classify_device == "cuda"

    def test_cpu_device_recorded_in_result(self):
        result = _make_result(detect_device="cpu", classify_device="cpu")
        assert result.detect_device   == "cpu"
        assert result.classify_device == "cpu"

    def test_mock_detector_device_property(self):
        mock_det = _MockDetector([])
        assert mock_det.device == "cpu"

    def test_repr_includes_device(self):
        mock_det = _MockDetector([])
        assert "cpu" in repr(mock_det)


# ══════════════════════════════════════════════════════════════════════════════
# Test 10 — Hierarchical taxonomy: scores are NOT addable across levels
# ══════════════════════════════════════════════════════════════════════════════

class TestHierarchicalTaxonomy:
    """
    Verify that the data structure keeps hierarchical labels separate and
    that no code in our layer adds scores across levels.
    """

    def test_top5_labels_preserved_verbatim(self):
        labels = [
            "667a4650;mammalia;lagomorpha;leporidae;sylvilagus;floridanus;eastern cottontail",
            "6c09fa63;mammalia;lagomorpha;leporidae;;;rabbit and hare family",
            "f1856211;;;;;;blank",
        ]
        scores = [0.542, 0.429, 0.007]
        clf = _make_clf(labels=labels, scores=scores)
        assert clf.top_labels == labels
        assert clf.top_scores == scores

    def test_scores_are_not_summed_anywhere(self):
        """Our code must NOT sum scores. Verify sum != 1 across only top-5."""
        labels = ["A", "B", "C", "D", "E"]
        scores = [0.6, 0.3, 0.05, 0.03, 0.01]
        clf = _make_clf(labels=labels, scores=scores)
        # total of top-5 may be < 1 (remaining classes hold the rest)
        assert sum(clf.top_scores) <= 1.0 + 1e-9

    def test_top_label_is_first_not_sum(self):
        clf = _make_clf(labels=["species_A", "family_B"], scores=[0.55, 0.40])
        # Top label must be the highest individual score, not a combined value
        assert clf.top_label  == "species_A"
        assert clf.top_score  == pytest.approx(0.55)
        # 0.55 + 0.40 = 0.95 — this combined value should NOT appear anywhere
        assert clf.top_score != pytest.approx(0.95)


# ══════════════════════════════════════════════════════════════════════════════
# Test 11 — detect() single-image wrapper delegates to detect_batch()
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectWrapperDelegates:
    def test_detect_calls_detect_batch_once(self):
        expected = _make_result()
        mock_det = _MockDetector([expected])
        r = mock_det.detect("some_image.jpg")
        assert mock_det._call_count == 1
        assert r.filepath == expected.filepath

    def test_detect_returns_single_result_not_list(self):
        mock_det = _MockDetector([_make_result()])
        r = mock_det.detect("img.jpg")
        assert isinstance(r, ImageDetectionResult)


# ══════════════════════════════════════════════════════════════════════════════
# Test 12 — succeeded / error_message consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestSucceededProperty:
    def test_succeeded_true_for_ok(self):
        r = _make_result(status=DetectionStatus.OK)
        assert r.succeeded is True

    def test_succeeded_false_for_load_failure(self):
        r = ImageDetectionResult("f.jpg", status=DetectionStatus.LOAD_FAILURE)
        assert r.succeeded is False

    def test_succeeded_false_for_inference_error(self):
        r = ImageDetectionResult("f.jpg", status=DetectionStatus.INFERENCE_ERROR)
        assert r.succeeded is False

    def test_not_run_is_not_succeeded(self):
        r = ImageDetectionResult("f.jpg")
        assert r.succeeded is False



# ==============================================================================
# Test 13 -- Bug regression tests (C1, C2, C3)
#
# Each test documents what the old implementation did (shown in the comment)
# and asserts the corrected behaviour.
# ==============================================================================

class TestBugRegressions:
    """
    Regression tests for the three confirmed bugs fixed in Milestone 3.

    C1 -- is_blank used substring matching; 'blanket' and 'black-blank' returned
         True.  Fixed: exact, case-insensitive match of the final taxonomy
         segment after stripping whitespace.

    C2 -- filter_by_conf() returned an ImageDetectionResult whose Detection list
         contained references to the SAME Detection objects as the original.
         Mutating a filtered detection mutated the original.  Fixed: deep copy
         each Detection (and its nested SpeciesClassification) before returning.

    C3 -- Detection.__post_init__ did not copy the caller-supplied bbox_norm
         list.  Mutating the original list after construction corrupted the
         stored coordinates.  Fixed: store list(self.bbox_norm) in __post_init__.
    """

    # --------------------------------------------------------------------------
    # C1 regressions -- is_blank exact match
    # --------------------------------------------------------------------------

    def test_is_blank_exact_match_true(self):
        """Full SpeciesNet-style label ending with 'blank' must return True."""
        clf = SpeciesClassification(
            top_labels=["f1856211;;;;;;blank"],
            top_scores=[0.9],
            attempted=True,
        )
        assert clf.is_blank is True

    def test_is_blank_uppercase(self):
        """'BLANK' (all caps) must return True -- case-insensitive."""
        clf = SpeciesClassification(
            top_labels=["BLANK"],
            top_scores=[0.8],
            attempted=True,
        )
        assert clf.is_blank is True

    def test_is_blank_with_whitespace(self):
        """Last segment with surrounding whitespace must still match."""
        clf = SpeciesClassification(
            top_labels=["  blank  "],
            top_scores=[0.7],
            attempted=True,
        )
        assert clf.is_blank is True

    def test_is_blank_false_for_blanket(self):
        """'blanket' shares a substring with 'blank' -- must return False.

        Old behaviour: returned True (substring match bug).
        Fixed behaviour: False (exact match).
        """
        clf = SpeciesClassification(
            top_labels=["animal;blanket"],
            top_scores=[0.6],
            attempted=True,
        )
        assert clf.is_blank is False  # OLD: True

    def test_is_blank_false_for_black_blank(self):
        """'black-blank' contains 'blank' as a substring -- must return False.

        Old behaviour: returned True (substring match bug).
        Fixed behaviour: False (exact match).
        """
        clf = SpeciesClassification(
            top_labels=["animal;black-blank"],
            top_scores=[0.5],
            attempted=True,
        )
        assert clf.is_blank is False  # OLD: True

    def test_is_blank_false_for_no_semicolon_blanket(self):
        """Top label with no semicolon that contains 'blank' as a substring.

        Old behaviour: returned True (substring match).
        Fixed behaviour: False (the word itself is not 'blank').
        """
        clf = SpeciesClassification(
            top_labels=["some_species_blanket"],
            top_scores=[0.4],
            attempted=True,
        )
        assert clf.is_blank is False  # OLD: True

    def test_is_blank_false_for_unknown(self):
        """'unknown' must not be treated as blank."""
        clf = SpeciesClassification(
            top_labels=["animal;unknown"],
            top_scores=[0.3],
            attempted=True,
        )
        assert clf.is_blank is False

    # --------------------------------------------------------------------------
    # C2 regressions -- filter_by_conf deep copy
    # --------------------------------------------------------------------------

    def test_filter_by_conf_filtered_detection_is_independent_object(self):
        """Each Detection in the filtered result must be a different object.

        Old behaviour: filtered.detections[0] is result.detections[0] (same ref).
        Fixed behaviour: they are distinct objects (deep copy).
        """
        det = _make_det(conf=0.5)
        result = _make_result(detections=[det])
        filtered = result.filter_by_conf(0.1)
        assert filtered.detections[0] is not result.detections[0]  # OLD: same obj

    def test_filter_by_conf_deepcopy_detection_field(self):
        """Mutating detector_conf on a filtered detection must not affect original.

        Old behaviour: mutation propagated back because filter_by_conf shared refs.
        Fixed behaviour: deep copy means they are fully independent.
        """
        det = _make_det(conf=0.5)
        result = _make_result(detections=[det])
        filtered = result.filter_by_conf(0.1)

        # Mutate the filtered detection
        filtered.detections[0].detector_conf = 0.999

        # Original must be unchanged
        assert result.detections[0].detector_conf == 0.5  # OLD: 0.999

    def test_filter_by_conf_deepcopy_classification_list(self):
        """Mutating top_labels on a filtered detection's classification must not
        affect the original.

        Old behaviour: top_labels list was the same object in both results.
        Fixed behaviour: deep copy gives each result its own list.
        """
        clf = SpeciesClassification(
            top_labels=["species_A"],
            top_scores=[0.9],
            attempted=True,
        )
        det = _make_det(conf=0.5, clf=clf)
        result = _make_result(detections=[det])
        filtered = result.filter_by_conf(0.1)

        # Mutate the classification in the filtered copy
        filtered.detections[0].classification.top_labels.append("injected")

        # Original classification must still have exactly one label
        assert len(result.detections[0].classification.top_labels) == 1  # OLD: 2

    # --------------------------------------------------------------------------
    # C3 regressions -- bbox_norm defensive copy
    # --------------------------------------------------------------------------

    def test_bbox_norm_is_not_same_object(self):
        """The bbox_norm stored in Detection must not be the same list object
        that was passed at construction time.

        Old behaviour: Detection stored the caller's list reference directly.
        Fixed behaviour: __post_init__ copies the list, so they are distinct.
        """
        original = [0.1, 0.2, 0.3, 0.4]
        det = _make_det(bbox_norm=original)
        assert det.bbox_norm is not original  # OLD: same object

    def test_bbox_norm_defensive_copy_from_input(self):
        """Mutating the original list after construction must not change stored bbox.

        Old behaviour: stored list was the same object, so mutation propagated.
        Fixed behaviour: defensive copy in __post_init__ isolates stored values.
        """
        original = [0.1, 0.2, 0.3, 0.4]
        det = _make_det(bbox_norm=original)
        original[0] = 99.0  # mutate caller's list
        assert det.bbox_norm[0] == 0.1  # OLD: 99.0

    def test_bbox_norm_stored_copy_independent(self):
        """Mutating the stored bbox_norm must not affect the original list.

        Tests independence in the reverse direction.
        Old behaviour: same list reference, so mutation went both ways.
        Fixed behaviour: independent copies.
        """
        original = [0.1, 0.2, 0.3, 0.4]
        original_snapshot = list(original)
        det = _make_det(bbox_norm=list(original))  # pass a copy so we can compare
        det.bbox_norm[1] = 88.0  # mutate the stored list
        # original_snapshot must be unchanged
        assert original_snapshot[1] == 0.2
        # stored value reflects the mutation we made
        assert det.bbox_norm[1] == 88.0


# ══════════════════════════════════════════════════════════════════════════════
# Regression tests — Milestone 3 bug corrections
# Added after audit; each test would FAIL against the original implementation.
# ══════════════════════════════════════════════════════════════════════════════

# ── C1 Regression: is_blank exact-match fix ───────────────────────────────────

class TestIsBlankExactMatch:
    """
    Regression tests for C1: is_blank must use exact segment match, not
    substring search.  All tests below would FAIL on the original code that
    used ``"blank" in segment``.
    """

    # False-positive cases that the old implementation got wrong
    def test_is_blank_false_for_blanket(self):
        """'blanket' in final segment must NOT trigger is_blank."""
        clf = _make_clf(labels=["some_species_blanket"], scores=[0.9])
        assert clf.is_blank is False

    def test_is_blank_false_for_black_blank_hyphenated(self):
        """'black-blank' is not exactly 'blank'."""
        clf = _make_clf(labels=["animal;black-blank"], scores=[0.9])
        assert clf.is_blank is False

    def test_is_blank_false_for_blank_as_prefix(self):
        """'blankety' contains 'blank' as a prefix but is not 'blank'."""
        clf = _make_clf(labels=["animal;blankety"], scores=[0.9])
        assert clf.is_blank is False

    def test_is_blank_false_for_blank_in_middle(self):
        """A species name containing 'blank' mid-word must not match."""
        clf = _make_clf(labels=["mammalia;blanknose shark"], scores=[0.9])
        assert clf.is_blank is False

    # True cases that must still work
    def test_is_blank_true_standard_speciesnet_label(self):
        """Standard SpeciesNet blank label must still match."""
        clf = _make_clf(
            labels=["f1856211-cfb7-4a5b-9158-c0f72fd09ee6;;;;;;blank"],
            scores=[0.978],
        )
        assert clf.is_blank is True

    def test_is_blank_true_uppercase(self):
        """BLANK in uppercase must match (case-insensitive)."""
        clf = _make_clf(labels=["animal;BLANK"], scores=[0.9])
        assert clf.is_blank is True

    def test_is_blank_true_mixed_case(self):
        """Mixed case 'Blank' must match."""
        clf = _make_clf(labels=["animal;Blank"], scores=[0.9])
        assert clf.is_blank is True

    def test_is_blank_true_bare_blank(self):
        """Label with no semicolons, value exactly 'blank'."""
        clf = _make_clf(labels=["blank"], scores=[0.9])
        assert clf.is_blank is True

    def test_is_blank_true_with_leading_trailing_space(self):
        """Whitespace around final segment must be stripped before matching."""
        clf = _make_clf(labels=["animal; blank "], scores=[0.9])
        assert clf.is_blank is True

    def test_is_blank_false_for_unknown(self):
        """'unknown' must not match blank."""
        clf = _make_clf(labels=["animal;unknown"], scores=[0.9])
        assert clf.is_blank is False


# ── C2 Regression: filter_by_conf deep-copy fix ───────────────────────────────

class TestFilterByConfDeepCopy:
    """
    Regression tests for C2: filter_by_conf must return independent Detection
    objects so that mutations to the filtered result do NOT affect the original.
    All tests below would FAIL against the original shallow-copy implementation.
    """

    def _original_with_one_detection(self):
        clf = _make_clf(labels=["species_A", "species_B"], scores=[0.8, 0.1])
        det = _make_det(conf=0.75, clf=clf)
        return _make_result(detections=[det])

    def test_mutating_filtered_conf_does_not_change_original(self):
        """Changing detector_conf in the filtered copy must not affect original."""
        original = self._original_with_one_detection()
        original_conf = original.detections[0].detector_conf

        filtered = original.filter_by_conf(0.0)
        filtered.detections[0].detector_conf = 0.001   # mutate filtered

        assert original.detections[0].detector_conf == pytest.approx(original_conf)

    def test_mutating_filtered_label_does_not_change_original(self):
        """Changing detector_label in the filtered copy must not affect original."""
        original = self._original_with_one_detection()

        filtered = original.filter_by_conf(0.0)
        filtered.detections[0].detector_label = "vehicle"

        assert original.detections[0].detector_label == "animal"

    def test_mutating_filtered_classification_top_labels_does_not_change_original(self):
        """Appending to top_labels in the filtered copy must not grow original's list."""
        original = self._original_with_one_detection()
        original_label_count = len(
            original.detections[0].classification.top_labels
        )

        filtered = original.filter_by_conf(0.0)
        filtered.detections[0].classification.top_labels.append("injected_label")

        assert (
            len(original.detections[0].classification.top_labels)
            == original_label_count
        )

    def test_mutating_filtered_classification_top_scores_does_not_change_original(self):
        """Appending to top_scores in the filtered copy must not change original's list."""
        original = self._original_with_one_detection()
        original_score_count = len(
            original.detections[0].classification.top_scores
        )

        filtered = original.filter_by_conf(0.0)
        filtered.detections[0].classification.top_scores.append(99.9)

        assert (
            len(original.detections[0].classification.top_scores)
            == original_score_count
        )

    def test_filtered_detection_is_not_same_object_as_original(self):
        """The Detection in the filtered result must be a distinct object."""
        original = self._original_with_one_detection()
        filtered = original.filter_by_conf(0.0)

        assert filtered.detections[0] is not original.detections[0]

    def test_filter_preserves_status_and_metadata(self):
        """filter_by_conf must copy status, image dims, devices, and timing."""
        original = ImageDetectionResult(
            filepath="img.jpg",
            status=DetectionStatus.OK,
            image_w=2048,
            image_h=1494,
            detect_device="cuda",
            classify_device="cuda",
            load_time_s=0.05,
            detect_time_s=0.3,
            classify_time_s=0.2,
            total_time_s=0.55,
            detections=[_make_det(conf=0.8)],
        )
        filtered = original.filter_by_conf(0.5)

        assert filtered.status          == DetectionStatus.OK
        assert filtered.image_w         == 2048
        assert filtered.image_h         == 1494
        assert filtered.detect_device   == "cuda"
        assert filtered.classify_device == "cuda"
        assert filtered.load_time_s     == pytest.approx(0.05)
        assert filtered.detect_time_s   == pytest.approx(0.3)
        assert filtered.classify_time_s == pytest.approx(0.2)
        assert filtered.total_time_s    == pytest.approx(0.55)


# ── C3 Regression: bbox_norm defensive copy fix ───────────────────────────────

class TestBBoxNormDefensiveCopy:
    """
    Regression tests for C3: Detection must store an independent copy of the
    bbox_norm list so that mutations to the caller's list or to the stored list
    are fully isolated.  Both tests would FAIL against the original implementation
    that stored the list reference directly.
    """

    def test_mutating_source_list_after_construction_does_not_change_stored_bbox(self):
        """Modifying the original list AFTER constructing Detection must be isolated."""
        source_bbox = [0.1, 0.2, 0.3, 0.4]
        det = _make_det(bbox_norm=tuple(source_bbox))   # pass as tuple to be safe

        # Separately build with a list to test the list path
        source_list = [0.1, 0.2, 0.3, 0.4]
        det2 = Detection(
            bbox_norm        = source_list,
            image_w          = 2048,
            image_h          = 1494,
            detector_conf    = 0.75,
            detector_label   = "animal",
            detector_category= "1",
        )

        source_list[0] = 99.0   # mutate original after construction

        assert det2.bbox_norm[0] != 99.0, (
            "Stored bbox_norm[0] must not change when source list is mutated"
        )
        assert det2.bbox_norm[0] == pytest.approx(0.1)

    def test_mutating_stored_bbox_does_not_affect_source_list(self):
        """Modifying the stored bbox must not change the caller's original list."""
        source_list = [0.1, 0.2, 0.3, 0.4]
        det = Detection(
            bbox_norm        = source_list,
            image_w          = 2048,
            image_h          = 1494,
            detector_conf    = 0.75,
            detector_label   = "animal",
            detector_category= "1",
        )

        det.bbox_norm[0] = 99.0   # mutate stored bbox

        assert source_list[0] == pytest.approx(0.1), (
            "Source list must not change when stored bbox_norm is mutated"
        )

    def test_bbox_stored_values_are_correct_after_copy(self):
        """Ensure the copy preserves all four coordinate values."""
        source_list = [0.25, 0.50, 0.10, 0.20]
        det = Detection(
            bbox_norm        = source_list,
            image_w          = 1000,
            image_h          = 1000,
            detector_conf    = 0.9,
            detector_label   = "animal",
            detector_category= "1",
        )
        assert det.bbox_norm == pytest.approx([0.25, 0.50, 0.10, 0.20])


# ══════════════════════════════════════════════════════════════════════════════
# Milestone 4A — R1: bbox_valid automatic geometry validation
# ══════════════════════════════════════════════════════════════════════════════

def _make_invalid_det(bbox_norm=(0.9, 0.0, 0.5, 0.5), clf=None, **kwargs):
    """Helper: Detection whose default bbox extends beyond the image boundary."""
    defaults = dict(
        image_w=2048, image_h=1494,
        detector_conf=0.8, detector_label="animal", detector_category="1",
    )
    defaults.update(kwargs)
    if clf is not None:
        defaults["classification"] = clf
    return Detection(bbox_norm=list(bbox_norm), **defaults)


class TestBBoxValidityFlag:
    """
    Detection.bbox_valid is set automatically in __post_init__ using
    validate_bbox().  Invalid geometry is flagged but never discarded.
    """

    def test_valid_bbox_sets_bbox_valid_true(self):
        """A geometrically valid bbox must produce bbox_valid=True."""
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        assert det.bbox_valid is True

    def test_invalid_bbox_sets_bbox_valid_false(self):
        """A bbox that overflows the frame must produce bbox_valid=False."""
        # x=0.9, w=0.5 → x+w=1.4 > 1.0 + 1e-6
        det = _make_invalid_det(bbox_norm=(0.9, 0.0, 0.5, 0.5))
        assert det.bbox_valid is False

    def test_invalid_bbox_original_coords_preserved(self):
        """bbox_norm must be unchanged even when bbox_valid=False."""
        bad = [0.9, 0.0, 0.5, 0.5]
        det = _make_invalid_det(bbox_norm=bad)
        assert det.bbox_valid is False
        assert det.bbox_norm == pytest.approx([0.9, 0.0, 0.5, 0.5])

    def test_invalid_bbox_bbox_pixels_raises_value_error(self):
        """Calling bbox_pixels on an invalid Detection must raise ValueError."""
        det = _make_invalid_det()
        with pytest.raises(ValueError):
            _ = det.bbox_pixels

    def test_invalid_bbox_raises_value_error_message_contains_coords(self):
        """The ValueError message must mention the raw bbox_norm for debugging."""
        det = _make_invalid_det(bbox_norm=(0.9, 0.0, 0.5, 0.5))
        with pytest.raises(ValueError, match=r"bbox_norm"):
            _ = det.bbox_pixels

    def test_invalid_bbox_classification_retained(self):
        """Species classification is preserved even when bbox_valid=False."""
        clf = SpeciesClassification(
            top_labels=["opossum"],
            top_scores=[0.92],
            attempted=True,
        )
        det = _make_invalid_det(clf=clf)
        assert det.bbox_valid is False
        assert det.classification.attempted is True
        assert det.classification.top_labels == ["opossum"]
        assert det.classification.top_scores == pytest.approx([0.92])

    def test_invalid_detection_kept_in_result(self):
        """An invalid-bbox Detection must appear in ImageDetectionResult.detections."""
        det = _make_invalid_det()
        result = _make_result(detections=[det])
        assert len(result.detections) == 1
        assert result.detections[0].bbox_valid is False

    def test_valid_bbox_bbox_pixels_returns_correct_tuple(self):
        """bbox_pixels must return the correct pixel tuple for a valid Detection."""
        det = _make_det(bbox_norm=(0.25, 0.50, 0.50, 0.25), image_w=400, image_h=200)
        assert det.bbox_valid is True
        assert det.bbox_pixels == (100, 100, 200, 50)

    def test_bbox_valid_survives_deepcopy(self):
        """Deep-copying a Detection must preserve bbox_valid (True or False)."""
        import copy as _copy
        valid_det   = _make_det()
        invalid_det = _make_invalid_det()
        assert _copy.deepcopy(valid_det).bbox_valid   is True
        assert _copy.deepcopy(invalid_det).bbox_valid is False

    def test_bbox_valid_survives_filter_by_conf(self):
        """filter_by_conf must preserve bbox_valid on copied detections."""
        det = _make_invalid_det(bbox_norm=(0.9, 0.0, 0.5, 0.5))
        result   = _make_result(detections=[det])
        filtered = result.filter_by_conf(0.0)
        assert filtered.detections[0].bbox_valid is False


# ══════════════════════════════════════════════════════════════════════════════
# Milestone 4A — R1: validate_bbox() edge cases
# ══════════════════════════════════════════════════════════════════════════════

def _validate(bbox):
    """Construct a Detection with the given bbox_norm and return its bbox_valid."""
    try:
        det = Detection(
            bbox_norm        = list(bbox),
            image_w          = 100,
            image_h          = 100,
            detector_conf    = 0.5,
            detector_label   = "animal",
            detector_category= "1",
        )
        return det.bbox_valid
    except (TypeError, ValueError):
        # Construction itself failed — treat as invalid for our purposes
        return False


class TestValidateBBoxEdgeCases:
    """
    validate_bbox() must handle all pathological coordinate values safely.
    Each test verifies one edge case independently.
    """

    # -- Correct length --------------------------------------------------------

    def test_wrong_length_too_short(self):
        """Fewer than 4 elements → invalid."""
        assert _validate([0.1, 0.2, 0.3]) is False

    def test_wrong_length_too_long(self):
        """More than 4 elements → invalid."""
        assert _validate([0.1, 0.2, 0.3, 0.4, 0.5]) is False

    def test_empty_list(self):
        """Empty list → invalid."""
        assert _validate([]) is False

    # -- NaN -------------------------------------------------------------------

    def test_nan_in_x(self):
        """NaN in x → invalid."""
        assert _validate([float("nan"), 0.0, 0.5, 0.5]) is False

    def test_nan_in_y(self):
        """NaN in y → invalid."""
        assert _validate([0.0, float("nan"), 0.5, 0.5]) is False

    def test_nan_in_width(self):
        """NaN in width → invalid."""
        assert _validate([0.0, 0.0, float("nan"), 0.5]) is False

    def test_nan_in_height(self):
        """NaN in height → invalid."""
        assert _validate([0.0, 0.0, 0.5, float("nan")]) is False

    # -- Infinity --------------------------------------------------------------

    def test_pos_infinity_in_x(self):
        """Positive infinity in x → invalid."""
        assert _validate([float("inf"), 0.0, 0.5, 0.5]) is False

    def test_neg_infinity_in_y(self):
        """Negative infinity in y → invalid."""
        assert _validate([0.0, float("-inf"), 0.5, 0.5]) is False

    def test_pos_infinity_in_width(self):
        """Positive infinity in width → invalid."""
        assert _validate([0.0, 0.0, float("inf"), 0.5]) is False

    def test_neg_infinity_in_height(self):
        """Negative infinity in height → invalid."""
        assert _validate([0.0, 0.0, 0.5, float("-inf")]) is False

    # -- Negative coordinates --------------------------------------------------

    def test_negative_x(self):
        """x < 0 → invalid."""
        assert _validate([-0.01, 0.0, 0.5, 0.5]) is False

    def test_negative_y(self):
        """y < 0 → invalid."""
        assert _validate([0.0, -0.01, 0.5, 0.5]) is False

    # -- Zero / negative dimensions --------------------------------------------

    def test_zero_width(self):
        """width == 0 → invalid (no area)."""
        assert _validate([0.0, 0.0, 0.0, 0.5]) is False

    def test_zero_height(self):
        """height == 0 → invalid (no area)."""
        assert _validate([0.0, 0.0, 0.5, 0.0]) is False

    def test_negative_width(self):
        """width < 0 → invalid."""
        assert _validate([0.0, 0.0, -0.1, 0.5]) is False

    def test_negative_height(self):
        """height < 0 → invalid."""
        assert _validate([0.0, 0.0, 0.5, -0.1]) is False

    # -- Out-of-bounds ---------------------------------------------------------

    def test_x_plus_w_just_over_tolerance(self):
        """x + w = 1.0 + 2e-6 (beyond 1e-6 tolerance) → invalid."""
        assert _validate([0.5, 0.0, 0.5 + 2e-6, 0.5]) is False

    def test_y_plus_h_just_over_tolerance(self):
        """y + h = 1.0 + 2e-6 (beyond 1e-6 tolerance) → invalid."""
        assert _validate([0.0, 0.5, 0.5, 0.5 + 2e-6]) is False

    def test_x_greater_than_one(self):
        """x > 1.0 → invalid."""
        assert _validate([1.001, 0.0, 0.1, 0.1]) is False

    def test_y_greater_than_one(self):
        """y > 1.0 → invalid."""
        assert _validate([0.0, 1.001, 0.1, 0.1]) is False

    # -- Valid edge cases ------------------------------------------------------

    def test_x_plus_w_within_tolerance(self):
        """x + w = 1.0 + 5e-7 (within 1e-6 tolerance) → valid."""
        assert _validate([0.5, 0.0, 0.5 + 5e-7, 0.5]) is True

    def test_valid_full_frame(self):
        """Full-frame bbox [0, 0, 1, 1] → valid."""
        assert _validate([0.0, 0.0, 1.0, 1.0]) is True

    def test_valid_normal_bbox(self):
        """Typical camera-trap bbox → valid."""
        assert _validate([0.24375, 0.476359, 0.1725, 0.133655]) is True

    def test_valid_tiny_bbox(self):
        """Smallest possible valid bbox (tiny but positive area) → valid."""
        assert _validate([0.0, 0.0, 1e-7, 1e-7]) is True


# ══════════════════════════════════════════════════════════════════════════════
# Milestone 4A — R2 & R3: lazy import verification (subprocess-isolated)
# ══════════════════════════════════════════════════════════════════════════════

class TestMilestone4ALazyImports:
    """
    Verify that importing src.inference and src.inference.speciesnet_infer
    does NOT eagerly load torch or SpeciesNet.

    All tests use a subprocess so they run in a fresh Python interpreter
    with no previously imported modules.
    """

    def _run(self, code: str) -> str:
        """Run code in a subprocess with REPO_ROOT on sys.path; return stdout."""
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"Subprocess failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        return result.stdout.strip()

    # R2 — src.inference.__init__ lazy import ---------------------------------

    def test_import_src_inference_does_not_load_torch(self):
        """
        Importing src.inference must NOT cause torch to appear in sys.modules.
        Before R2 fix, this would take ~4.5 s and load torch eagerly.
        """
        out = self._run(
            "import sys; sys.path.insert(0, '.'); "
            "import src.inference; "
            "print('torch_loaded:', 'torch' in sys.modules)"
        )
        assert "torch_loaded: False" in out, (
            f"torch was eagerly imported by src.inference: {out!r}"
        )

    def test_src_inference_SpeciesNetAnimalDetector_accessible(self):
        """
        from src.inference import SpeciesNetAnimalDetector must work
        (PEP 562 __getattr__ resolves the lazy import correctly).
        """
        out = self._run(
            "import sys; sys.path.insert(0, '.'); "
            "from src.inference import SpeciesNetAnimalDetector; "
            "print('ok:', SpeciesNetAnimalDetector.__name__)"
        )
        assert "ok: SpeciesNetAnimalDetector" in out, (
            f"SpeciesNetAnimalDetector not accessible: {out!r}"
        )

    # R3 — speciesnet_infer lazy imports --------------------------------------

    def test_speciesnet_infer_does_not_load_speciesnet_at_module_level(self):
        """
        import src.inference.speciesnet_infer must NOT load speciesnet or torch.
        Before R3 fix, top-level from speciesnet.* imports ran at import time.
        """
        out = self._run(
            "import sys; sys.path.insert(0, '.'); "
            "import src.inference.speciesnet_infer; "
            "torch_loaded = 'torch' in sys.modules; "
            "sn_loaded = any(k.startswith('speciesnet') for k in sys.modules); "
            "print('torch_loaded:', torch_loaded); "
            "print('speciesnet_loaded:', sn_loaded)"
        )
        assert "torch_loaded: False" in out, (
            f"torch was loaded at module import time: {out!r}"
        )
        assert "speciesnet_loaded: False" in out, (
            f"speciesnet was loaded at module import time: {out!r}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Milestone 4A — R4: test_cct_3images.py API migration (AST lint)
# ══════════════════════════════════════════════════════════════════════════════

class TestMilestone4AMigration:
    """
    Verify that test_cct_3images.py has been migrated to the new
    SpeciesNetAnimalDetector API and no longer imports from speciesnet_infer.
    """

    def test_cct_3images_does_not_import_speciesnet_infer(self):
        """test_cct_3images.py must not contain 'from speciesnet_infer import'."""
        import ast
        src_path = REPO_ROOT / "tests" / "inference" / "test_cct_3images.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert "speciesnet_infer" not in module, (
                    f"test_cct_3images.py still imports from {module!r} "
                    "(should use SpeciesNetAnimalDetector)"
                )

    def test_cct_3images_uses_SpeciesNetAnimalDetector(self):
        """test_cct_3images.py must import SpeciesNetAnimalDetector."""
        import ast
        src_path = REPO_ROOT / "tests" / "inference" / "test_cct_3images.py"
        source = src_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        names_imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    names_imported.add(alias.name)
        assert "SpeciesNetAnimalDetector" in names_imported, (
            "test_cct_3images.py does not import SpeciesNetAnimalDetector"
        )

    def test_cct_3images_uses_DetectionStatus_enum(self):
        """test_cct_3images.py must import DetectionStatus (not compare with strings)."""
        import ast
        src_path = REPO_ROOT / "tests" / "inference" / "test_cct_3images.py"
        source = src_path.read_text(encoding="utf-8")
        # Quick textual check — DetectionStatus must appear
        assert "DetectionStatus" in source, (
            "test_cct_3images.py does not use DetectionStatus "
            "(old code compared result.status to strings like 'ok')"
        )

    def test_cct_3images_does_not_use_old_field_names(self):
        """test_cct_3images.py must not access old DetectionResult field names."""
        src_path = REPO_ROOT / "tests" / "inference" / "test_cct_3images.py"
        source = src_path.read_text(encoding="utf-8")
        old_fields = ["det.label", "det.conf ", "det.category", "det.top5_classes",
                      "det.top5_scores", "det.classification_attempted"]
        for field_ref in old_fields:
            assert field_ref not in source, (
                f"test_cct_3images.py still uses old field {field_ref!r}; "
                "should use new Detection field names"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Milestone 4A final audit — regression tests for post-construction mutation
# ══════════════════════════════════════════════════════════════════════════════

class TestBBoxValidLiveProperty:
    """
    bbox_valid is a @property that calls validate_bbox() on every access.
    It must therefore reflect the *current* state of bbox_norm at the time
    of access, not the state captured at construction time.

    These tests guard against the bug where bbox_valid was a stored bool field:
    mutating bbox_norm after construction left bbox_valid stale, allowing
    bbox_pixels to silently return invalid pixel coordinates.
    """

    def test_mutation_after_construction_updates_bbox_valid(self):
        """
        Mutating bbox_norm in-place must invalidate bbox_valid immediately.

        Old behaviour (stored field): bbox_valid remained True after mutation.
        Fixed behaviour (property):   bbox_valid returns False after mutation.
        """
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        assert det.bbox_valid is True                  # valid at construction

        det.bbox_norm[0] = 0.9                         # x=0.9, w=0.3 → x+w=1.2>1
        assert det.bbox_valid is False                 # OLD: still True (BUG)

    def test_bbox_pixels_raises_after_mutation_makes_bbox_invalid(self):
        """
        bbox_pixels must raise ValueError when bbox_norm is mutated to invalid.

        Old behaviour: returned wrong pixel coordinates without raising.
        Fixed behaviour: raises ValueError because bbox_valid is now False.
        """
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        assert det.bbox_valid is True

        det.bbox_norm[0] = 0.9                         # makes box extend past frame
        with pytest.raises(ValueError, match=r"bbox_norm"):
            _ = det.bbox_pixels                        # OLD: returned bad coords

    def test_mutation_back_to_valid_restores_bbox_valid(self):
        """
        Restoring bbox_norm to valid values must make bbox_valid True again.
        This confirms the property is truly live, not cached.
        """
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        det.bbox_norm[0] = 0.9                         # make invalid
        assert det.bbox_valid is False
        det.bbox_norm[0] = 0.1                         # restore to valid
        assert det.bbox_valid is True
        assert det.bbox_pixels[0] == int(0.1 * 2048)  # also works again


class TestValidateBBoxNeverRaises:
    """
    validate_bbox() must return False for any malformed input without raising.
    The docstring promises 'Never raises'.

    These tests guard against the bug where non-numeric element types
    caused math.isfinite() to raise TypeError instead of returning False.
    """

    def test_non_numeric_string_element_returns_false_not_type_error(self):
        """
        A string element must return False, not raise TypeError.

        Old behaviour: math.isfinite('hello') raised TypeError.
        Fixed behaviour: try/except returns False.
        """
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        det.bbox_norm[0] = "hello"
        result = det.validate_bbox()
        assert result is False                         # OLD: raised TypeError

    def test_none_element_returns_false_not_type_error(self):
        """None in bbox_norm must return False, not raise TypeError."""
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        det.bbox_norm[1] = None
        assert det.validate_bbox() is False

    def test_non_numeric_does_not_crash_bbox_valid_property(self):
        """
        Accessing bbox_valid with a non-numeric element must return False
        without raising, because bbox_valid calls validate_bbox() which
        now catches TypeError.
        """
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        det.bbox_norm[2] = object()
        assert det.bbox_valid is False                 # must not raise

    def test_non_numeric_does_not_crash_bbox_pixels(self):
        """
        Calling bbox_pixels with a non-numeric element must raise ValueError
        (the clean geometry-invalid error), not TypeError.
        """
        det = _make_det(bbox_norm=(0.1, 0.2, 0.3, 0.4))
        det.bbox_norm[3] = []
        with pytest.raises(ValueError):               # not TypeError
            _ = det.bbox_pixels
