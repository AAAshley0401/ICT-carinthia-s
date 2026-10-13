import unittest

from main import run_inspection


class WorkflowTests(unittest.TestCase):
    def test_normal_suggestion_preview(self):
        output = run_inspection("001", "unused.png", "normal")
        self.assertEqual(output["path"], "NORMAL")
        self.assertEqual(output["reason_codes"], ["HIGH_CONFIDENCE"])
        self.assertEqual(output["agent_called"], ["DetectorAgent", "RouterAgent"])
        self.assertFalse(output["human_review_required"])
        self.assertTrue(output["human_confirmation_required"])
        self.assertEqual(output["validated_decision"]["current_state"], "INVALID_RESULT")
        self.assertEqual(output["validated_decision"]["reason_codes"], ["DEMO_RESULT"])
        self.assertFalse(output["production_usable"])

    def test_boundary_review_preview(self):
        output = run_inspection("002", "unused.png", "boundary")
        self.assertEqual(output["path"], "REVIEW")
        self.assertIn("LOW_CONFIDENCE", output["reason_codes"])
        self.assertIn("SEVERITY_BOUNDARY", output["reason_codes"])
        self.assertTrue(output["human_review_required"])
        self.assertEqual(output["validated_decision"]["current_state"], "INVALID_RESULT")

    def test_tool_failure(self):
        output = run_inspection("003", "unused.png", "failure")
        self.assertEqual(output["path"], "FAILED")
        self.assertEqual(output["reason_codes"], ["MODEL_TIMEOUT"])
        self.assertEqual(output["validated_decision"]["current_state"], "DETECT_FAILED")
        self.assertEqual(output["validated_decision"]["reason_codes"], ["MODEL_TIMEOUT"])
        self.assertFalse(output["human_review_required"])


if __name__ == "__main__":
    unittest.main()
