# AgentArts 接入起点

数据集尚未到手时，先打通 AgentArts 调用自定义工具的链路。本目录先记录工具协议；真实模型服务就绪后，保留同一个接口，替换模拟实现。

## 接口约定 v0

`POST /v1/inspect`，请求头 `Content-Type: application/json`：

```json
{
  "sample_id": "W-0304",
  "image_url": "https://example.invalid/wafer.png"
}
```

`sample_id` 可省略；`image_url` 必填。响应示例：

```json
{
  "sample_id": "W-0304",
  "mode": "mock",
  "demo_only": true,
  "image_analyzed": false,
  "image_size": {"width": 1024, "height": 1024},
  "grade": "Marginal NG",
  "confidence": 0.63,
  "defects": [
    {
      "category": "scratch",
      "confidence": 0.81,
      "bbox_xyxy": [320, 390, 500, 470],
      "severity": "Marginal NG"
    }
  ],
  "message": "模拟结果：未读取或分析图片，不得作为实测成绩。"
}
```

`bbox_xyxy` 是基于 `image_size` 的像素坐标，顺序为左、上、右、下。真实模型可以增加掩码字段，但应保留现有字段。模拟服务对 `W-0301`、`W-0304`、`W-0307`、`W-0312` 使用固定样例，其余输入根据 `sample_id`（缺省时根据 URL）稳定选择一组固定结果，**完全不读取图片**；档位不由图片决定。

## 本地启动

在仓库根目录运行：

```powershell
python src/mock_inference_server.py
```

服务默认监听 `127.0.0.1:8000`。健康检查为 `GET /health`。云端 AgentArts 无法直接访问本机的 `127.0.0.1`；接入自定义插件时，需把接口部署到平台可访问的地址，并按平台要求配置 HTTPS、鉴权和请求参数。

## 先完成的闭环

1. 确认 AgentArts 账号与自定义插件权限，在调试界面创建最小智能体。
2. 把上述请求和响应字段配置为工具，调用一次模拟服务，保存调用 Trace 截图。
3. 在 AgentArts 内分别配置检测、分拣、仲裁的输入、动作和输出。检测先调用 `/v1/inspect` 取得置信度；分拣根据置信度决定是否转人工；仲裁处理边界档与低置信度结果。阈值先作为演示配置，不声称已校准。
4. 真实模型可用后，将 `mode` 改为 `model`、`demo_only` 改为 `false`、`image_analyzed` 改为 `true`，由模型填充结果。此时再做指标评测；模拟结果绝不进入评测表。

AgentArts 的实际插件导入格式、权限和公网接入方式，需以开通后的平台页面为准。
