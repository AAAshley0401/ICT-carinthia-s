# MVTec bottle 真实图像证据视图 v1

本协议用于把**已有的真实推理输出**与其原图、预测 mask 绑定到展示页。它独立于 [AgentCaseResult Demo 协议](demo_view_contract_v1.md)，因为当前 PatchCore 基线只有原始最近邻距离和像素 mask，没有校准的缺陷概率、缺陷类别或四档严重度。不得把原始距离填入 `defect_probability`，也不得补造分级字段。

`GET /api/baseline-cases` 列出已有记录的样本 ID 和可选版本；`GET /api/baseline-case?sample_id=...&version=q995`（或 `q999`）返回一个 `baseline-evidence/1.0` 对象。`version=legacy` 可读取旧目录记录。`GET /api/baseline-compare?sample_id=...` 返回同一样本两个版本的对象，供前端并排展示。响应包含：

- `provenance`：MVTec AD bottle/test、`image_analyzed=true`、`production_usable=false`、临时阈值状态及 `integrity`；
- `image`：经过与推理一致的 256×256 缩放后的原图 URL、预测 mask URL、mask 外接矩形、预测 mask 像素数与面积占比，以及 `evidence_bound=true`；
- `evidence`：原始异常分数、原始分数类型、临时图像阈值、是否超过阈值、mask 阈值、模型版本和推理耗时；
- `agent_status`：`NOT_RUN`，原因码为 `SEVERITY_NOT_AVAILABLE` 与 `UNCALIBRATED_SCORE`。

图像绑定条件：服务端从固定的 MVTec bottle/test 路径，以及版本白名单对应的 `outputs/experiments/bottle_q995_bound`、`outputs/experiments/bottle_q999_bound` 或旧 `outputs/json`、`outputs/masks` 目录推导同一 `sample_id`，核对记录内的绝对路径与预期路径一致，并检查 mask 尺寸。浏览器只获得受限的本地媒体 URL，不接收任意文件路径。mask 外接矩形与面积是预测 mask 的几何量，不是四档缺陷检测框。

媒体 URL 同时带有固定版本标识和当前记录的 `run_id`；历史记录使用 `legacy` 标记。服务端在读取媒体时核对版本和运行标记，若结果记录在页面加载后已被另一轮推理替换，则拒绝旧 URL，页面提示重新载入样本。历史记录没有内容摘要，因此旧记录不能证明文件内容与当年的推理一致。

从新增推理记录开始，`algorithm/tools/bottle_patchcore.py` 在结果 JSON 中写入 `evidence_manifest`：`manifest_version`、随机 `run_id`、原图文件 SHA-256、预测 mask 文件 SHA-256、生成时间。服务在返回记录或媒体前核对摘要：

| `provenance.integrity.status` | 含义 | 页面处理 |
|---|---|---|
| `CONTENT_MATCH` | 当前原图和预测 mask 字节与记录中的 SHA-256 一致 | 显示运行 ID 与摘要前缀 |
| `LEGACY_UNVERIFIED` | 旧记录没有 manifest，仅路径和样本 ID 对齐 | 明确显示“历史记录，内容未校验” |
| 摘要不一致或 manifest 不完整 | 证据不可安全绑定 | 接口拒绝返回记录和媒体 |

实验版本还需要 `integrity.checkpoint_status=CONTENT_MATCH`。只有原图、预测 mask 和 checkpoint 三者都匹配时，前端才允许打开 q=.995 / q=.999 双版本对照；否则只返回错误，不降级成部分对照。

`CONTENT_MATCH` 证明当前字节与同一结果 JSON 的摘要一致，不证明模型判断正确，也不是防篡改签名。旧记录不能追溯生成时内容；不会自动回填并声称已验证。正式审计还应保存不可改写的运行日志或签名，以及模型权重摘要。

`algorithm/tools/bottle_patchcore.py`、`algorithm/tools/evaluate_bottle.py` 等入口在新记录的 `evidence_manifest` 中保存 `checkpoint_sha256` 和 `preprocessing`。q=.995 / q=.999 已分别重新推理到两个 `_bound` 目录，各有 83 条新记录；旧实验目录完整保留。服务端仅展示新目录并对固定 checkpoint 路径核对摘要；缺字段或摘要不匹配时拒绝展示。页面权重绑定显示“摘要匹配”。这证明当前文件与记录的摘要一致，仍不等于不可改写的运行日志或签名。

前端对此对象展示“真实图像证据，Agent 分流未运行”。真实图像和 mask 可作为定位实验样例；当前不能由此得出项目四档处置建议，也不能声称 Agent 已对该图片完成风险分流。原始数据、模型文件和推理输出保持在 Git 忽略目录，服务仅监听 `127.0.0.1`。

双版本视图只对照同一原图的原始异常距离、临时像素阈值与预测 mask 面积。两个版本分别读取固定目录并核对各自的 `run_id`、原图、预测 mask 和 checkpoint SHA-256；实验目录缺少 manifest 时直接拒绝。该视图不载入公开数据集真值 mask，也不把数据集标签送入 Agent。两版的 `agent_status` 均为 `NOT_RUN`。

可用 `python algorithm/tools/audit_evidence_manifests.py <实验目录> <MVTec bottle 根目录> <checkpoint> --output <报告路径>` 批量核验一个版本。该报告只统计 manifest、文件摘要、预处理标识和 256×256 mask 尺寸，不评估模型质量，也不产生 Agent 决策。

通用 `infer()` 默认不读取真值 mask；离线评估与样例导出入口须显式设置 `include_ground_truth=True`，才会把真值用于评估可视化。两版完整评估记录的 JSON 中有真值文件路径；工作台聚合对象仅取原图、预测 mask 和模型分数，不向前端或 Agent 传递真值路径。
