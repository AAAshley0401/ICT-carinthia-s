# 四档严重度人工标注协议 v1

此协议用于准备真实模型所需的人工标签，字段结构见 [JSON Schema](severity_annotation_v1.schema.json)。**目前没有项目认可的四档判定准则和晶圆标注集；此协议不定义各档阈值，也不生成等级。**

每张图片先创建 `PENDING` 记录：`image_label=null`、`defects=[]`、`grade_standard_version=null`、`reviewer_ids=[]`。`PENDING` 与 `NORMAL` 含义不同，训练和评测必须排除 `PENDING`。

拿到获准使用的晶圆图片后，可运行 `python -m tools.prepare_wafer_annotation_queue <图片目录> <标注目录> --dataset-name <数据集名>` 生成待标注 JSON。工具只读取图片尺寸和 SHA-256，不调用模型、不推断标签，已有 JSON 不会覆盖。`image_ref` 是相对图片目录的路径；保留数据集根目录与标注目录的关联，后续用摘要复核实际图片。

完成两人复核及分歧裁决后，标记 `ADJUDICATED`，填写准则版本和两名以上复核者代号。`NORMAL` 必须没有缺陷项；`DEFECT` 至少有一项。每个缺陷记录类别、基于原图像素的 `bbox_xyxy`、可选 mask 引用和四档严重度。标注导入程序还应检查框在图像范围内、`x1<x2`、`y1<y2`、缺陷 ID 不重复，以及图片 SHA-256 与实际文件一致；JSON Schema 只处理结构，不能验证这些跨字段条件。

正式标注前须由项目业务负责人确认四档准则，包括尺寸/长度、位置、功能影响和边界样本的处理。无法按准则裁定的样本继续待裁决，不强行归档。数据集划分应在同一晶圆或批次层面隔离训练、校准和最终评测，避免相邻视野泄漏。标注者不查看模型预测分数，以免反向影响标签。

MVTec 的 `good` / `broken_large` 等目录名只表示公开数据集类别，不能代替本项目四档严重度标签。现有 MVTec mask 可以用于定位方法实验，但不能由 mask 面积自动赋四档等级。
