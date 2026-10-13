import unittest

from src.routing_engine import RoutingPolicy, route_detection
from src.task_state import InspectionTask, TaskState


def model_result(**changes):
    result = {
        "sample_id": "W-001",
        "mode": "model",
        "demo_only": False,
        "image_analyzed": True,
        "model_version": "prototype-model-v1",
        "grade": "NG",
        "confidence": 0.96,
        "defects": [],
    }
    result.update(changes)
    return result


class RoutingEngineTests(unittest.TestCase):
    def test_normal_suggestion(self):
        task = InspectionTask("W-001")
        decision = route_detection(task, model_result())

        self.assertEqual(decision.to_dict()["selected_path"], "NORMAL")
        self.assertEqual(decision.current_state, TaskState.SUGGESTION_READY)
        self.assertEqual(decision.action, "Generate normal quality suggestion")
        self.assertFalse(decision.human_review_required)
        self.assertEqual(
            task.history,
            [TaskState.CREATED, TaskState.DETECTING, TaskState.DETECT_SUCCESS,
             TaskState.SORTING, TaskState.SUGGESTION_READY],
        )
        self.assertEqual(decision.to_dict()["task_id"], "W-001")

    def test_boundary_review(self):
        task = InspectionTask("W-001")
        decision = route_detection(
            task, model_result(grade="Marginal NG", confidence=0.94)
        )

        self.assertEqual(decision.to_dict()["selected_path"], "REVIEW")
        self.assertEqual(decision.current_state, TaskState.REVIEW_REQUIRED)
        self.assertIn("SEVERITY_BOUNDARY", decision.reason_codes)
        self.assertTrue(decision.human_review_required)
        self.assertEqual(decision.action, "Human review required")

    def test_tool_failure(self):
        task = InspectionTask("W-001")
        decision = route_detection(task, tool_error={"code": "TOOL_ERROR"})

        self.assertEqual(decision.to_dict()["selected_path"], "FAILED")
        self.assertEqual(decision.current_state, TaskState.DETECT_FAILED)
        self.assertEqual(decision.reason_codes, ("TOOL_ERROR",))
        self.assertEqual(decision.action, "Cannot generate reliable suggestion")

    def test_demo_result_is_invalid_even_when_fields_are_missing(self):
        task = InspectionTask("W-001")
        decision = route_detection(task, {"demo_only": True, "grade": "NG"})

        self.assertEqual(decision.current_state, TaskState.INVALID_RESULT)
        self.assertEqual(decision.reason_codes, ("DEMO_RESULT",))
        self.assertIn("cannot be used for real production decisions", decision.explanation)

    def test_missing_fields_fail(self):
        decision = route_detection(InspectionTask("W-001"), {"demo_only": False})
        self.assertEqual(decision.reason_codes, ("MISSING_REQUIRED_FIELDS",))

    def test_model_timeout_fails(self):
        decision = route_detection(InspectionTask("W-001"), tool_error=TimeoutError())
        self.assertEqual(decision.reason_codes, ("MODEL_TIMEOUT",))

    def test_invalid_response_format_fails(self):
        decision = route_detection(InspectionTask("W-001"), model_result(confidence="high"))
        self.assertEqual(decision.reason_codes, ("INVALID_RESPONSE_FORMAT",))

    def test_low_confidence_and_conflict_review(self):
        decision = route_detection(InspectionTask("W-001"), model_result(confidence=0.7, conflict=True))
        self.assertEqual(decision.to_dict()["selected_path"], "REVIEW")
        self.assertEqual(decision.reason_codes, ("LOW_CONFIDENCE", "RULE_CONFLICT"))

    def test_acceptable_without_screening_score_requires_review(self):
        decision = route_detection(InspectionTask("W-001"), model_result(grade="Acceptable"))
        self.assertEqual(decision.reason_codes, ("SCREENING_SCORE_MISSING",))

    def test_state_transition_is_guarded(self):
        task = InspectionTask("W-001")
        with self.assertRaises(ValueError):
            task.transition_to(TaskState.SUGGESTION_READY)

    def test_policy_rejects_invalid_thresholds(self):
        with self.assertRaises(ValueError):
            RoutingPolicy(confidence_threshold=1.2)


if __name__ == "__main__":
    unittest.main()
