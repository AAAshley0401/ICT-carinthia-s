# Task 10｜前端 Demo 数据协议 v1

状态：**前端 Demo 内部协议冻结**，2026-10-14。适用于合成与模拟样例；不代表真实模型接口或 AgentArts 平台协议已冻结。

前端只消费一个由服务端或预生成文件提供的 `AgentCaseResult`（此前草案名为 `DemoCaseView`）。它是展示聚合对象，不是检测模型的原始输出。后端负责把 Detector、Validation、Router 和本地 Trace 汇总；前端只读，不重新路由。

机器可读结构见 [demo_view_contract_v1.schema.json](demo_view_contract_v1.schema.json)，示例见 [demo_view_cases_v1.json](demo_view_cases_v1.json)。相关页面设计见 [07-AGENT前端页面设计方案](../docs/07-AGENT前端页面设计方案.md)。

## 顶层结构

```ts
interface AgentCaseResult {
  contract_version: "1.0";
  sample_id: string;
  provenance: {
    source_kind: "LOCAL_WORKFLOW" | "SYNTHETIC_REPLAY";
    demo_only: true;
    image_analyzed: boolean;
    decision_scope: "SIMULATION_PREVIEW" | "SYNTHETIC_REPLAY";
    production_usable: false;
  };
  image: {
    ref: string | null;
    width: number | null;
    height: number | null;
    evidence_bound: boolean;
  };
  detection: {
    status: "success" | "failed";
    model_version: string | null;
    calibration_version: string | null;
    defect_probability: number | null;
    defects: DemoDefect[];
    error_code: string | null;
  };
  validation: {
    status: "VALID" | "INVALID_RESULT";
    reason_code: string | null;
  };
  routing: {
    path: "NORMAL" | "SUGGESTION" | "REVIEW" | "FAILED";
    reason_codes: string[];
    human_review_required: boolean;
    recommended_action: string | null;
    preview: null | {
      path: "NORMAL" | "SUGGESTION" | "REVIEW" | "FAILED";
      reason_codes: string[];
      human_review_required: boolean;
      explanation: string;
    };
  };
  trace: Array<{
    stage: "DETECTION" | "VALIDATION" | "ROUTING";
    label: string;
    input_summary: Record<string, unknown>;
    output_summary: Record<string, unknown>;
    reason_codes: string[];
  }>;
}

interface DemoDefect {
  defect_id: string;
  defect_type: string;
  detection_confidence: number;
  class_confidence: number;
  severity: "Acceptable" | "Marginal NG" | "NG" | "Gross NG";
  severity_confidence: number;
  severity_probabilities: Record<string, number>;
  bbox_xyxy: [number, number, number, number] | null;
  mask_ref: string | null;
}
```

## 字段语义与不变量

1. `routing.path` 是**实际验证路径**。本地 mock 的检测结果因 `DEMO_RESULT` 不可用于真实决策，因此 `validation.status=INVALID_RESULT`，`routing.path=FAILED`，即使预览路径是 `NORMAL` 或 `REVIEW`。
2. `routing.preview` 只表达演示规则在该模拟输入上的预览。界面必须明确写“模拟规则预览”，不能把 `preview.path` 当作正式建议。合成 Replay 若没有预览层，填 `null`。
3. `provenance.demo_only=true`、`production_usable=false` 对本协议的所有记录固定成立。`source_kind=SYNTHETIC_REPLAY` 即使内部构造的模型字段写 `mode=model`，仍须作为合成样例呈现。
4. `image.evidence_bound=false` 表示检测结果没有与页面图片建立可信绑定。此时不得把缺陷框叠到图片上；`bbox_xyxy` 可以保留为原始合成字段。没有图片尺寸时 `width`、`height` 均为 `null`，不得默认 1024。
5. `defect_probability` 是图像级；其他分数是单缺陷级。缺字段用 `null` 或明确失败状态，不生成默认高分。协议示例中的四档数值均不代表真实严重度模型能力。
6. `reason_codes` 使用后端原因码原值，如 `DEMO_RESULT`、`EVIDENCE_CONFLICT`、`SEVERITY_BOUNDARY`；中文文案由前端映射，但不能更改路径或原因码。
7. `trace` 只含真实存在的本地步骤。当前没有 AgentArts 平台运行时间、耗时、角色交接和知识库引用，不添加虚构字段或记录。
8. `model_version`、`calibration_version` 来自 Detector。当前路由没有稳定的 `policy_version`，本协议 v1 不包含它；将来若纳入审计，需升级协议版本。

## 从现有代码映射

| 来源 | 映射 |
|---|---|
| `DetectorAgent.detect()` / `ModelAdapter.detect()` | `detection`；原始缺陷框和模型版本来自这里 |
| `validate_detection_result()` | `validation.status`、`validation.reason_code` |
| `route_detection()` | `routing.path`、`reason_codes`、`human_review_required`、`recommended_action` |
| `preview_demo_route()` | `routing.preview`，仅用于 mock 预览 |
| `main.py` 的 `execution_trace` | 映射为三类 `trace.stage`；不要把 `RoutingEngine` 伪称为已接入平台的 Agent |
| `src/replay.py` 合成样例 | `source_kind=SYNTHETIC_REPLAY`；可展示路由逻辑，不用于模型成绩；当前 Replay 没有逐步 Trace，填空数组 |

当前 `/v1/inspect` 只返回 Detector 结果，不能直接填充完整 `AgentCaseResult`。前端可读取预生成的聚合 JSON，也可通过下述本地薄 API 获取完整流程结果；前端不得自行拼接多个 Agent 输出。

本地联调的薄 API 现已放在 `workspace_server.py`：`POST /api/agent-case` 接收 `sample_id` 和 `scenario`，返回一个 `AgentCaseResult`。该服务只调用已有 `run_inspection` 并映射输出，不读图、不改变路由规则；`GET /api/health` 返回 mock 模式状态。

## UI 必须显示的状态

| 条件 | 主标题 | 次级信息 |
|---|---|---|
| `routing.path=FAILED`、`reason_codes=["DEMO_RESULT"]` | 模拟结果已拒绝 | 可查看模拟规则预览；无正式处置建议 |
| `routing.path=FAILED`、`reason_codes=["EVIDENCE_CONFLICT"]` | 证据冲突，已阻塞 | 显示异常概率与缺陷列表为空的矛盾 |
| `routing.path=REVIEW` | 建议人工复核 | 展示证据不足或边界原因；若为合成 Replay，继续标合成 |

## 版本变更规则

v1 字段名与含义不原地改动。新增可选字段可发布 v1.1；改变 `routing.path` 含义、来源语义或把预览与验证合并，必须发布 v2。真实模型和 AgentArts 接口接入时先做适配，不让前端直接依赖其原始返回格式。
