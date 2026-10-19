# Nano 独立客户端

`jetson_client.py` 仅要求 Python 3.6+ 标准库；capture 模式额外需要设备自带 jetson_inference、jetson_utils、NumPy、Pillow。
replay/flush/stats 不导入 Jetson 库，可在桌面测试。

```bash
python3 jetson_client.py capture --camera /dev/video0 --node-id nano-01   --url http://YOUR_HOST_IP:8000 --network ssd-mobilenet-v2   --width 640 --quality 75 --cooldown 5 --heartbeat 30
```

主机需监听设备可达的地址，如 `uvicorn rma.api:create_app --factory --host 0.0.0.0 --port 8000`。
使用鉴权时两侧设置相同的 API_KEY。默认单进程，outbox 只有一个上传线程；不要用多个进程同时 flush 同一个库。
待发送事件持久化，最大 pending 默认 500；满时跳过新触发且不更新触发状态。4xx 永久错误进入 dead，临时错误保留并退避。
dead 行需人工查看 SQLite 并修复错误后再处理，不能宣称自动死信恢复。outbox 不是任意大小视频缓存。
采集/检测与上传线程分离，但 SQLite 写入和图像压缩仍占用采集线程，需要实测 FPS 与磁盘容量。
Nano 不可用时保留客户端脚本并用 replay 验证协议，不能把 replay 写成已完成设备部署。
