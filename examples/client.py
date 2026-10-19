import json
import os
import httpx
from rma.cli import make_events
from rma.vision import synthetic_frame

headers = {'Authorization': 'Bearer ' + os.environ['API_KEY']} if os.getenv('API_KEY') else {}
with httpx.Client(timeout=45, headers=headers) as client:
    payload = make_events(synthetic_frame())[0]
    result = client.post('http://127.0.0.1:8000/v1/events', json=payload)
    result.raise_for_status()
    print(json.dumps(result.json(), ensure_ascii=False, indent=2))
    question = client.post('http://127.0.0.1:8000/v1/events/' + payload['event_id'] + '/questions', json={'question': '请区分事实与推测。'})
    question.raise_for_status()
    print(json.dumps(question.json(), ensure_ascii=False, indent=2))
