import unittest

from src.replay import build_result, load_cases, replay_case, run_replay


class ReplayTests(unittest.TestCase):
    def test_all_cases_replay_with_expected_decisions(self):
        report = run_replay()
        self.assertGreaterEqual(report["total"], 14)
        self.assertEqual(report["passed"], report["total"])
        self.assertEqual(report["failed"], 0)
        self.assertTrue(all(result["synthetic_fixture"] for result in report["results"]))
        self.assertTrue(all(not result["production_usable"] for result in report["results"]))

    def test_missing_field_fixture_is_removed_before_routing(self):
        case = next(c for c in load_cases() if c["case_id"] == "missing_severity_probabilities")
        result = build_result(case)
        self.assertNotIn("severity_probabilities", result["defects"][0])
        self.assertEqual(replay_case(case)["actual"]["state"], "INVALID_RESULT")

    def test_high_probability_without_defects_is_evidence_conflict(self):
        case = next(c for c in load_cases() if c["case_id"] == "high_probability_without_defects")
        actual = replay_case(case)["actual"]
        self.assertEqual(actual["path"], "FAILED")
        self.assertEqual(actual["reason_codes"], ["EVIDENCE_CONFLICT"])


if __name__ == "__main__":
    unittest.main()
