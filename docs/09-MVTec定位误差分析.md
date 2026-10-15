# MVTec bottle 定位误差分析

日期：2026-10-14。使用同一 PatchCore-style ResNet18 特征记忆，对 MVTec AD `bottle/test` 完整划分重新推理。两个 checkpoint 的 memory tensor 与图像阈值相同，仅像素阈值不同：v1 为正常训练校准像素的 0.995 分位，v2 为 0.999 分位。阈值由正常训练图像得出；测试 mask 只用于事后评估，不参与阈值拟合。

| 指标 | v1，q=0.995 | v2，q=0.999 |
|---|---:|---:|
| 像素阈值，原始距离 | 1.4898 | 1.6694 |
| 63 张异常图平均 IoU | 0.3791 | 0.4509 |
| 63 张异常图平均像素召回 | 0.9842 | 0.9548 |
| 20 张正常图的预测阳性像素比例 | 0.00580 | 0.00098 |
| `broken_small` 平均 IoU | 0.2909 | 0.3687 |
| `contamination` 平均像素召回 | 0.9600 | 0.8837 |

更严格的阈值减少了明显的过度分割，平均 IoU 增加约 0.072；同时 `contamination` 的召回下降，不能只按 IoU 宣称全面改进。最差样本 `bottle_contamination_018` 的真值仅 375 像素，v1 预测 6,480 像素、IoU 0.058；v2 仍预测 4,837 像素、IoU 0.078。模型能发现异常，但范围不够精确。

对照图保存在 `outputs/figures/bottle_contamination_018_comparison.png`：原图、真值、q=.995 预测、q=.999 预测。真值仅供离线评测，不会进入推理工作台或 Agent 输入。图由 [`tools/render_localization_comparison.py`](../tools/render_localization_comparison.py) 从原图和两个 checkpoint 重新生成，输出时记录原图、真值和 checkpoint 的 SHA-256。

可复算脚本为 [`tools/evaluate_localization_failures.py`](../tools/evaluate_localization_failures.py)，完整逐样本报告位于 Git 忽略的 `outputs/evaluation/bottle_localization_failures_v1.json` 与 `outputs/evaluation/bottle_localization_failures_q999_v2.json`。脚本直接从冻结 checkpoint、原图和真值 mask 重新计算，不依赖可能被后续运行覆盖的 `outputs/masks`。v1 平均 IoU 与已有完整评测报告一致。

这些结果只说明公开 bottle 数据上的定位表现。比较结果属于探索性分析，不应反复使用官方测试集选择最终阈值；下一轮如需定型，应在独立验证集上确定阈值后再做一次锁定评估。像素 mask 也不提供四档严重度标签，因此本结果不进入 Agent 路由。
