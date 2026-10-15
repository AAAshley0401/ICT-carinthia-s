/* Static AgentCaseResult snapshots. All records are synthetic or mock; no image is analyzed. */
(function () {
  const replaySource = {
    source_kind: "SYNTHETIC_REPLAY",
    demo_only: true,
    image_analyzed: false,
    decision_scope: "SYNTHETIC_REPLAY",
    production_usable: false
  };
  const noImage = { ref: null, width: null, height: null, evidence_bound: false };
  const replayDefect = {
    defect_id: "d1",
    defect_type: "scratch",
    detection_confidence: 0.96,
    class_confidence: 0.93,
    severity: "NG",
    severity_confidence: 0.94,
    severity_probabilities: { "Acceptable": 0.01, "Marginal NG": 0.03, "NG": 0.94, "Gross NG": 0.02 },
    bbox_xyxy: [10, 20, 30, 40],
    mask_ref: "fixture://mask/d1"
  };
  const base = (sampleId, probability, defects, path, reasons, review) => ({
    contract_version: "1.0",
    sample_id: sampleId,
    provenance: { ...replaySource },
    image: { ...noImage },
    detection: {
      status: "success",
      model_version: "synthetic-replay-fixture-v1",
      calibration_version: "synthetic-calibration-v1",
      defect_probability: probability,
      defects,
      error_code: null
    },
    validation: { status: "VALID", reason_code: null },
    routing: { path, reason_codes: reasons, human_review_required: review, recommended_action: null, preview: null },
    trace: []
  });

  const normal = base("R-N001", 0.05, [], "NORMAL", ["LOW_DEFECT_PROBABILITY"], false);
  const boundaryDefect = {
    ...replayDefect,
    severity: "Marginal NG",
    severity_confidence: 0.82,
    severity_probabilities: { "Acceptable": 0.05, "Marginal NG": 0.52, "NG": 0.43, "Gross NG": 0.0 }
  };
  const review = base("R-B001", 0.95, [boundaryDefect], "REVIEW", ["SEVERITY_BOUNDARY"], true);
  const failed = base("R-C001", 0.9, [], "FAILED", ["EVIDENCE_CONFLICT"], true);

  const mockTrace = {
    contract_version: "1.0",
    sample_id: "demo-boundary",
    provenance: {
      source_kind: "LOCAL_WORKFLOW",
      demo_only: true,
      image_analyzed: false,
      decision_scope: "SIMULATION_PREVIEW",
      production_usable: false
    },
    image: { ...noImage },
    detection: {
      status: "success",
      model_version: "mock-detector-v2",
      calibration_version: "mock-unvalidated",
      defect_probability: 0.95,
      defects: [{
        ...boundaryDefect,
        class_confidence: 0.91,
        severity_confidence: 0.52,
        bbox_xyxy: [320, 390, 500, 470],
        mask_ref: "mock://masks/demo-boundary/d1"
      }],
      error_code: null
    },
    validation: { status: "INVALID_RESULT", reason_code: "DEMO_RESULT" },
    routing: {
      path: "FAILED",
      reason_codes: ["DEMO_RESULT"],
      human_review_required: true,
      recommended_action: null,
      preview: {
        path: "REVIEW",
        reason_codes: ["UNCERTAIN_SEVERITY", "SEVERITY_BOUNDARY"],
        human_review_required: true,
        explanation: "模拟规则预览：严重度分数较低，Marginal NG 与 NG 概率接近。"
      }
    },
    trace: [
      { stage: "DETECTION", label: "DetectorAgent", input_summary: { sample_id: "demo-boundary", scenario: "boundary" }, output_summary: { status: "success", defect_probability: 0.95, demo_only: true }, reason_codes: [] },
      { stage: "VALIDATION", label: "ValidationAgent", input_summary: { demo_only: true }, output_summary: { status: "INVALID_RESULT" }, reason_codes: ["DEMO_RESULT"] },
      { stage: "ROUTING", label: "RoutingEngine", input_summary: { validation_status: "INVALID_RESULT", severity_confidence: 0.52, severity_gap: 0.09 }, output_summary: { validated_path: "FAILED", preview_path: "REVIEW" }, reason_codes: ["DEMO_RESULT"] }
    ]
  };

  window.AGENT_DEMO_CASES = [
    { key: "normal", label: "NORMAL · 正常候选", data: normal },
    { key: "review", label: "REVIEW · 边界复核", data: review },
    { key: "failed", label: "FAILED · 证据冲突", data: failed },
    { key: "trace", label: "本地 Trace · 模拟预览", data: mockTrace }
  ];
})();
