# 真实模型接入门槛 v1

状态：**未通过**。本文件规定何时可以把真实图像推理送入现有 `ModelAdapter → Validation → Routing → Trace`，不改变现有路由规则，也不把 MVTec 基线包装成四档质检模型。

## 当前盘点

执行 `python -m tools.audit_model_readiness outputs/json --output outputs/evaluation/model_readiness_v1.json`。当前 `outputs/json` 中 83 条保存记录全部为 `raw_anomaly_baseline`。它们有原始最近邻距离、预测 mask、模型版本；部分新记录可能有图像和 mask 摘要。它们没有经校准的图像级缺陷概率、由模型预测的缺陷类别及其置信度、四档严重度分布、校准版本。因此 `agent_routing_enabled=false`，工作台仅展示 `Agent NOT RUN`。

`audit_model_readiness.py` 只盘点字段。即使未来记录符合 Agent JSON 形状，也仅报告 `agent_shape_unverified`；字段存在不能证明概率经过校准、严重度有效或图像证据绑定正确。报告不是模型性能评测。

## 公开数据概率校准试验

`python -m tools.calibrate_bottle_probability outputs/evaluation/bottle-patchcore-style-resnet18-v1.json --output outputs/evaluation/bottle_probability_pilot_v1.json` 对保存的 MVTec bottle 原始分数按样本 ID 做确定性的分层划分：50 条用于拟合单调 Logistic 校准器，33 条留作评估。该次运行在保留集上得到 Brier `0.0152`、5 桶 ECE `0.0716`、AUROC `1.0`。报告保存原始评测文件摘要、样本 ID、拟合参数、保留集预测和局限说明，可复核划分。

这些指标只覆盖同一个公开数据集的 bottle 类别，校准和评估样本共享缺陷家族，样本量也小；不能外推到晶圆或 ICME，更不能代替四档严重度模型。试验输出使用 `estimated_anomaly_probability`，没有写入 Agent 的 `defect_probability`，`agent_routing_usable=false`。

## 接入验收

| 能力 | 必须提交的可核查材料 |
|---|---|
| 图像级缺陷概率 | 输出语义、独立校准集、校准版本、可靠性曲线或 Brier/ECE、独立评测集结果；原始异常距离不得直接映射为概率 |
| 定位与类别 | 每个缺陷的框或 mask、坐标系、类别标签、检测与类别分数语义；不得用数据集目录名代替模型预测类别 |
| 四档严重度 | `Acceptable / Marginal NG / NG / Gross NG` 的业务标注准则、带分歧处理的人工标注集、四档分布与独立评测结果；不能由 mask 面积直接臆造等级 |
| 证据绑定 | 原图、预测 mask、运行 ID、模型权重摘要、预处理版本、输出记录的关联；历史记录无摘要须继续标为未验证 |
| 版本与错误 | `model_version`、`calibration_version`、推理时间、失败与超时响应；映射到 `ModelPrediction`，再经 `ModelAdapter` 验证 |

至少提供正常样本、单缺陷、多缺陷和推理失败的原生输出样例。先在保留集上确认分数与四档含义，再让接入层调用现有 `run_inspection(..., detector=ModelAdapter(backend))`。校准集和最终评测集分开；MVTec 公共数据上的实验不得称为 ICME 或晶圆实测成绩。接入后仍需人工确认，不能据此执行产线动作。

## 下一步实际工作

1. 明确目标数据与四档业务标注准则，收集对应人工标签；若 ICME 数据仍未到位，公开数据集实验仅作方法验证。
2. 在独立数据上训练和校准概率、类别与严重度模型，保存版本和评测证据。
3. 用真实原生输出实现 `ModelBackend`，通过本门槛后接入 Agent 与前端聚合对象；再审查路由阈值的适用性。
