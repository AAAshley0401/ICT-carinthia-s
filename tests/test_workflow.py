import unittest

from main import run_inspection
from src.detector_agent import DetectorAgent


class WorkflowTests(unittest.TestCase):
    def test_normal_preview(self):
        output = run_inspection("001", "unused.png", "normal")
        self.assertEqual(output["path"], "NORMAL")
        self.assertEqual(output["reason_codes"], ["LOW_DEFECT_PROBABILITY"])
        self.assertEqual(output["evidence"]["defect_probability"], 0.05)
        self.assertEqual(output["agent_called"], ["DetectorAgent", "ValidationAgent", "RoutingEngine"])
        self.assertEqual(output["validated_decision"]["current_state"], "INVALID_RESULT")
        self.assertEqual(output["validated_decision"]["reason_codes"], ["DEMO_RESULT"])
        self.assertFalse(output["production_usable"])

    def test_boundary_preview(self):
        output = run_inspection("002", "unused.png", "boundary")
        self.assertEqual(output["path"], "REVIEW")
        self.assertIn("SEVERITY_BOUNDARY", output["reason_codes"])
        self.assertTrue(output["human_review_required"])
        self.assertEqual(output["evidence"]["defect_probability"], 0.95)

    def test_tool_failure(self):
        output = run_inspection("003", "unused.png", "failure")
        self.assertEqual(output["path"], "FAILED")
        self.assertEqual(output["reason_codes"], ["TOOL_ERROR"])
        self.assertEqual(output["validated_decision"]["current_state"], "INVALID_RESULT")
        self.assertEqual(output["validated_decision"]["reason_codes"], ["TOOL_ERROR"])

    def test_mock_uses_new_contract_and_never_claims_analysis(self):
        result = DetectorAgent("boundary").detect("W-0304", "unused.png")
        self.assertEqual(result["schema_version"], "1.0")
        self.assertTrue(result["demo_only"])
        self.assertFalse(result["image_analyzed"])
        self.assertIn("severity_probabilities", result["defects"][0])
        self.assertNotIn("confidence", result)


if __name__ == "__main__":
    unittest.main()
