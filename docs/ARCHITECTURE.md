# 设计与源码路线

## 端侧

`edge/jetson_client.py` 是完整独立客户端，适配旧 Python，与主机依赖隔离。
`capture` 通过 jetson-inference 的 detectNet/videoSource/cudaToNumpy 公开接口取得检测和 RGB 像素；没有嵌入上游实现。
每个检测包含 label、confidence 和原图像素 bbox。缩放 JPEG 后 bbox 仍对应原图，当前云侧仅使用标签/置信度规则，不将这些 bbox 画到缩放图。
未来增加可视化时，需一起发送原图宽高或按缩放比例变换坐标。

`EventGate.select` 根据超过阈值的标签计数构造签名；发生变化且超过冷却时间时上传，长期不变时按 heartbeat 上传。
它不能发现同类别目标的轨迹变化或外观变化，不能称为语义新颖性检测或目标跟踪。
仅在 Outbox.add 成功后 commit 触发状态，避免磁盘队列满时静默丢失触发状态。
后台线程执行 Outbox.flush，成功删除本地事件，临时错误按 1/2/4/.../60 秒重试；4xx（408/429 除外）进入 dead。

## 主机

`api.py` 校验输入 → `service.py:EventService.process` 设置总 deadline → JPEG 校验 → 事件锁与 SQLite 查询 → 并发闸门 → `backend.py:VLMBackend.ask`。
同一事件 ID 的并发上传只处理一次；payload 不同返回 409。完成后保存图像输入、检测元数据和输出。
追问通过存储的同一张图重新调用 VLM，逐次记录 question/answer；当前没有多轮对话历史拼接或 LangGraph 图编排。
`vision.py:scene_rules` 基于 person/car 等标签生成记录或人工复核建议，没有执行外部控制动作。

## 时延

edge_processing_ms 在采集线程同一单调时钟测量；cloud_queue_ms、vlm_ms、cloud_processing_ms 在主机同一单调时钟测量。
客户端记录请求 round_trip_ms。不同设备墙上时钟可能不同步，不能用 captured_at 与主机时刻相减当作准确单向传输时间。
`round_trip_ms - cloud_processing_ms` 至多是网络、序列化、HTTP 框架及其余等待的组合估计，不是纯单向带宽时延。
重放响应包含原始处理 timing，不是本次重放处理耗时，统计时根据 replayed 排除或独立分组。

## 失效与扩展

主机单进程/单 Uvicorn worker；成功事件持久化，图像随输入保存在 SQLite 中，需规划实验数据保留策略。
VLM 对网络、429、部分 5xx 重试；连续 3 次请求级失败后暂时拒绝 15 秒，再允许试探；这是简易计数熔断，不是分布式半开探针控制。
进程重启可能重新计算未提交结果的事件，不能声称 crash 场景严格 exactly-once。
目前无目标跟踪、标定、地图坐标、动作规划和车辆控制。需要实机标注数据才能评价场景描述质量。
