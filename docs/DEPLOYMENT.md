# 设备与模型部署

## 先用当前 Windows 主机运行

Python 3.10+，执行 README 离线命令。Docker 可用 `docker compose up --build` 启动 mock 主机；本次未构建 Docker 镜像。
如需重现测试依赖，使用 `python -m pip install -c requirements.lock.txt -e ".[dev]"`。
部署时保持单个主机 worker。`.env.example` 不自动读取；用当前 shell 设置变量。

## RTX 8GB 模型候选

路线 A：独立 Linux/WSL2 vLLM 环境运行 `bash deploy/serve_vlm_vllm.sh`，模型候选 Qwen/Qwen3-VL-2B-Instruct。
小型权重并不保证 8GB 一定够用，视觉编码器、KV cache 和临时缓冲也占显存；脚本使用单并发、短 context/eager 起步，需实测。
真实接口通过图文 messages 发送 JPEG data URL，模型服务的 served-model-name 为 local-vlm。
先确认 `/v1/models`，再设置 BACKEND=openai、VLM_BASE_URL、VLM_MODEL=local-vlm。

路线 B：根据 [llama.cpp 官方多模态文档](https://github.com/ggml-org/llama.cpp/blob/master/docs/multimodal.md) 编译/安装支持 libmtmd 的 llama-server，
运行 `bash deploy/serve_llamacpp.sh`。默认是官方列出的 SmolVLM-500M GGUF 模型候选，-hf 会联网取得模型和视觉 projector。
它用作低资源替代，不等价于 Qwen3-VL，也不保证中文道路描述质量。

本次没有下载 VLM 或执行 GPU 推理，两个后端通过本地 HTTP 协议 fixture 验证序列化/错误处理。
使用同一张 8GB 显卡时，项目一和项目二的大模型服务优先分开启动，避免并行驻留导致 OOM；性能比较保留各自版本与启动参数。

## 以后接入 Nano

按 [jetson-inference 官方部署说明](https://github.com/dusty-nv/jetson-inference) 选择与设备 JetPack 兼容的版本/构建环境。
不要把 Orin 的新 JetPack 环境或 RK3576/RKLLM 产物直接用于原始 Nano。
先运行上游 detectNet 摄像头示例，确认相机格式与网络可用，再复制 `edge/jetson_client.py`。
设备只需自有运行时、NumPy/Pillow 和标准库，不安装本仓库现代 FastAPI/Pydantic 主机依赖。
运行方式见 `edge/README.md`。固定设备/JetPack/模型版本后，采集真实 FPS、RAM、重连和事件上传记录。

树莓派目前可以作为协议回放节点；本项目未提供其真实视觉 detector 部署，不应声称已完成树莓派视觉模型推理。
若需要树莓派 ONNX 推理，可使用第三个项目的 ONNX worker，前提是系统和 Python 满足对应 wheel 支持要求。
