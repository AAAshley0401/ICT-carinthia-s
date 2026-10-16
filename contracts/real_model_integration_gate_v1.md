# 真实模型接入门槛 v1

状态：**未通过**。本文件规定何时可以把真实图像推理送入现有 `ModelAdapter → Validation → Routing → Trace`，不改变现有路由规则，也不把 MVTec 基线包装成四档质检模型。

## 当前盘点

已对两个固定实验版本分别执行字段盘点：

```powershell
python algorithm/tools/audit_model_readiness.py outputs/experiments/bottle_q995_bound/json --output outputs/evaluation/model_readiness_bottle_q995_bound.json
python algorithm/tools/audit_model_readiness.py outputs/experiments/bottle_q999_bound/json --output outputs/evaluation/model_readiness_bottle_q999_bound.json
```

两份报告各有 83 条 `raw_anomaly_baseline`，83 条均记录了原图、预测 mask、checkpoint 摘要和预处理字段。它们有原始最近邻距离、预测 mask 与模型版本，但没有经校准的图像级缺陷概率、由模型预测的缺陷类别及其置信度、四档严重度分布、校准版本。因此两版均为 `agent_routing_enabled=false`，工作台仅展示 `Agent NOT RUN`。旧实验目录与 `outputs/json` 保留，但不作为这两份版本报告的输入。重新绑定只解决证据追溯，不改变接入门槛。

批量 manifest 审计结果：q=.995 为 `83/83 CONTENT_MATCH`，q=.999 为 `83/83 CONTENT_MATCH`。报告分别保存为 `outputs/evaluation/evidence_audit_bottle_q995_bound.json` 和 `outputs/evaluation/evidence_audit_bottle_q999_bound.json`。

此前 166 条记录未保存生成时的 checkpoint 摘要；现已重新推理到新的 `_bound` 目录，保留旧记录。服务端对新记录核对固定 checkpoint 文件的 SHA-256 与预处理标识。`model_version` 字符串仍不能单独证明权重身份，也不能代替模型质量评测。

`audit_model_readiness.py` 分别盘点原图与 mask 摘要字段、checkpoint 摘要与预处理字段；它不重算文件的 SHA-256。展示服务在读取时执行内容核对。即使未来记录符合 Agent JSON 形状，也仅报告 `agent_shape_unverified`；字段存在不能证明概率经过校准、严重度有效或图像证据绑定正确。报告不是模型性能评测。

## 公开数据概率校准试验

`python algorithm/tools/calibrate_bottle_probability.py outputs/evaluation/bottle-patchcore-style-resnet18-v1.json --output outputs/evaluation/bottle_probability_pilot_v1.json` 对保存的 MVTec bottle 原始分数按样本 ID 做确定性的分层划分：50 条用于拟合单调 Logistic 校准器，33 条留作评估。该次运行在保留集上得到 Brier `0.0152`、5 桶 ECE `0.0716`、AUROC `1.0`。报告保存原始评测文件摘要、样本 ID、拟合参数、保留集预测和局限说明，可复核划分。

这些指标只覆盖同一个公开数据集的 bottle 类别，校准和评估样本共享缺陷家族，样本量也小；不能外推到晶圆或 ICME，更不能代替四档严重度模型。试验输出使用 `estimated_anomaly_probability`，没有写入 Agent 的 `defect_probability`，`agent_routing_usable=false`。

## 接入验收

| 能力 | 必须提交的可核查材料 |
|---|---|
| 图像级缺陷概率 | 输出语义、独立校准集、校准版本、可靠性曲线或 Brier/ECE、独立评测集结果；原始异常距离不得直接映射为概率 |
| 定位与类别 | 每个缺陷的框或 mask、坐标系、类别标签、检测与类别分数语义；不得用数据集目录名代替模型预测类别 |
| 四档严重度 | `Acceptable / Marginal NG / NG / Gross NG` 的业务标注准则、带分歧处理的人工标注集、四档分布与独立评测结果；不能由 mask 面积直接臆造等级 |
| 证据绑定 | 原图、预测 mask、运行 ID、模型权重摘要、预处理版本、输出记录的关联；历史记录无摘要须继续标为未验证 |
| 版本与错误 | `model_version`、`calibration_version`、推理时间、失败与超时响应；映射到 `ModelPrediction`，再经 `ModelAdapter` 验证 |

当前 `ModelAdapter` 在适配层就拒绝 `image_analyzed=false` 或布尔元数据类型错误的 `ModelPrediction`，返回 `INVALID_MODEL_OUTPUT`；通过适配层仍需经过 `Validation → Routing`，不能把适配成功当作 Agent 接入通过。

可用 `python algorithm/tools/evaluate_agent_readiness.py <模型 readiness 报告> --annotation-report <标注审计报告> --model-evaluation-evidence <模型评测材料> --business-criteria-evidence <四档准则确认材料> --agentarts-evidence <平台权限材料> --output <门禁报告>` 盘点材料。文件材料只记录路径与 SHA-256，工具不会根据自填布尔字段认定业务批准或平台开通。模型输出必须至少具有 Agent 输入形状，且标注审计报告须有已裁决记录、无待标注或无效记录；这仍不能证明模型语义或性能合格。

资料缺失时报告为 `BLOCKED`；材料齐备时仅为 `PENDING_TECHNICAL_REVIEW`。两种状态下 `agent_routing_enabled` 均为 `false`。最终仍须人工审查校准、四档准则、独立评测、证据绑定和实际 AgentArts 权限；这份盘点报告不分配严重度、不评估模型质量，也不授予路由权限。

至少提供正常样本、单缺陷、多缺陷和推理失败的原生输出样例。先在保留集上确认分数与四档含义，再让接入层调用现有 `run_inspection(..., detector=ModelAdapter(backend))`。校准集和最终评测集分开；MVTec 公共数据上的实验不得称为 ICME 或晶圆实测成绩。接入后仍需人工确认，不能据此执行产线动作。

## 下一步实际工作

1. 明确目标数据与四档业务标注准则，收集对应人工标签；若 ICME 数据仍未到位，公开数据集实验仅作方法验证。
2. 在独立数据上训练和校准概率、类别与严重度模型，保存版本和评测证据。
3. 用真实原生输出实现 `ModelBackend`，通过本门槛后接入 Agent 与前端聚合对象；再审查路由阈值的适用性。
