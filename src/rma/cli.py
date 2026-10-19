import argparse
import asyncio
import base64
import csv
import json
from pathlib import Path
import time
import uuid
from PIL import Image
from .config import Settings
from .schema import Event
from .service import EventService
from .vision import compress, synthetic_frame


def make_events(image):
    encoded = base64.b64encode(compress(image)).decode()
    return [Event(event_id='fixture-' + str(uuid.uuid4()), node_id='offline-fixture', captured_at=time.time(),
                  image_b64=encoded, detections=[{'label': 'car', 'confidence': .9}]).model_dump()]


def compression_benchmark(image, output):
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for width in [320, 640, 960]:
        for quality in [40, 65, 85]:
            start = time.perf_counter()
            encoded = compress(image, width, quality)
            duration_ms = (time.perf_counter() - start) * 1000
            filename = 'w%d-q%d.jpg' % (width, quality)
            (output / filename).write_bytes(encoded)
            rows.append({'width_limit': width, 'quality': quality, 'jpeg_bytes': len(encoded),
                         'base64_bytes': len(base64.b64encode(encoded)), 'encode_ms': duration_ms, 'file': filename})
    with (output / 'compression.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / 'metadata.json').write_text(json.dumps({'image_size': image.size, 'source': 'user image or explicitly synthetic fixture',
                                                     'quality_assessment': 'not measured; bytes and encoding time only'}, indent=2), encoding='utf-8')
    return rows


def main():
    parser = argparse.ArgumentParser(description='Roadside edge-cloud multimodal prototype')
    sub = parser.add_subparsers(dest='command', required=True)
    demo = sub.add_parser('demo')
    demo.add_argument('--output', type=Path, default=Path('artifacts/demo'))
    fixture = sub.add_parser('fixtures')
    fixture.add_argument('--output', type=Path, default=Path('artifacts/events.json'))
    bench = sub.add_parser('compression')
    bench.add_argument('--image', type=Path)
    bench.add_argument('--output', type=Path, default=Path('artifacts/compression'))
    sub.add_parser('serve')
    args = parser.parse_args()
    if args.command == 'serve':
        import uvicorn
        uvicorn.run('rma.api:create_app', factory=True, host='127.0.0.1', port=8000)
    elif args.command == 'compression':
        image = Image.open(args.image).convert('RGB') if args.image else synthetic_frame()
        print(json.dumps(compression_benchmark(image, args.output), ensure_ascii=False, indent=2))
    elif args.command == 'fixtures':
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(make_events(synthetic_frame()), indent=2), encoding='utf-8')
        print(str(args.output))
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        image = synthetic_frame()
        image.save(args.output / 'synthetic-road.jpg')
        event = Event.model_validate(make_events(image)[0])
        service = EventService(Settings.from_env())
        async def run():
            return {'first': await service.process(event), 'replay': await service.process(event),
                    'qa': await service.question(event.event_id, '图中有哪些车辆？')}
        result = asyncio.run(run())
        (args.output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
