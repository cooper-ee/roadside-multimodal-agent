# API

| 方法 / 路径 | 功能 |
|---|---|
| GET /health | 主机进程状态与配置后端；不检测模型实际健康 |
| GET /metrics | 接收、去重、处理、错误累计数 |
| POST /v1/events | 上传一次图像/检测/问题事件 |
| GET /v1/events/{event_id} | 读取已处理的事件输出 |
| POST /v1/events/{event_id}/questions | 针对存储图像追问 |

```json
{"event_id":"e-001","node_id":"nano-01","captured_at":0.0,"detections":[{"label":"car","confidence":0.9}],"question":"描述可见车辆","edge_processing_ms":12.3}
```

真实 VLM 模式必须增加 image_b64，值为 JPEG 原始字节的 base64（不含 data: 前缀）。
JPEG 最多 2MB、最长边 2048px、最多 300 万像素；默认发送 640px/quality75。
字段与长度限制见 `/docs`。bbox 可选，当前不用于云侧几何判断。

追问体：`{"question":"图中有哪些可见目标？"}`。
设置 API_KEY 后，业务请求要求 Authorization: Bearer；/health 不鉴权。
401 鉴权，404 事件不存在，409 ID 冲突，422 参数/图像错误，502 后端失败，503 熔断，504 deadline。
检测元数据没有图像时可以在 mock 下测试，但输出明确标注没有进行视觉识别。
运行 `python examples/client.py` 或 edge replay 验证完整输入与追问。
