import unittest

from main import run_inspection
from src.model_adapter import ModelAdapter, ModelDefect, ModelPrediction


class StubBackend:
    def __init__(self, *, missing_probabilities=False):
        self.missing_probabilities = missing_probabilities

    def predict(self, sample_id, image_path):
        defect = ModelDefect(
            defect_id="d1",
            label="scratch",
            detection_score=0.96,
            classification_score=0.93,
            severity_label="NG",
            severity_score=0.94,
            severity_distribution=None if self.missing_probabilities else {
                "Acceptable": 0.01,
                "Marginal NG": 0.03,
                "NG": 0.94,
                "Gross NG": 0.02,
            },
            box_xyxy=(10, 20, 30, 40),
            mask_reference="authorized://mask/d1",
        )
        return ModelPrediction(
            sample_id=sample_id,
            model_version="stub-model-v1",
            calibration_version="stub-calibration-v1",
            defect_probability=0.95,
            detections=(defect,),
            image_analyzed=True,
            demo_only=False,
            inference_timestamp="2026-10-13T00:00:00Z",
        )


class ModelAdapterTests(unittest.TestCase):
    def test_existing_mock_pipeline_still_runs(self):
        output = run_inspection("M-001", "unused.png", "normal")
        self.assertEqual(output["path"], "NORMAL")
        self.assertEqual(output["validated_decision"]["reason_codes"], ["DEMO_RESULT"])

    def test_non_demo_adapter_reaches_validated_suggestion(self):
        output = run_inspection("M-002", "unused.png", detector=ModelAdapter(StubBackend()))
        self.assertEqual(output["path"], "SUGGESTION")
        self.assertEqual(output["validation_status"], "VALID")
        self.assertEqual(output["validated_decision"]["current_state"], "SUGGESTION_READY")
        self.assertEqual(output["decision_scope"], "VALIDATED_MODEL_OUTPUT")
        self.assertEqual(output["agent_called"][0], "ModelAdapter")

    def test_missing_probability_distribution_becomes_invalid_result(self):
        output = run_inspection(
            "M-003", "unused.png", detector=ModelAdapter(StubBackend(missing_probabilities=True))
        )
        self.assertEqual(output["path"], "FAILED")
        self.assertEqual(output["validated_decision"]["current_state"], "INVALID_RESULT")
        self.assertEqual(output["validated_decision"]["reason_codes"], ["TOOL_ERROR"])
        self.assertEqual(output["decision_scope"], "REJECTED_MODEL_OUTPUT")


if __name__ == "__main__":
    unittest.main()
