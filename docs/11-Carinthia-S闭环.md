# Carinthia-S 真实模型与人工复核闭环

## 范围

此流程针对公开的 Carinthia-S 数据：**缺陷二值定位 + 原始 1–6 类分类 → 人工复核分流 → 人工结论与事件留痕**。数据没有四档严重度标签，因此这里不输出 `Acceptable / Marginal NG / NG / Gross NG`，也不调用现有的四档严重度路由。当前是本地研究与演示流程；尚未接入 AgentArts 或身份认证，不执行产线处置。

## 从仓库重建并启动

在仓库根目录、已安装 `requirements-carinthia.txt` 所列依赖的环境中运行：

```powershell
python tools/assemble_carinthia.py --parts-dir datasets/carinthia-s --output data/raw/carinthia-s/data.zip
python tools/prepare_carinthia.py --archive data/raw/carinthia-s/data.zip --output data/processed/carinthia-s
python eval/verify_carinthia.py --data data/processed/carinthia-s
python -m src.carinthia_app --data data/processed/carinthia-s --checkpoint artifacts/carinthia-s/best.pt --db runs/carinthia-live/cases.sqlite3 --artifacts runs/carinthia-live
```

打开 `http://127.0.0.1:8766/carinthia`。输入 `manifest.csv` 中的图像 ID 即可创建检测案件。页面显示原图、预测掩码、六类分类分数、路由原因和事件摘要；待复核样本进入左侧队列。复核人可以确认类别、修正类别、标记无法确定或建议重新采图，并填写依据。提交后队列状态和事件链即时更新。

也可以调用本地 API：

| 方法与路径 | 用途 |
|---|---|
| `POST /api/carinthia/inspect` | `{"image_id":"..."}`，实际读图、预测、路由并保存案件 |
| `GET /api/carinthia/review-queue` | 待人工复核案件 |
| `GET /api/carinthia/cases/{case_id}` | 预测、路由、人工事件及哈希链 |
| `GET /api/carinthia/cases/{case_id}/image` | 校验 SHA-256 后返回原图 |
| `GET /api/carinthia/cases/{case_id}/mask` | 校验 SHA-256 后返回预测掩码 |
| `GET /api/carinthia/cases/{case_id}/preview-mask` | 校验原始掩码后返回红色透明预览图 |
| `POST /api/carinthia/cases/{case_id}/reviews` | 保存人工结论；可追加新结论，不覆盖旧事件 |

人工结论示例：

```json
{"reviewer":"质检员A","conclusion":"CORRECT_CLASS","final_label":"4","notes":"复核后判为第4类"}
```

## 模型与评估

`tools/train_carinthia.py` 用训练集拟合一个轻量多任务 U-Net，输入为 128×128 灰度图；分割头预测二值掩码，分类头预测 6 类。基线训练命令：

```powershell
python -m tools.train_carinthia --data data/processed/carinthia-s --output runs/carinthia-baseline-v1 --epochs 5 --batch-size 16 --size 128 --base 16
python -m eval.evaluate_carinthia_model --data data/processed/carinthia-s --checkpoint runs/carinthia-baseline-v1/best.pt --split test --output runs/carinthia-baseline-v1/test
```

本次权重选自第 3 轮验证集综合指标。留出测试集 688 张：分类 Macro-F1 **0.716**，非空掩码平均 Dice **0.895**、IoU **0.819**。第 2、5 类在测试集中各只有 1 张；第 5 类这张未识别。详见 `artifacts/carinthia-s/test_metrics.json`，不能把这些分数说成 ICME 四档严重度成绩，也不能推断跨晶圆或跨产线泛化。

路由规则只根据验证集选定：分类原始 softmax 分数 `<0.90`、预测少数类 `1/2/4/5`、第 3 类预测掩码占比 `>6%`，或类别与掩码是否存在相冲突时送人工。验证集送人工 91/688，覆盖 14/14 个分类错误；冻结规则在测试集送人工 93/688，覆盖 8/11 个分类错误。**仍有 3 个高分误判未被分流**，不能自动放行模型候选。原始 softmax 分数没有做概率校准。

## 留痕与限制

每个案件在 SQLite 中保存原图摘要、模型权重摘要、预测掩码摘要、模型输出、路由策略和原因。模型路由事件与每次人工复核事件按顺序追加，并以前一事件 SHA-256 串联；读取案件时重新校验链。该机制可发现普通的记录内容篡改，但数据库管理员仍可整体重写数据库，故不能称为不可篡改审计。页面中的复核人由本人填写，尚未验证身份。

原始数据没有晶圆或批次 ID，固定集只保证图像级互斥；极少样本类别的单类指标不稳定。AgentArts 云端调用、角色鉴权和实际业务四档严重度标注均为后续集成工作。
