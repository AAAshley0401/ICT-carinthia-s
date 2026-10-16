# Carinthia-S 数据与固定评估集

## 来源与许可

原始数据：Corinna Kofler、Vahidin Hasić，*Carinthia-S dataset* (2025)，[Zenodo DOI: 10.5281/zenodo.16895427](https://doi.org/10.5281/zenodo.16895427)，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。`data.zip` 是原始下载文件，未修改，MD5 为 `3a41242574635cf1302fab15accb7730`。本项目的清单、固定划分和二值掩码为派生处理；原始图片与原始掩码始终保留。

原始 ZIP 为 139,225,942 字节，超过 GitHub 普通 Git 的单文件上限。仓库将其无损拆为 5 个 `data.zip.part-*` 文件，每块均小于 50 MiB；`chunks.json` 记录每块与完整 ZIP 的 SHA-256。重组后的 ZIP 不入 Git。处理脚本需要 Python、NumPy 和 Pillow。

## 重建与校验

从仓库根目录运行：

```powershell
python tools/assemble_carinthia.py --parts-dir datasets/carinthia-s --output data/raw/carinthia-s/data.zip
python tools/prepare_carinthia.py --archive data/raw/carinthia-s/data.zip --output data/processed/carinthia-s
python eval/verify_carinthia.py --data data/processed/carinthia-s
```

`data/processed/carinthia-s/` 将生成 `images/`、`masks_original/`、`masks_binary/`、`manifest.csv`、`train.csv`、`val.csv`、`test.csv`、`audit.json`。图片路径在 CSV 中相对于此输出目录。仓库中的同名 CSV 和审计报告是本次冻结副本；`eval/split_lock.json` 记录源 ZIP 和清单的 SHA-256。

## 评估约定

共 4,591 张图，按原始 6 类标签和固定种子 `20261016` 分层，划分为训练 3,215、验证 688、测试 688。训练集用于拟合，验证集用于选择模型和阈值，测试集只用于最终报告。分类建议报告混淆矩阵、各类召回率及 Macro-F1；定位建议报告非空掩码 Dice/IoU 和空掩码误报率。

原始数据没有晶圆、批次或采集会话 ID，因此目前只能保证图像级划分。类别 2 和 5 在验证集和测试集各只有 1 张，单类结果需要标明样本量。第 6 类有一张原始掩码非空的样本 `8b782473c99742e394df74b430412232`，它位于测试集；在人工核对前，应在定位评估中单独列示，不视为普通空掩码样本。原始掩码中的非零灰度像素被转成二值掩码的 255，零像素保持 0。
