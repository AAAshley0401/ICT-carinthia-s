# MVTec bottle 真实图像证据视图 v1

本协议用于把**已有的真实推理输出**与其原图、预测 mask 绑定到展示页。它独立于 [AgentCaseResult Demo 协议](demo_view_contract_v1.md)，因为当前 PatchCore 基线只有原始最近邻距离和像素 mask，没有校准的缺陷概率、缺陷类别或四档严重度。不得把原始距离填入 `defect_probability`，也不得补造分级字段。

`GET /api/baseline-cases` 列出已有记录的样本 ID；`GET /api/baseline-case?sample_id=...` 返回一个 `baseline-evidence/1.0` 对象。响应包含：

- `provenance`：MVTec AD bottle/test、`image_analyzed=true`、`production_usable=false`、临时阈值状态及 `integrity`；
- `image`：经过与推理一致的 256×256 缩放后的原图 URL、预测 mask URL、mask 外接矩形和 `evidence_bound=true`；
- `evidence`：原始异常分数、原始分数类型、临时图像阈值、是否超过阈值、mask 阈值、模型版本和推理耗时；
- `agent_status`：`NOT_RUN`，原因码为 `SEVERITY_NOT_AVAILABLE` 与 `UNCALIBRATED_SCORE`。

图像绑定条件：服务端从固定的 MVTec bottle/test 路径、`outputs/json` 记录和 `outputs/masks` 文件推导同一 `sample_id`，核对记录内的绝对路径与预期路径一致，并检查 mask 尺寸。浏览器只获得受限的本地媒体 URL，不接收任意文件路径。mask 外接矩形是预测 mask 的几何范围，不是四档缺陷检测框。

媒体 URL 带有当前记录的 `run_id`；历史记录使用 `legacy` 标记。服务端在读取媒体时核对该标记，若结果记录在页面加载后已被另一轮推理替换，则拒绝旧 URL，页面提示重新载入样本。历史记录没有内容摘要，因此 `legacy` 仅能防止记录身份切换，不能证明文件内容与当年的推理一致。

从新增推理记录开始，`tools/bottle_patchcore.py` 在结果 JSON 中写入 `evidence_manifest`：`manifest_version`、随机 `run_id`、原图文件 SHA-256、预测 mask 文件 SHA-256、生成时间。服务在返回记录或媒体前核对摘要：

| `provenance.integrity.status` | 含义 | 页面处理 |
|---|---|---|
| `CONTENT_MATCH` | 当前文件字节与记录中的两个 SHA-256 一致 | 显示运行 ID 与摘要前缀 |
| `LEGACY_UNVERIFIED` | 旧记录没有 manifest，仅路径和样本 ID 对齐 | 明确显示“历史记录，内容未校验” |
| 摘要不一致或 manifest 不完整 | 证据不可安全绑定 | 接口拒绝返回记录和媒体 |

`CONTENT_MATCH` 证明当前字节与同一结果 JSON 的摘要一致，不证明模型判断正确，也不是防篡改签名。旧记录不能追溯生成时内容；不会自动回填并声称已验证。正式审计还应保存不可改写的运行日志或签名，以及模型权重摘要。

前端对此对象展示“真实图像证据，Agent 分流未运行”。真实图像和 mask 可作为定位实验样例；当前不能由此得出项目四档处置建议，也不能声称 Agent 已对该图片完成风险分流。原始数据、模型文件和推理输出保持在 Git 忽略目录，服务仅监听 `127.0.0.1`。
