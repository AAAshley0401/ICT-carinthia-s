# MVTec AD 标注与四档严重度接入审计

审计日期：2026-10-14。数据位置：`D:\AAA-My-project\ICT\data\raw\mvtec_anomaly_detection`。

## 实际数据

| 项目 | 数量 / 格式 |
|---|---|
| 物体与纹理类别 | 15 类 |
| `train/good/*.png` | 3,629 张正常训练图像 |
| `test/good/*.png` | 467 张正常测试图像 |
| `test/<缺陷类型>/*.png` | 1,258 张异常测试图像 |
| `ground_truth/<缺陷类型>/*_mask.png` | 1,258 张像素级真值 mask |

标注保存在目录结构和 PNG mask 中，没有发现四档严重度标注文件。以 `bottle` 为例，测试目录为 `good`、`broken_large`、`broken_small`、`contamination`；`broken_large` / `broken_small` 是该物体的缺陷形态名称，不能直接解释为项目的 `Gross NG` / `Marginal NG`。其他类别也使用如 `scratch`、`crack`、`color` 等缺陷类型标签。这些标签可用于公开数据集的正常/异常评测和定位评测，不能据此声称已有晶圆四档等级。

## 对 Agent 契约的影响

| 字段 / 能力 | 当前 MVTec 数据可支持的事实 | 接入结论 |
|---|---|---|
| 异常存在 | 测试集 `good` 与缺陷目录提供二值标签 | 可做公开数据集的分数校准试验；不能外推晶圆 |
| 定位 | 异常图像有像素 mask | 可评估公开数据集定位；现有 PatchCore 也输出预测 mask |
| 缺陷类型 | 目录给出图像级类型 | 可作为实验标签，但不是模型预测或逐缺陷类别置信度 |
| 四档严重度 | 无 Acceptable / Marginal NG / NG / Gross NG 人工标签及业务准则 | **无法训练或评估四档模型，不得映射目录名或 mask 面积** |
| `severity_probabilities` | 无四档监督数据 | 不得生成看似真实的四档概率分布 |

因此，`model_output_contract_v1.draft.json` 仍是待确认草案，不能冻结为真实模型已实现的接口。当前前端保持 MVTec 证据视图的 `Agent NOT RUN`，本地模拟 Trace 与真实图像证据分开展示。MVTec AD 自带 `readme.txt` 声明 CC BY-NC-SA 4.0；比赛材料使用时保留数据集署名和来源。

## 真正完成四档接入所需输入

需取得目标晶圆/ICME 图像的获准使用位置、每个缺陷的人工四档标签、版本化业务判定准则，以及独立的训练、校准和评测划分。收到后按[四档标注协议](../contracts/severity_annotation_v1.md)整理，再训练和评估严重度分布，并按[真实模型接入门槛](../contracts/real_model_integration_gate_v1.md)核验后接入 ModelAdapter。
