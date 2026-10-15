# Agent 决策工作台 MVP

离线展示可直接用浏览器打开 [index.html](index.html)，无需安装依赖。要让前端调用现有本地 Agent 流程，在仓库根目录运行：

```powershell
python workspace_server.py
```

然后打开 `http://127.0.0.1:8765/`，在“本地 Agent 流程”选择 `normal`、`boundary` 或 `failure` 并点击运行。也可以在已打开的 `file:///.../prototype/index.html` 页面运行此接口；跨源请求仅用于本机演示。

`GET /api/health` 返回接口状态。`POST /api/agent-case` 接收：

```json
{"sample_id":"W-0304","scenario":"boundary"}
```

返回一个 [AgentCaseResult v1](../contracts/demo_view_contract_v1.md)。聚合服务调用现有 `run_inspection`，把 Detector、Validation、Router 和本地 Trace 汇总成前端对象；不修改现有路由逻辑。

首页默认打开“本地 Trace”案例，使证据校验、模拟预览与实际验证路径的区别在第一屏可见。

## 可以演示什么

- `NORMAL`：合成 Replay 的正常候选路径；
- `REVIEW`：合成 Replay 的严重度边界复核路径；
- `FAILED`：合成 Replay 的 `EVIDENCE_CONFLICT` 阻塞路径；
- 本地 Trace：真实存在于本地程序的 Detector → Validation → Routing 记录；该案例为 mock，正式路径是 `FAILED`，旁边另列模拟规则预览 `REVIEW`。

前三个案例来自现有 Replay 的合成输入，**没有真实模型成绩，也没有逐步 Trace**。第四个案例展示本地程序 Trace，不是 AgentArts 平台 Trace。页面不会虚构 Replay 的执行步骤。

## 导入自己的案例

点击“导入 AgentCaseResult JSON”，选择符合 [Demo 数据协议 v1](../contracts/demo_view_contract_v1.md) 的单个 JSON 对象。协议示例文件 [demo_view_cases_v1.json](../contracts/demo_view_cases_v1.json) 是数组；要导入其中一条，请先将该对象单独保存为 JSON 文件。

页面只消费聚合后的 `AgentCaseResult`，不直接调用 Detector、Router 或模型接口。当前只接受 `demo_only=true`、`production_usable=false` 的演示数据。导入文件只在浏览器本地读取。

本地聚合接口也只返回 mock 数据：`image_analyzed=false`、`image.evidence_bound=false`，实际验证路径仍是 `FAILED`；若规则预览为 `NORMAL` 或 `REVIEW`，页面会另列预览并明确其演示范围。该接口不接收图片，也不读取图片文件。

## 查看已保存的真实图像证据

启动同一个 `workspace_server.py` 后，页面的“MVTec bottle · 真实图像证据”下拉框会列出 `outputs/json` 中已有的 bottle 推理记录。选择样本即可查看与该记录绑定的 MVTec 原图、256×256 预测 mask、mask 外接矩形、原始异常距离和临时阈值。图像及 mask 由本地服务器从固定目录读取，不接受任意文件路径。

这类记录使用独立的 [真实图像证据协议](../contracts/baseline_evidence_v1.md)：原始距离不是概率，基线没有四档严重度，页面明确显示 `Agent NOT RUN`。因此“真实图像证据”展示的是模型定位实验，不是完整的 Agent 决策闭环，也不代表 ICME 成绩。

新生成的推理记录会带运行 ID、原图与 mask 的 SHA-256；服务在展示前核对内容。旧记录没有这些字段时显示“历史记录，内容未校验”，不会回填为已验证。摘要不匹配时服务拒绝展示该样本。

“仅预览本地图片”不会将图片发送到服务端，也不会把演示检测结果绑定到上传的图片。导入的 JSON 若有已绑定的图像引用和尺寸，页面才会绘制其缺陷框；可加载的掩码引用会叠加显示。`mock://` 与 `fixture://` 掩码只是示意引用，页面不会伪造掩码图像。

## 范围

本页面只含证据、校验、决策、Trace 和人工交接说明。没有登录、批次管理、设置、真实复核工单或产线控制。四档严重度及多类分数在内置案例中均为合成/模拟数据。
