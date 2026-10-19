import asyncio
import json
import time
import httpx


class CircuitOpenError(RuntimeError):
    pass


class VLMBackend:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport
        self.failures = 0
        self.open_until = 0.0

    async def ask(self, event, question):
        if self.settings.backend == 'mock':
            labels = ', '.join(x.label for x in event.detections) or '无检测元数据'
            return '[MOCK/协议演示，未识别图像] 输入检测标签：' + labels + '。问题：' + question
        if not event.image_b64:
            raise ValueError('real VLM mode requires an image')
        if time.monotonic() < self.open_until:
            raise CircuitOpenError('VLM circuit temporarily open')
        content = [
            {'type': 'text', 'text': '道路场景研究。检测元数据仅供参考：' + json.dumps([d.model_dump() for d in event.detections], ensure_ascii=False) + '\n问题：' + question},
            {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + event.image_b64}},
        ]
        payload = {'model': self.settings.model, 'temperature': 0, 'max_tokens': 256,
                   'messages': [{'role': 'system', 'content': '描述可见事实与不确定性。不要声称能判断碰撞风险或控制车辆。'}, {'role': 'user', 'content': content}]}
        headers = {'Authorization': 'Bearer ' + self.settings.backend_key} if self.settings.backend_key else {}
        try:
            async with httpx.AsyncClient(base_url=self.settings.base_url + '/', headers=headers,
                                         timeout=self.settings.timeout_s, transport=self.transport) as client:
                for attempt in range(2):
                    try:
                        response = await client.post('chat/completions', json=payload)
                        response.raise_for_status()
                        answer = response.json()['choices'][0]['message']['content']
                        if not isinstance(answer, str) or not answer.strip():
                            raise ValueError('VLM returned empty content')
                        self.failures = 0
                        self.open_until = 0
                        return answer
                    except (httpx.NetworkError, httpx.TimeoutException, httpx.HTTPStatusError) as error:
                        if isinstance(error, httpx.HTTPStatusError) and error.response.status_code not in {429, 500, 502, 503, 504}:
                            raise
                        if attempt:
                            raise
                        await asyncio.sleep(.15)
        except Exception:
            self.failures += 1
            if self.failures >= self.settings.circuit_failures:
                self.open_until = time.monotonic() + self.settings.circuit_reset_s
            raise
