(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const tabs = $("scenario-tabs");
  const examples = window.AGENT_DEMO_CASES || [];
  let currentCase = null;
  let activeKey = null;
  let localImageUrl = null;

  function clearLocalImage() {
    if (localImageUrl) URL.revokeObjectURL(localImageUrl);
    localImageUrl = null;
  }

  const pathNames = { NORMAL: "正常候选", SUGGESTION: "处置建议", REVIEW: "人工复核", FAILED: "已阻塞" };
  const reasonNames = {
    DEMO_RESULT: "模拟结果不可用于正式决策",
    EVIDENCE_CONFLICT: "异常概率与定位证据冲突",
    SEVERITY_NOT_AVAILABLE: "缺少四档严重度输出",
    UNCALIBRATED_SCORE: "原始距离未校准为概率",
    LOW_DEFECT_PROBABILITY: "异常概率低于原型阈值",
    SEVERITY_BOUNDARY: "相邻严重度档位接近",
    UNCERTAIN_SEVERITY: "严重度分数不足",
    TOOL_ERROR: "检测工具失败",
    INVALID_SCHEMA: "结果结构无效"
  };

  function node(tag, className, value) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = value;
    return element;
  }

  function setText(id, value) { $(id).textContent = value == null ? "—" : String(value); }
  function score(value) { return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 100)}%` : "未提供"; }
  function showError(message) { const target = $("error-banner"); target.textContent = message; target.hidden = !message; }
  function fillReasons(target, reasons) {
    target.replaceChildren();
    if (!reasons.length) { target.append(node("span", "reason-code", "无")); return; }
    reasons.forEach((code) => {
      const label = node("span", `reason-code ${code === "DEMO_RESULT" || code === "EVIDENCE_CONFLICT" ? "critical" : ""}`, code);
      label.title = reasonNames[code] || code;
      target.append(label);
    });
  }

  function safeMediaUrl(ref) {
    if (typeof ref !== "string" || !ref.trim()) return null;
    try {
      const url = new URL(ref, document.baseURI);
      return ["https:", "http:", "file:"].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }

  function renderImage(result) {
    const viewer = $("image-viewer");
    viewer.replaceChildren();
    const image = result.image;
    const ref = localImageUrl || safeMediaUrl(image.ref);
    const bound = Boolean(image.evidence_bound && !localImageUrl && image.width && image.height);
    if (!ref) {
      const placeholder = node("div", "image-placeholder");
      const wafer = node("div", "wafer-map");
      wafer.append(node("div", "wafer-ring"), node("div", "wafer-core"));
      if (result.detection.defects.length) wafer.append(node("div", "wafer-marker"));
      else wafer.append(node("div", "wafer-empty", "NO LOCALIZED REGION"));
      placeholder.append(wafer, node("span", "view-caption", "SYNTHETIC EVIDENCE MAP · 非原图"));
      viewer.append(placeholder);
      setText("image-note", "当前为合成证据示意，标记位置不代表原图坐标；导入与证据绑定的图片后才会叠加真实对应的框。 ");
      return;
    }

    const stack = node("div", "image-stack");
    const imageNode = node("img", "base-image");
    imageNode.alt = localImageUrl ? "用户本地预览图，未参与检测" : "样本图像";
    imageNode.src = ref;
    imageNode.onerror = () => {
      if (!stack.isConnected) return;
      viewer.replaceChildren(node("div", "image-placeholder", "图像无法加载；检测证据仍可在下方查看。"));
    };
    stack.append(imageNode);
    if (bound) {
      const maskRefs = result.detection.defects.map((defect) => safeMediaUrl(defect.mask_ref)).filter(Boolean);
      maskRefs.forEach((maskRef) => {
        const mask = node("img", "mask-overlay");
        mask.alt = "缺陷掩码叠加";
        mask.src = maskRef;
        mask.onerror = () => mask.remove();
        stack.append(mask);
      });
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", `0 0 ${image.width} ${image.height}`);
      svg.setAttribute("aria-label", "缺陷框叠加");
      result.detection.defects.forEach((defect) => {
        const box = defect.bbox_xyxy;
        if (!Array.isArray(box) || box.length !== 4 || box.some((item) => typeof item !== "number")) return;
        const [x1, y1, x2, y2] = box;
        if (x1 < 0 || y1 < 0 || x2 <= x1 || y2 <= y1 || x2 > image.width || y2 > image.height) return;
        const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        rect.setAttribute("x", String(x1)); rect.setAttribute("y", String(y1));
        rect.setAttribute("width", String(x2 - x1)); rect.setAttribute("height", String(y2 - y1));
        svg.append(rect);
      });
      stack.append(svg);
    }
    viewer.append(stack);
    setText("image-note", localImageUrl ? "本地图片仅供预览，未发送到服务端，也未与检测证据绑定；不叠加缺陷框。" : bound ? "图像与证据已声明绑定；叠加的框和可用掩码来自输入 JSON。" : "图像与检测证据未绑定；不叠加缺陷框或掩码。");
  }

  function renderEvidence(result) {
    const detection = result.detection;
    setText("metric-label", "异常存在概率");
    setText("metric-kind", "IMAGE LEVEL EVIDENCE");
    setText("evidence-count", `${detection.defects.length} 条缺陷记录`);
    renderImage(result);
    setText("defect-probability", score(detection.defect_probability));
    setText("evidence-summary", detection.defects.length ? `记录 ${detection.defects.length} 处合成缺陷区域。位置、类别与严重度是不同层级的证据，需要逐项检查。` : detection.defect_probability != null && detection.defect_probability >= 0.2 ? "异常概率较高，但缺陷区域列表为空。该组合需要进入证据一致性检查。" : "缺陷区域列表为空。此处仅展示合成输入，不能据此认定真实图片无缺陷。");
    const scoreGrid = $("score-grid");
    scoreGrid.replaceChildren();
    [["区域定位", detection.defects.length ? score(Math.min(...detection.defects.map((item) => item.detection_confidence))) : "未提供", "单缺陷最低分"], ["缺陷类别", detection.defects.length ? score(Math.min(...detection.defects.map((item) => item.class_confidence))) : "未提供", "单缺陷最低分"], ["严重度", detection.defects.length ? score(Math.min(...detection.defects.map((item) => item.severity_confidence))) : "未提供", "单缺陷最低分"]].forEach(([label, value, note]) => {
      const card = node("div", "score-card"); card.append(node("span", "", label), node("strong", "", value), node("small", "", note)); scoreGrid.append(card);
    });

    const list = $("defect-list"); list.replaceChildren();
    if (!detection.defects.length) { list.append(node("div", "empty-state", "缺陷列表为空。请结合异常概率和决策原因查看其含义。")); return; }
    detection.defects.forEach((defect) => {
      const card = node("article", "defect-card");
      const top = node("div", "defect-top");
      top.append(node("strong", "", `${defect.defect_id}  /  ${defect.defect_type}`), node("span", "severity-tag", defect.severity));
      const grid = node("div", "mini-grid");
      [["定位", score(defect.detection_confidence)], ["类别", score(defect.class_confidence)], ["严重度", score(defect.severity_confidence)], ["坐标", Array.isArray(defect.bbox_xyxy) ? defect.bbox_xyxy.join(", ") : "未提供"]].forEach(([label, value]) => {
        const item = node("div", ""); item.append(node("span", "", `${label} `), node("b", "", value)); grid.append(item);
      });
      card.append(top, grid);
      if (defect.severity_probabilities) {
        const parts = Object.entries(defect.severity_probabilities).map(([name, value]) => `${name} ${score(value)}`);
        card.append(node("div", "probability-line", `四档分布 · ${parts.join(" · ")}`));
      }
      card.append(node("div", "probability-line", `Mask · ${defect.mask_ref || "未提供"}${safeMediaUrl(defect.mask_ref) ? "（图像绑定时可叠加）" : "（引用不可直接显示）"}`));
      list.append(card);
    });
  }

  function renderDecision(result) {
    const validation = result.validation;
    const routing = result.routing;
    const detection = result.detection;
    const conflict = routing.reason_codes.includes("EVIDENCE_CONFLICT");
    const rejected = validation.status !== "VALID" || conflict;
    const pill = $("validation-pill");
    pill.className = `state-pill ${validation.status === "VALID" ? "good" : "bad"}`;
    pill.textContent = validation.status;
    const checks = $("check-list"); checks.replaceChildren();
    const checkRows = [
      ["异常概率", score(detection.defect_probability), !conflict],
      ["定位区域", `${detection.defects.length} 处`, !conflict],
      ["模型来源", detection.model_version || "未提供", validation.reason_code !== "DEMO_RESULT"]
    ];
    checkRows.forEach(([label, value, good]) => {
      const row = node("div", `check-row ${good ? "" : "bad"}`);
      row.append(node("span", "check-mark", good ? "✓" : "×"), node("span", "", label), node("strong", "", value));
      checks.append(row);
    });
    const checkResult = $("check-result-icon").closest(".check-result");
    checkResult.className = `check-result ${rejected ? "bad" : ""}`;
    setText("check-result-icon", rejected ? "×" : "✓");
    setText("check-result-title", conflict ? "发现证据冲突" : validation.status === "VALID" ? "结构校验通过" : "结果已被拒绝");
    setText("validation-description", conflict ? "结构字段有效，但高异常概率没有对应缺陷区域；一致性检查阻断后续建议。" : validation.status === "VALID" ? "字段与来源校验通过。本案例仍是合成演示，不代表真实图像已被分析。" : validation.reason_code === "DEMO_RESULT" ? "检测器返回模拟结果，正式路径已拒绝；规则预览不能当作处置建议。" : "检测结果未通过校验，无法形成有效建议。");
    fillReasons($("validation-reasons"), validation.reason_code ? [validation.reason_code] : []);

    setText("final-path", routing.path);
    setText("path-meaning", pathNames[routing.path] || "未知路径");
    $("final-path").closest(".decision-panel").className = `surface decision-panel path-${routing.path.toLowerCase()}`;
    fillReasons($("routing-reasons"), routing.reason_codes);
    const reasonText = routing.reason_codes.map((code) => reasonNames[code] || code).join("；");
    setText("decision-explanation", routing.path === "FAILED" ? `系统停止给出自动建议：${reasonText || "缺少有效证据"}。` : routing.path === "REVIEW" ? `边界证据不足以支持直接建议：${reasonText}。转人工核对。` : routing.path === "NORMAL" ? "合成证据中没有可靠的缺陷定位，异常概率低于原型阈值；仅形成正常候选。" : `证据满足原型策略：${reasonText}。仍需授权人员确认。`);
    const proof = $("decision-proof"); proof.replaceChildren();
    let proofItems;
    if (conflict) proofItems = [["异常存在概率", score(detection.defect_probability)], ["对应缺陷区域", `${detection.defects.length} 处`]];
    else if (routing.reason_codes.includes("SEVERITY_BOUNDARY") && detection.defects[0]) {
      const top = Object.entries(detection.defects[0].severity_probabilities || {}).sort((a, b) => b[1] - a[1]).slice(0, 2);
      proofItems = [[top[0] ? top[0][0] : "最高档", top[0] ? score(top[0][1]) : "未提供"], [top[1] ? top[1][0] : "次高档", top[1] ? score(top[1][1]) : "未提供"]];
    } else if (routing.reason_codes.includes("DEMO_RESULT")) proofItems = [["数据模式", "MOCK"], ["图片分析", result.provenance.image_analyzed ? "已声明" : "未进行"]];
    else proofItems = [["异常存在概率", score(detection.defect_probability)], ["缺陷区域", `${detection.defects.length} 处`]];
    proofItems.forEach(([label, value]) => { const item = node("div", "proof-item"); item.append(node("span", "", label), node("strong", "", value)); proof.append(item); });

    const preview = $("preview-card"); preview.replaceChildren(); preview.hidden = !routing.preview;
    if (routing.preview) {
      preview.append(node("strong", "", `模拟规则预览：${routing.preview.path} · ${pathNames[routing.preview.path] || ""}`));
      preview.append(node("p", "", routing.preview.explanation));
      preview.append(node("p", "", `预览原因：${routing.preview.reason_codes.join(" / ") || "无"}。正式路径仍为 ${routing.path}。`));
    }
    const handoff = $("human-handoff"); handoff.replaceChildren();
    handoff.append(node("strong", "", routing.human_review_required ? "需要人工接管或复核" : "仍需按现场制度人工确认"));
    handoff.append(node("span", "", routing.path === "FAILED" ? "请查看校验原因与原始证据，修复问题后重新运行；不要根据被拒绝结果处置样本。" : routing.path === "REVIEW" ? "请核对缺陷区域、严重度边界和原始证据，保留模型原判。" : "当前仅有路径建议，未生成真实复核工单或产线动作。"));

    const pipe = (id, state, tone) => { const element = $(id); element.className = `pipeline-item ${tone || ""}`; setText(`${id}-state`, state); };
    pipe("pipe-evidence", `${detection.defects.length} 条定位记录`, "active");
    pipe("pipe-validation", conflict ? "一致性冲突" : validation.status === "VALID" ? "字段通过" : "结果拒绝", rejected ? "bad" : "active");
    pipe("pipe-routing", routing.path, routing.path === "FAILED" ? "bad" : routing.path === "REVIEW" ? "warn" : "active");
    pipe("pipe-human", routing.human_review_required ? "需要接管" : "按制度确认", routing.human_review_required ? "warn" : "active");
  }

  function renderAudit(result) {
    const source = result.provenance;
    setText("scope-badge", source.source_kind === "LOCAL_WORKFLOW" ? "本地 Mock · 模拟预览" : "合成 Replay · 非实测");
    setText("image-status", source.image_analyzed ? "图像已分析（来源声明）" : "图像未分析");
    setText("source-note", source.source_kind === "LOCAL_WORKFLOW" ? "本地模拟流程；预览路径与实际验证路径分开显示。" : "合成回放案例；用于解释路由规则，不代表模型成绩。");
    const audit = $("audit-grid"); audit.replaceChildren();
    [["数据来源", source.source_kind], ["决策范围", source.decision_scope], ["模型版本", result.detection.model_version || "未提供"], ["校准版本", result.detection.calibration_version || "未提供"], ["规则版本", "未提供 / 待接入"], ["生产可用", source.production_usable ? "是" : "否"]].forEach(([label, value]) => {
      const item = node("div", "audit-item"); item.append(node("span", "", label), node("strong", "", value)); audit.append(item);
    });
  }

  function renderTrace(result) {
    const list = $("trace-list"); list.replaceChildren();
    setText("trace-source", result.provenance.source_kind === "LOCAL_WORKFLOW" ? "本地程序 Trace · 非 AgentArts 平台记录" : "Replay 当前没有逐步 Trace");
    if (!result.trace.length) { list.append(node("div", "empty-state trace-empty", "该 Replay 样例仅保存路由结果，没有逐步执行记录。切换到“本地 Trace”查看真实存在的程序步骤。")); return; }
    result.trace.forEach((step, index) => {
      const card = node("article", "trace-step");
      card.append(node("div", "step-number", `STEP 0${index + 1} · ${step.stage}`), node("h3", "", step.label));
      const summary = step.stage === "DETECTION" ? `取得检测工具输出 · 异常概率 ${score(step.output_summary.defect_probability)}` : step.stage === "VALIDATION" ? `检查输出来源与结构 · ${step.output_summary.status || "结果已记录"}` : `形成路径 · ${step.output_summary.validated_path || step.output_summary.path || "结果已记录"}`;
      card.append(node("p", "", step.reason_codes.length ? `${summary} · ${step.reason_codes.join(" / ")}` : summary));
      const details = node("details", ""); details.append(node("summary", "", "展开结构化记录"));
      details.append(node("pre", "", JSON.stringify({ input: step.input_summary, output: step.output_summary }, null, 2)));
      card.append(details); list.append(card);
    });
  }

  function validateCase(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("JSON 顶层必须是 AgentCaseResult 对象。");
    if (value.contract_version !== "1.0" || !value.sample_id || !value.provenance || !value.image || !value.detection || !value.validation || !value.routing || !Array.isArray(value.trace)) throw new Error("JSON 不符合 AgentCaseResult v1 的必需结构。");
    if (value.provenance.demo_only !== true || value.provenance.production_usable !== false) throw new Error("本展示原型只接收明确标记为 Demo、不可用于生产的案例。");
    if (!["LOCAL_WORKFLOW", "SYNTHETIC_REPLAY"].includes(value.provenance.source_kind)) throw new Error("未知的数据来源。");
    if (!["NORMAL", "SUGGESTION", "REVIEW", "FAILED"].includes(value.routing.path) || !Array.isArray(value.routing.reason_codes) || typeof value.routing.human_review_required !== "boolean") throw new Error("决策路径或原因码无效。");
    if (!Array.isArray(value.detection.defects) || !["VALID", "INVALID_RESULT"].includes(value.validation.status)) throw new Error("检测或校验字段无效。");
    if (value.detection.defect_probability !== null && (typeof value.detection.defect_probability !== "number" || value.detection.defect_probability < 0 || value.detection.defect_probability > 1)) throw new Error("异常概率必须在 0 到 1 之间。");
    value.detection.defects.forEach((defect) => {
      if (!defect || !defect.defect_id || !defect.defect_type || !defect.severity || !["detection_confidence", "class_confidence", "severity_confidence"].every((key) => typeof defect[key] === "number" && defect[key] >= 0 && defect[key] <= 1)) throw new Error("缺陷证据字段无效。");
    });
    if (value.routing.preview && (value.provenance.source_kind !== "LOCAL_WORKFLOW" || !["NORMAL", "SUGGESTION", "REVIEW", "FAILED"].includes(value.routing.preview.path))) throw new Error("预览路径无效。");
    if (value.provenance.source_kind === "LOCAL_WORKFLOW" && value.validation.status === "INVALID_RESULT" && value.routing.path !== "FAILED") throw new Error("模拟结果被拒绝后，正式路径必须为 FAILED。");
    if (value.trace.some((step) => !step || !["DETECTION", "VALIDATION", "ROUTING"].includes(step.stage) || !step.label || !Array.isArray(step.reason_codes) || !step.input_summary || !step.output_summary)) throw new Error("Trace 记录无效。");
    return value;
  }

  function render(result) {
    currentCase = validateCase(result);
    showError("");
    setText("trace-tail", "MODEL → CHECK → ROUTE → HUMAN");
    setText("sample-id", currentCase.sample_id);
    renderEvidence(currentCase);
    renderDecision(currentCase);
    renderAudit(currentCase);
    renderTrace(currentCase);
  }

  function renderBaseline(result) {
    if (!result || result.contract_version !== "baseline-evidence/1.0" || !result.image || !result.evidence || !result.provenance || !result.provenance.integrity || !result.agent_status || result.image.evidence_bound !== true || result.provenance.image_analyzed !== true || result.agent_status.status !== "NOT_RUN") {
      throw new Error("真实图像证据对象不符合预期协议。");
    }
    const integrity = result.provenance.integrity;
    const contentMatched = integrity.status === "CONTENT_MATCH";
    if (!contentMatched && integrity.status !== "LEGACY_UNVERIFIED") throw new Error("未知的证据完整性状态。");
    currentCase = null;
    clearLocalImage();
    showError("");
    setText("sample-id", result.sample_id);
    setText("source-note", `MVTec AD bottle/test · 原始距离非概率 · ${contentMatched ? "内容摘要匹配" : "历史记录未做内容校验"}`);
    setText("scope-badge", contentMatched ? "MVTec 实测证据 · 摘要匹配" : "MVTec 实测证据 · 历史未校验");
    setText("image-status", `图像已分析 · ${contentMatched ? "图像与 mask 内容匹配" : "仅路径和样本 ID 对齐"}`);

    const viewer = $("image-viewer"); viewer.replaceChildren();
    const stack = node("div", "image-stack");
    const base = node("img", "base-image");
    base.alt = "与基线推理记录绑定的 MVTec bottle 图像";
    base.src = new URL(result.image.ref, apiBase).href;
    base.onerror = () => {
      if (stack.isConnected) viewer.replaceChildren(node("div", "image-placeholder", "绑定图像无法加载；请重新载入该样本。"));
    };
    stack.append(base);
    const mask = node("img", "mask-overlay");
    mask.alt = "同一样本的预测 mask";
    mask.src = new URL(result.image.mask_ref, apiBase).href;
    mask.onerror = () => {
      if (!stack.isConnected) return;
      mask.remove();
      const rectangle = stack.querySelector("svg");
      if (rectangle) rectangle.remove();
      setText("image-status", "预测 mask 无法加载 · 请重新载入该样本");
      setText("evidence-count", "预测 mask 无法显示");
    };
    stack.append(mask);
    const box = result.image.mask_bbox_xyxy;
    if (Array.isArray(box) && box.length === 4) {
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", `0 0 ${result.image.width} ${result.image.height}`);
      svg.setAttribute("aria-label", "预测 mask 外接矩形");
      const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      rect.setAttribute("x", String(box[0])); rect.setAttribute("y", String(box[1]));
      rect.setAttribute("width", String(box[2] - box[0])); rect.setAttribute("height", String(box[3] - box[1]));
      svg.append(rect); stack.append(svg);
    }
    viewer.append(stack, node("span", "view-caption", "MVTEC TEST IMAGE + PREDICTED MASK · 同一样本"));
    setText("image-note", "原图按推理预处理缩放为 256×256；红色区域是预测 mask，框为该 mask 的外接矩形，不是四档缺陷检测框。");
    setText("evidence-count", box ? "预测 mask 可用" : "预测 mask 为空");
    setText("metric-label", "异常原始距离");
    setText("metric-kind", "RAW DISTANCE · NOT PROBABILITY");
    setText("defect-probability", Number(result.evidence.anomaly_score).toFixed(3));
    setText("evidence-summary", result.evidence.is_anomaly ? "异常分数超过临时图像阈值。该阈值仅由正常训练图像估计，不能解释为可信概率或四档分级。" : "异常分数未超过临时图像阈值。此判断只属于当前基线实验，不能作为项目放行建议。");
    const scores = $("score-grid"); scores.replaceChildren();
    [["临时图像阈值", Number(result.evidence.image_threshold).toFixed(3), "原始距离"], ["预测 mask 阈值", Number(result.evidence.mask_threshold).toFixed(3), "像素级"], ["推理耗时", result.evidence.inference_ms == null ? "未提供" : `${result.evidence.inference_ms} ms`, "已有记录"]].forEach(([label, value, note]) => {
      const card = node("div", "score-card"); card.append(node("span", "", label), node("strong", "", value), node("small", "", note)); scores.append(card);
    });
    const defects = $("defect-list"); defects.replaceChildren();
    defects.append(node("div", "empty-state", box ? `预测 mask 外接矩形：${box.join(", ")}。当前模型没有缺陷类别、四档严重度或逐缺陷置信度。` : "预测 mask 为空；当前模型没有缺陷类别、四档严重度或逐缺陷置信度。"));

    const pill = $("validation-pill"); pill.className = "state-pill bad"; pill.textContent = "PARTIAL";
    const checks = $("check-list"); checks.replaceChildren();
    [["原图与 mask", "同一样本", true], ["内容摘要", contentMatched ? "匹配" : "旧记录未提供", contentMatched], ["分数语义", "原始距离", false], ["四档严重度", "未提供", false]].forEach(([label, value, good]) => {
      const row = node("div", `check-row ${good ? "" : "bad"}`); row.append(node("span", "check-mark", good ? "✓" : "×"), node("span", "", label), node("strong", "", value)); checks.append(row);
    });
    $("check-result-icon").closest(".check-result").className = "check-result bad";
    setText("check-result-icon", "!");
    setText("check-result-title", contentMatched ? "图像内容已核对，Agent 契约仍不完整" : "历史记录仅核对路径，Agent 契约仍不完整");
    setText("validation-description", "当前基线不能提供校准后的缺陷概率和四档严重度，因此尚不能进入现有 Agent 路由。内容摘要匹配也不等于模型判断正确。");
    fillReasons($("validation-reasons"), result.agent_status.reason_codes);
    $("final-path").closest(".decision-panel").className = "surface decision-panel";
    setText("final-path", "NOT RUN");
    setText("path-meaning", "Agent 风险分流未运行");
    setText("decision-explanation", "记录显示模型曾处理这张图并输出原始异常距离与预测 mask，但不足以推导 Acceptable / Marginal NG / NG / Gross NG 或正式处置建议。");
    const proof = $("decision-proof"); proof.replaceChildren();
    [["原始异常距离", Number(result.evidence.anomaly_score).toFixed(3)], ["临时阈值", Number(result.evidence.image_threshold).toFixed(3)]].forEach(([label, value]) => { const item = node("div", "proof-item"); item.append(node("span", "", label), node("strong", "", value)); proof.append(item); });
    fillReasons($("routing-reasons"), result.agent_status.reason_codes);
    $("preview-card").hidden = true;
    const handoff = $("human-handoff"); handoff.replaceChildren();
    handoff.append(node("strong", "", "仅作定位实验观察"), node("span", "", "请人工查看原图与预测 mask。当前没有 Agent 复核工单，也没有四档处置建议。"));
    const pipe = (id, state, tone) => { $(id).className = `pipeline-item ${tone}`; setText(`${id}-state`, state); };
    pipe("pipe-evidence", "实测图像 + mask", "active");
    pipe("pipe-validation", "契约不完整", "warn");
    pipe("pipe-routing", "未运行", "warn");
    pipe("pipe-human", "人工查看", "active");
    setText("trace-source", "基线保存了推理结果；没有 Agent 执行 Trace");
    setText("trace-tail", "MODEL EVIDENCE ONLY · AGENT NOT RUN");
    $("trace-list").replaceChildren(node("div", "empty-state trace-empty", "这是 MVTec bottle 的真实图像推理记录，不是 AgentArts 或本地 Router 的运行记录。缺少四档分级时，系统不生成 Agent 决策链。"));
    const audit = $("audit-grid"); audit.replaceChildren();
    [["数据集", "MVTec AD"], ["范围", "bottle/test"], ["模型版本", result.evidence.model_version], ["完整性", integrity.status], ["运行 ID", integrity.run_id || "历史记录无"], ["原图摘要", integrity.image_sha256 ? integrity.image_sha256.slice(0, 12) + "…" : "未记录"], ["mask 摘要", integrity.mask_sha256 ? integrity.mask_sha256.slice(0, 12) + "…" : "未记录"], ["阈值状态", result.provenance.threshold_status], ["生产可用", "否"]].forEach(([label, value]) => { const item = node("div", "audit-item"); item.append(node("span", "", label), node("strong", "", value)); audit.append(item); });
  }

  examples.forEach((example) => {
    const button = node("button", "scenario-button", example.label);
    button.type = "button";
    button.addEventListener("click", () => {
      activeKey = example.key;
      clearLocalImage();
      tabs.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button));
      render(example.data);
    });
    tabs.append(button);
  });

  $("json-input").addEventListener("change", async (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 2_000_000) throw new Error("JSON 文件不能超过 2 MB。");
      const data = JSON.parse(await file.text());
      validateCase(data);
      activeKey = null;
      clearLocalImage();
      tabs.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
      render(data);
    } catch (error) { showError(error.message || "JSON 文件无法读取。"); }
    event.target.value = "";
  });

  $("image-input").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    if (!currentCase) {
      showError("当前真实证据视图已绑定其推理图像；请切换至演示案例后再预览本地图片。");
      event.target.value = "";
      return;
    }
    clearLocalImage();
    localImageUrl = URL.createObjectURL(file);
    renderImage(currentCase);
    event.target.value = "";
  });

  const apiBase = window.location.protocol === "file:" ? "http://127.0.0.1:8765" : window.location.origin;
  const apiStatus = $("api-status");
  function setApiStatus(message, state) {
    apiStatus.textContent = message;
    apiStatus.className = `api-status ${state || ""}`;
  }
  async function apiFetch(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 7000);
    try {
      return await fetch(`${apiBase}${path}`, { ...options, signal: controller.signal, cache: "no-store" });
    } finally {
      clearTimeout(timeout);
    }
  }
  async function checkApi() {
    try {
      const response = await apiFetch("/api/health");
      if (!response.ok) throw new Error("接口不可用");
      const health = await response.json();
      if (health.mode !== "mock") throw new Error("接口模式不匹配");
      setApiStatus("本地接口已连接 · MOCK", "ready");
      try {
        await loadBaselineList();
      } catch {
        const select = $("baseline-sample");
        select.replaceChildren(node("option", "", "真实证据目录不可用"));
        $("load-baseline").disabled = true;
        setApiStatus("本地 Agent 已连接 · 真实证据不可用", "ready");
      }
    } catch {
      setApiStatus("本地接口未连接 · 可先查看静态案例", "error");
      const select = $("baseline-sample");
      select.replaceChildren(node("option", "", "本地接口未连接"));
      $("load-baseline").disabled = true;
    }
  }
  async function loadBaselineList() {
    const response = await apiFetch("/api/baseline-cases");
    if (!response.ok) throw new Error("真实证据目录不可用");
    const payload = await response.json();
    const cases = Array.isArray(payload.cases) ? payload.cases : [];
    const select = $("baseline-sample");
    select.replaceChildren();
    if (!cases.length) {
      select.append(node("option", "", "没有已保存的推理记录"));
      $("load-baseline").disabled = true;
      return;
    }
    cases.forEach((sampleId) => {
      const option = node("option", "", sampleId);
      option.value = sampleId;
      select.append(option);
    });
    select.value = cases.includes("bottle_broken_large_000") ? "bottle_broken_large_000" : cases[0];
    $("load-baseline").disabled = false;
  }
  $("run-api").addEventListener("click", async () => {
    const button = $("run-api");
    const sampleId = $("run-sample-id").value.trim();
    const scenario = $("run-scenario").value;
    if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(sampleId)) {
      showError("样本 ID 须为 1–64 位字母、数字、连字符或下划线，且以字母或数字开头。");
      return;
    }
    button.disabled = true;
    showError("");
    setApiStatus("正在调用本地 Agent 流程…", "");
    try {
      const response = await apiFetch("/api/agent-case", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_id: sampleId, scenario })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "本地流程运行失败。");
      validateCase(data);
      clearLocalImage();
      activeKey = null;
      tabs.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
      render(data);
      setApiStatus("本地流程已运行 · MOCK · 图像未分析", "ready");
    } catch (error) {
      const message = error.name === "AbortError" ? "本地接口响应超时。" : error.message || "无法连接本地接口。";
      showError(`${message} 请先运行 python workspace_server.py。`);
      setApiStatus("本地流程运行失败", "error");
    } finally {
      button.disabled = false;
    }
  });
  $("load-baseline").addEventListener("click", async () => {
    const button = $("load-baseline");
    const sampleId = $("baseline-sample").value;
    if (!sampleId) return;
    button.disabled = true;
    showError("");
    try {
      const response = await apiFetch(`/api/baseline-case?sample_id=${encodeURIComponent(sampleId)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || "无法读取真实图像证据。");
      activeKey = null;
      tabs.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
      renderBaseline(data);
      setApiStatus("真实图像证据已载入 · Agent 未运行", "ready");
    } catch (error) {
      showError(error.name === "AbortError" ? "读取真实证据超时。" : error.message || "无法读取真实证据。");
    } finally {
      button.disabled = false;
    }
  });
  window.addEventListener("beforeunload", clearLocalImage);
  if (examples.length) tabs.querySelector("button:last-child").click();
  checkApi();
})();
