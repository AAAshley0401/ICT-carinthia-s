import copy
import unittest

from src.detection_validation import validate_detection_result
from src.routing_engine import RoutingPolicy, route_detection
from src.task_state import InspectionTask, TaskState


def model_result(**changes):
    result = {
        "schema_version": "1.0",
        "sample_id": "W-001",
        "status": "success",
        "mode": "model",
        "demo_only": False,
        "image_analyzed": True,
        "model_version": "synthetic-test-v1",
        "calibration_version": "synthetic-calibration-v1",
        "defect_probability": 0.95,
        "defects": [{
            "defect_id": "d1",
            "defect_type": "particle",
            "detection_confidence": 0.96,
            "class_confidence": 0.93,
            "severity": "NG",
            "severity_confidence": 0.94,
            "severity_probabilities": {
                "Acceptable": 0.01, "Marginal NG": 0.03, "NG": 0.94, "Gross NG": 0.02,
            },
            "bbox_xyxy": [10, 20, 30, 40],
            "mask_ref": "authorized://masks/W-001/d1",
        }],
        "error": None,
    }
    result.update(changes)
    return result


class RoutingEngineTests(unittest.TestCase):
    def test_normal_candidate(self):
        task = InspectionTask("W-001")
        decision = route_detection(task, model_result(defect_probability=0.05, defects=[]))
        self.assertEqual(decision.selected_path.value, "NORMAL")
        self.assertEqual(decision.reason_codes, ("LOW_DEFECT_PROBABILITY",))
        self.assertEqual(decision.current_state, TaskState.SUGGESTION_READY)
        self.assertEqual(decision.evidence["defect_probability"], 0.05)
        self.assertIsNone(decision.evidence["detection_confidence"])

    def test_boundary_review(self):
        result = model_result()
        result["defects"][0]["severity"] = "Marginal NG"
        result["defects"][0]["severity_confidence"] = 0.52
        result["defects"][0]["severity_probabilities"] = {
            "Acceptable": 0.05, "Marginal NG": 0.52, "NG": 0.43, "Gross NG": 0.0,
        }
        decision = route_detection(InspectionTask("W-001"), result)
        self.assertEqual(decision.selected_path.value, "REVIEW")
        self.assertIn("SEVERITY_BOUNDARY", decision.reason_codes)
        self.assertTrue(decision.human_review_required)

    def test_low_detection_confidence_review(self):
        result = model_result()
        result["defects"][0]["detection_confidence"] = 0.65
        decision = route_detection(InspectionTask("W-001"), result)
        self.assertEqual(decision.selected_path.value, "REVIEW")
        self.assertEqual(decision.reason_codes, ("LOW_DETECTION_CONFIDENCE",))

    def test_tool_failure(self):
        task = InspectionTask("W-001")
        decision = route_detection(task, {"status": "failed", "error": "timeout"})
        self.assertEqual(decision.selected_path.value, "FAILED")
        self.assertEqual(decision.reason_codes, ("TOOL_ERROR",))
        self.assertEqual(decision.current_state, TaskState.INVALID_RESULT)

    def test_reliable_defect_evidence_generates_suggestion(self):
        decision = route_detection(InspectionTask("W-001"), model_result())
        self.assertEqual(decision.selected_path.value, "SUGGESTION")
        self.assertEqual(decision.reason_codes, ("RELIABLE_DEFECT_EVIDENCE",))
        self.assertIn("NG", decision.recommended_action)
        self.assertIn("localized defect", decision.evidence_summary)
        self.assertEqual(decision.to_dict()["agent_called"], ["DetectorAgent", "RouterAgent"])

    def test_class_and_severity_uncertainty_review(self):
        result = model_result()
        result["defects"][0]["class_confidence"] = 0.72
        result["defects"][0]["severity_confidence"] = 0.7
        decision = route_detection(InspectionTask("W-001"), result)
        self.assertEqual(decision.reason_codes, ("UNCERTAIN_DEFECT_TYPE", "UNCERTAIN_SEVERITY"))

    def test_severity_label_conflict_requires_review(self):
        result = model_result()
        result["defects"][0]["severity"] = "Gross NG"
        decision = route_detection(InspectionTask("W-001"), result)
        self.assertEqual(decision.reason_codes, ("SEVERITY_LABEL_CONFLICT",))

    def test_demo_result_is_rejected(self):
        result = model_result(demo_only=True, mode="mock", image_analyzed=False)
        decision = route_detection(InspectionTask("W-001"), result)
        self.assertEqual(decision.reason_codes, ("DEMO_RESULT",))
        self.assertEqual(decision.current_state, TaskState.INVALID_RESULT)

    def test_missing_field_is_invalid_schema(self):
        result = model_result()
        del result["calibration_version"]
        decision = route_detection(InspectionTask("W-001"), result)
        self.assertEqual(decision.reason_codes, ("INVALID_SCHEMA",))

    def test_bad_probability_distribution_is_invalid_schema(self):
        result = model_result()
        result["defects"][0]["severity_probabilities"]["NG"] = 0.5
        self.assertFalse(validate_detection_result(result, "W-001").valid)

    def test_any_unreliable_defect_requires_review(self):
        result = model_result()
        second = copy.deepcopy(result["defects"][0])
        second.update(defect_id="d2", detection_confidence=0.65)
        result["defects"].append(second)
        decision = route_detection(InspectionTask("W-001"), result)
        self.assertEqual(decision.reason_codes, ("LOW_DETECTION_CONFIDENCE",))

    def test_possible_defect_without_localization_requires_review(self):
        decision = route_detection(InspectionTask("W-001"), model_result(defects=[]))
        self.assertEqual(decision.reason_codes, ("MISSING_DEFECT_EVIDENCE",))

    def test_state_transition_is_guarded(self):
        with self.assertRaises(ValueError):
            InspectionTask("W-001").transition_to(TaskState.SUGGESTION_READY)

    def test_policy_rejects_invalid_threshold(self):
        with self.assertRaises(ValueError):
            RoutingPolicy(detection_threshold=1.2)


if __name__ == "__main__":
    unittest.main()
