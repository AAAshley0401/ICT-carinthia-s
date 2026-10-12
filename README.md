# 明察 DefectLens

华为 ICT 大赛创新赛赛题二的晶圆显微缺陷质检项目。目标是定位缺陷、划分四档严重度，并在 AgentArts 上完成分拣、检测、仲裁流程。项目目前处于方案与原型阶段；ICME 数据集已申请，实验结果待实测。

## 仓库结构

| 路径 | 用途 |
|---|---|
| [`docs/`](docs/) | 项目文档、起跑清单、方案存档及获奖项目调研 |
| `docs/competition/` | 本地赛事通知与报名表附件，不纳入 Git |
| [`prototype/`](prototype/) | 可直接用浏览器打开的界面示意 |
| `src/` | 后续放检测与分级模型代码 |
| [`agentarts/`](agentarts/) | AgentArts 工具接口约定与接入步骤 |
| `eval/` | 后续放指标计算与消融记录脚本 |
| `data/raw/` | 本地原始数据，只读保存，不纳入 Git |
| `data/processed/` | 本地预处理数据，不纳入 Git |
| `runs/` | 本地训练输出与实验记录，不纳入 Git |

从[项目文档](docs/项目文档-明察DefectLens.md)了解完整方案，从[起跑清单](docs/起跑清单-明察DefectLens.md)了解当前分工。界面示意位于[prototype/明察-DefectLens.html](prototype/明察-DefectLens.html)。

等待数据期间可先用 `python src/mock_inference_server.py` 启动本地模拟接口；它不读取图片，也不产生实测结果。接入说明见[agentarts/README.md](agentarts/README.md)。

## 当前状态

- ICME 数据集已申请，等待回复；尚无同条件实测成绩。
- `docs/项目文档-明察DefectLens.md` 中的 `figs/` 插图引用来自原稿，图片文件目前不在仓库中。
- 原始数据、赛事附件、模型权重和训练输出保存在本地忽略目录；提交代码前先检查 `git status`。
