# 毫芒 Hairline

华为 ICT 大赛创新赛赛题二项目：在晶圆显微图中定位缺陷、判定四档严重度，并通过 AgentArts 完成检测、分流与人工复核建议。**ICME 数据已申请，当前没有本项目实测成绩。**

## 从这里开始

| 文件 | 读什么 |
|---|---|
| [01-项目概览](docs/01-项目概览.md) | 目标、范围、比赛口径、风险 |
| [02-技术方案](docs/02-技术方案.md) | 架构、接口、算法和评测约定 |
| [03-任务计划](docs/03-任务计划.md) | 三人分工、当前并行事项 |
| [04-参赛材料](docs/04-参赛材料.md) | 材料结构与证据清单 |
| [Agent 工作流程图](docs/05-Agent工作流程图.md) | 检测、分拣、仲裁及人工复核路径 |
| [Agent 详细设计](docs/06-Agent详细设计.md) | 角色权限、状态机、知识库与人机协同 |
| [前端工作台设计](docs/07-AGENT前端页面设计方案.md) | 可解释决策工作台的 MVP 范围与展示边界 |
| [Demo 数据协议 v1](contracts/demo_view_contract_v1.md) | 前端聚合 JSON、模拟来源与预览/验证路径 |
| [真实图像证据协议](contracts/baseline_evidence_v1.md) | MVTec bottle 原图、预测 mask 与原始异常分数绑定 |
| [算法证据清单审计工具](algorithm/tools/audit_evidence_manifests.py) | 批量核对原图、mask、checkpoint 摘要和预处理标识 |
| [算法接入材料盘点工具](algorithm/tools/evaluate_agent_readiness.py) | 汇总模型、四档标注和 AgentArts 材料；齐备时仅进入人工技术审查，路由始终关闭 |
| [真实模型接入门槛](contracts/real_model_integration_gate_v1.md) | 当前能力盘点、模型评测材料及进入 Agent 路由的条件 |
| [四档标注协议](contracts/severity_annotation_v1.md) | 晶圆严重度标签格式、人工裁决要求及只读标注核验工具；准则和标签仍待提供 |
| [MVTec 数据标注审计](docs/08-MVTec数据标注审计.md) | 已下载数据的样本数、标注形式与四档接入结论 |
| [MVTec 定位误差分析](docs/09-MVTec定位误差分析.md) | 两个正常训练阈值的定位权衡与失败样本 |
| [三分钟工作台演示脚本](docs/11-三分钟工作台演示脚本.md) | 按证据冲突、人工复核与真实图像证据讲解当前能力和边界 |
| [参赛进度基线](docs/12-项目进度基线.md) | 38% 阶段估算、模块缺口和下一阶段验收物 |
| [AgentArts 接入路线](docs/10-AgentArts接入路线.md) | 公测通过后的平台操作步骤、限额与验收标志 |

## 目录

- `src/`：Agent、校验、路由、模型适配和 Trace 代码。
- `algorithm/`：算法实验、数据检查、推理、评估、审计和算法样例；不直接承担 Agent 路由。
- `agentarts/`：平台接入说明；接口示例见 [agentarts/README.md](agentarts/README.md)。
- `eval/`：预留的通用评测目录；当前 MVTec 实验入口位于 `algorithm/tools/`。
- `prototype/`：可直接在浏览器打开的 Agent 决策工作台 MVP；入口见 [prototype/index.html](prototype/index.html)。
- `data/`、`runs/`：本地数据和实验输出，均被 Git 忽略。
- `docs/competition/`：本地赛事附件，均被 Git 忽略。

本地模拟服务可用 `python src/mock_inference_server.py` 启动；返回值只用于接入演示，不能作为模型成绩。

前端与本地 Agent 流程联调可运行 `python workspace_server.py`，再打开 `http://127.0.0.1:8765/`；接口只包装现有本地工作流，仍不分析图片。
同一页面也可查看已保存的 MVTec bottle 真实推理图像与预测 mask；当前页面读取带 checkpoint 摘要的 `outputs/experiments/bottle_q995_bound` 和 `bottle_q999_bound`，支持同一样本双版本对照。该基线只有原始异常距离，没有四档严重度，页面不会为它生成 Agent 分流结论。
后续新推理记录包含运行 ID 与图像、mask 的 SHA-256；展示服务会核对摘要，旧记录则明确标为未做内容校验。

当前绑定证据可复核：

```powershell
python algorithm/tools/audit_evidence_manifests.py outputs/experiments/bottle_q995_bound data/raw/mvtec_anomaly_detection/bottle models/bottle_patchcore_v1.pt --output outputs/evaluation/evidence_audit_bottle_q995_bound.json
python algorithm/tools/audit_evidence_manifests.py outputs/experiments/bottle_q999_bound data/raw/mvtec_anomaly_detection/bottle models/bottle_maskq999_v2.pt --output outputs/evaluation/evidence_audit_bottle_q999_bound.json
```

两份审计报告当前均为 `83/83 CONTENT_MATCH`；这只证明证据文件关联完整，不代表四档严重度模型或 Agent 路由已经通过接入门槛。

早期方案和调研材料已从当前目录收敛，仍可在 Git 历史中查阅。
