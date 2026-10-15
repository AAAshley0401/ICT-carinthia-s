# AgentArts 接入准备

**状态：AgentArts 公测已于 2026-10-14 通过；平台侧步骤与导入文件已备好，但尚无任何平台调用记录。** 本目录描述当前代码实际返回的接口。

[OpenAPI 3.0 草案](mock_detector.openapi.json)记录当前 `/v1/inspect` 的请求与响应形状。[平台导入用文件](plugin_import_v1.json)在其基础上补了 Bearer 鉴权声明与公网地址占位，导入前需替换 `servers[0].url`。两者均尚未经 AgentArts 导入验证。

接入步骤、平台限制与验收标志见 [docs/10-AgentArts接入路线](../docs/10-AgentArts接入路线.md)。

## 当前本地工具

运行 `python src/mock_inference_server.py`，默认监听 `127.0.0.1:8000`。`GET /health` 返回 `{"status":"ok","mode":"mock"}`。`POST /v1/inspect` 接收 JSON：

```json
{"sample_id":"W-0304","image_url":"https://example.invalid/wafer.png","scenario":"boundary"}
```

`image_url` 必填且只检查为非空字符串；服务**不会下载、打开或分析图像**。`sample_id` 可省略，服务会由 URL 摘要生成演示 ID。`scenario` 可选，取 `normal`、`boundary` 或 `failure`，默认 `normal`。响应直接来自 `DetectorAgent.detect()`，并非聚合后的前端 `AgentCaseResult`：

```json
{
  "schema_version": "1.0",
  "sample_id": "W-0304",
  "status": "success",
  "mode": "mock",
  "demo_only": true,
  "image_analyzed": false,
  "model_version": "mock-detector-v2",
  "calibration_version": "mock-unvalidated",
  "inference_timestamp": "2026-10-14T15:00:00+00:00",
  "defect_probability": 0.95,
  "defects": [{
    "defect_id": "d1",
    "defect_type": "scratch",
    "detection_confidence": 0.96,
    "class_confidence": 0.91,
    "severity": "Marginal NG",
    "severity_confidence": 0.52,
    "severity_probabilities": {
      "Acceptable": 0.05,
      "Marginal NG": 0.52,
      "NG": 0.43,
      "Gross NG": 0.0
    },
    "bbox_xyxy": [320, 390, 500, 470],
    "mask_ref": "mock://masks/W-0304/d1"
  }],
  "error": null
}
```

`inference_timestamp` 在每次调用时生成，上面时间只作格式示例。`normal` 返回低异常概率和空缺陷列表；`failure` 返回 `status=failed`、`defect_probability=null`、`error=timeout`。上述分数和四档字段均为固定模拟值，不能作为模型成绩。`mock://` mask 不对应实际图像。

`POST /v1/detector` 是同一个本地模拟服务的别名，请求字段改为 `image_path`；它也不读图。Agent 工作台另用 `POST /api/agent-case` 调用本地 `run_inspection`，返回聚合后的 [Demo 数据协议](../contracts/demo_view_contract_v1.md)。平台工具配置应明确选择一种接口，不能混用响应结构。

## 平台迁移顺序

1. 核对 AgentArts 账号、自定义工具权限与平台实际接受的接口格式；将已授权的**模拟**工具部署在平台可访问的 HTTPS 地址，配置鉴权。当前本机 `127.0.0.1` 不能从云端访问。
2. 先完成单次工具调用并保存平台原生 Trace，核对 `demo_only=true`、`image_analyzed=false` 和错误路径；再配置 Validation、Routing 与人工交接。模拟输出的实际验证路径应为 `FAILED`，规则预览需单独标示。
3. 真实模型达到[接入门槛](../contracts/real_model_integration_gate_v1.md)后，再由 `ModelBackend → ModelAdapter` 接入相同的 Agent 决策链，重新核对平台 Trace、版本和人工确认边界。

受限原图的跨服务传输必须先符合数据许可；不能因为插件需要 URL 就直接公开图片。未经平台实际调用的流程不得标为“AgentArts 已验证”。
