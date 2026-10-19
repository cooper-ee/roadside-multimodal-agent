import asyncio
import base64
from dataclasses import replace
import importlib.util
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from rma.api import create_app
from rma.backend import VLMBackend, CircuitOpenError
from rma.config import Settings
from rma.schema import Event
from rma.service import EventService, ConflictError
from rma.vision import synthetic_frame, compress, validate_image

spec = importlib.util.spec_from_file_location('jetson_client', Path(__file__).parents[1] / 'edge/jetson_client.py')
edge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(edge)


def event(**kwargs):
    return Event(event_id='e1', node_id='test', captured_at=0, detections=[{'label': 'person', 'confidence': .8}],
                 image_b64=base64.b64encode(compress(synthetic_frame())).decode(), **kwargs)


def test_event_dedup_conflict_and_restart(tmp_path):
    config = Settings(database=str(tmp_path / 'db.sqlite'))
    service = EventService(config)
    async def run():
        a, b = await asyncio.gather(service.process(event()), service.process(event()))
        assert a['answer'] == b['answer']
        assert service.counters['processed'] == 1
        assert service.counters['replayed'] == 1
        assert a['rules']['priority'] == 'review'
        assert '[MOCK' in a['answer']
        assert not service.locks
        with pytest.raises(ConflictError):
            await service.process(event(question='different'))
        assert (await EventService(config).process(event()))['replayed']
        assert 'MOCK' in (await service.question('e1', '有哪些目标？'))['answer']
    asyncio.run(run())


def test_gate_and_outbox_retry_persistence(tmp_path):
    gate = edge.EventGate(cooldown_s=5, heartbeat_s=30)
    car = [{'label': 'car', 'confidence': .9}]
    assert gate.select(car, 0)
    gate.commit(car, 0)
    assert not gate.select(car, 6)
    assert not gate.select([], 4)
    assert gate.select([], 5)
    assert gate.select(car, 30)
    path = str(tmp_path / 'outbox.sqlite')
    outbox = edge.Outbox(path, max_pending=1)
    outbox.add(event().model_dump())
    with pytest.raises(OverflowError):
        outbox.add({**event().model_dump(), 'event_id': 'e2'})
    def fail(payload):
        raise OSError('offline')
    assert outbox.flush(fail, now=0) == 0
    assert edge.Outbox(path).stats() == {'pending': 1}
    assert outbox.flush(lambda payload: None, now=.5) == 0
    assert outbox.flush(lambda payload: None, now=1) == 1
    assert outbox.stats() == {}


def test_image_and_api_validation(tmp_path):
    assert validate_image(event().image_b64)
    with pytest.raises(ValueError):
        validate_image('not base64')
    with TestClient(create_app(Settings(database=str(tmp_path / 'api.sqlite'), api_key='test'))) as client:
        payload = event().model_dump()
        assert client.post('/v1/events', json=payload).status_code == 401
        headers = {'Authorization': 'Bearer test'}
        assert client.post('/v1/events', json=payload, headers=headers).status_code == 200
        payload['image_b64'] = base64.b64encode(b'bad-image').decode()
        assert client.post('/v1/events', json=payload, headers=headers).status_code == 422
        assert client.get('/v1/events/missing', headers=headers).status_code == 404


def test_real_vlm_contract_and_circuit(tmp_path):
    seen = []
    def handler(request):
        import json
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Visible objects'}}]})
    config = Settings(backend='openai', circuit_failures=1)
    backend = VLMBackend(config, httpx.MockTransport(handler))
    assert asyncio.run(backend.ask(event(), 'q')) == 'Visible objects'
    assert seen[0]['messages'][1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    broken = VLMBackend(config, httpx.MockTransport(lambda request: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(broken.ask(event(), 'q'))
    with pytest.raises(CircuitOpenError):
        asyncio.run(broken.ask(event(), 'q'))


def test_cloud_deadline(tmp_path):
    class Slow:
        async def ask(self, event, question):
            await asyncio.sleep(.1)
    service = EventService(Settings(database=str(tmp_path / 'timeout.sqlite'), timeout_s=.02), Slow())
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(service.process(event()))
