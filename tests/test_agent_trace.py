import json
import unittest

from main import run_inspection
from src.agent_trace import TraceCollector, format_trace


class AgentTraceTests(unittest.TestCase):
    def test_normal_path_records_detector_and_router(self):
        output = run_inspection("001", "samples/001.png", "normal")
        steps = output["execution_trace"]
        self.assertEqual([step["agent"] for step in steps], [
            "DetectorAgent", "ValidationAgent", "RoutingEngine",
        ])
        self.assertEqual(steps[0]["input"]["image_path"], "samples/001.png")
        self.assertEqual(steps[0]["output_summary"]["defect_probability"], 0.05)
        self.assertEqual(steps[2]["decision"]["path"], "NORMAL")
        self.assertFalse(output["final_decision"]["human_review_required"])
        self.assertEqual(output["final_decision"]["validated_path"], "FAILED")
        json.dumps(output["execution_trace"], allow_nan=False)

    def test_review_records_severity_evidence_and_reasons(self):
        output = run_inspection("W-0304", "samples/W-0304.png", "boundary")
        detector = output["execution_trace"][0]
        router = output["execution_trace"][2]
        self.assertEqual(detector["output_summary"]["defects"][0]["severity_confidence"], 0.52)
        self.assertEqual(
            detector["output_summary"]["defects"][0]["severity_probabilities"]["NG"], 0.43
        )
        self.assertIn("SEVERITY_BOUNDARY", router["decision"]["reason_codes"])
        self.assertTrue(output["final_decision"]["human_review_required"])
        self.assertTrue(output["final_decision"]["human_confirmation_required"])
        self.assertIn("Human review: REQUIRED", format_trace(output))
        self.assertIn("Severity confidence: 0.52", format_trace(output))
        self.assertIn("severity gap: 0.09", format_trace(output))

    def test_failure_records_tool_error_and_failure_reason(self):
        output = run_inspection("003", "samples/003.png", "failure")
        steps = output["execution_trace"]
        self.assertEqual(steps[0]["output_summary"]["error"], "timeout")
        self.assertEqual(steps[1]["output_summary"]["reason_code"], "TOOL_ERROR")
        self.assertEqual(steps[2]["decision"]["reason_codes"], ["TOOL_ERROR"])
        self.assertEqual(output["final_decision"]["path"], "FAILED")
        self.assertEqual(output["final_decision"]["validated_path"], "FAILED")

    def test_collector_snapshots_mutable_input(self):
        trace = TraceCollector("001")
        data = {"value": [1]}
        trace.add_step("DetectorAgent", input_data=data)
        data["value"].append(2)
        self.assertEqual(trace.to_dict({"path": "NORMAL"})["execution_trace"][0]["input"], {"value": [1]})


if __name__ == "__main__":
    unittest.main()
