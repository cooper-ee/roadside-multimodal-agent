#!/usr/bin/env python3
"""Standalone Python 3.6+ Jetson client. No cloud-package dependency.

Uses public jetson-inference APIs; upstream implementation is not embedded.
"""
import argparse
import base64
import io
import json
import os
import sqlite3
import threading
import time
import uuid
import urllib.error
import urllib.request


class EventGate:
    def __init__(self, cooldown_s=5.0, heartbeat_s=30.0, threshold=0.5):
        if cooldown_s < 0 or heartbeat_s <= 0 or not 0 <= threshold <= 1:
            raise ValueError('Invalid gate configuration')
        self.cooldown_s = cooldown_s
        self.heartbeat_s = heartbeat_s
        self.threshold = threshold
        self.last_time = float('-inf')
        self.signature = None

    def select(self, detections, now):
        counts = {}
        for item in detections:
            if item['confidence'] >= self.threshold:
                label = item['label']
                counts[label] = counts.get(label, 0) + 1
        signature = tuple(sorted(counts.items()))
        elapsed = now - self.last_time
        # Selection is side-effect free; commit only after a successful enqueue.
        return elapsed >= self.heartbeat_s or (signature != self.signature and elapsed >= self.cooldown_s)

    def commit(self, detections, now):
        counts = {}
        for item in detections:
            if item['confidence'] >= self.threshold:
                counts[item['label']] = counts.get(item['label'], 0) + 1
        self.signature = tuple(sorted(counts.items()))
        self.last_time = now


class Outbox:
    def __init__(self, path, max_pending=500):
        self.path = path
        self.max_pending = max_pending
        folder = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS outbox(id TEXT PRIMARY KEY, payload TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_at REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending', error TEXT);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def add(self, payload):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM outbox WHERE id=?', (payload['event_id'],)).fetchone():
                return
            if db.execute("SELECT COUNT(*) FROM outbox WHERE status='pending'").fetchone()[0] >= self.max_pending:
                raise OverflowError('outbox full; new frame skipped')
            db.execute('INSERT INTO outbox(id,payload) VALUES (?,?)', (payload['event_id'], json.dumps(payload, ensure_ascii=False)))

    def flush(self, send, now=None, limit=8):
        now = time.time() if now is None else now
        with self.connect() as db:
            rows = db.execute("SELECT id,payload,attempts FROM outbox WHERE status='pending' AND next_at<=? ORDER BY rowid LIMIT ?", (now, limit)).fetchall()
        delivered = 0
        for event_id, encoded, attempts in rows:
            try:
                send(json.loads(encoded))
                with self.connect() as db:
                    db.execute('DELETE FROM outbox WHERE id=?', (event_id,))
                delivered += 1
            except Exception as error:
                permanent = isinstance(error, urllib.error.HTTPError) and 400 <= error.code < 500 and error.code not in (408, 429)
                with self.connect() as db:
                    db.execute('UPDATE outbox SET attempts=?,next_at=?,status=?,error=? WHERE id=?',
                               (attempts + 1, now + min(60, 2 ** min(attempts, 6)), 'dead' if permanent else 'pending', type(error).__name__, event_id))
        return delivered

    def stats(self):
        with self.connect() as db:
            return dict(db.execute('SELECT status,COUNT(*) FROM outbox GROUP BY status').fetchall())


def http_sender(url, api_key=''):
    def send(payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = 'Bearer ' + api_key
        request = urllib.request.Request(url.rstrip('/') + '/v1/events', data=encoded, headers=headers)
        start = time.perf_counter()
        with urllib.request.urlopen(request, timeout=8) as response:
            result = json.loads(response.read().decode('utf-8'))
        round_trip_ms = (time.perf_counter() - start) * 1000
        print(json.dumps({'event_id': payload['event_id'], 'round_trip_ms': round_trip_ms,
                          'cloud_timing': result.get('timing'), 'replayed': result.get('replayed')}, ensure_ascii=False), flush=True)
        return result
    return send


def capture(args, outbox, send):
    # Keep legacy Nano Python separate from Python 3.10+ cloud dependencies.
    from jetson_inference import detectNet
    from jetson_utils import videoSource, cudaToNumpy, cudaDeviceSynchronize
    from PIL import Image
    import numpy as np
    net = detectNet(args.network, argv=[], threshold=args.threshold)
    camera = videoSource(args.camera, argv=[])
    gate = EventGate(args.cooldown, args.heartbeat, args.threshold)
    stop = threading.Event()
    def upload():
        while not stop.is_set():
            outbox.flush(send)
            stop.wait(.5)
    worker = threading.Thread(target=upload)
    worker.daemon = True
    worker.start()
    try:
        while camera.IsStreaming():
            start = time.perf_counter()
            frame = camera.Capture()
            if frame is None:
                continue
            found = net.Detect(frame, overlay='none')
            detections = [{'label': net.GetClassDesc(d.ClassID), 'confidence': float(d.Confidence),
                           'bbox': [float(d.Left), float(d.Top), float(d.Right), float(d.Bottom)]} for d in found]
            now = time.monotonic()
            if not gate.select(detections, now):
                continue
            cudaDeviceSynchronize()
            array = np.asarray(cudaToNumpy(frame))
            image = Image.fromarray(np.clip(array[:, :, :3], 0, 255).astype(np.uint8), 'RGB')
            image.thumbnail((args.width, args.width))
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=args.quality)
            payload = {'event_id': str(uuid.uuid4()), 'node_id': args.node_id, 'captured_at': time.time(),
                       'detections': detections, 'image_b64': base64.b64encode(buffer.getvalue()).decode('ascii'),
                       'question': args.question, 'edge_processing_ms': (time.perf_counter() - start) * 1000}
            try:
                outbox.add(payload)
                gate.commit(detections, now)
            except OverflowError as error:
                print(str(error), flush=True)
    finally:
        stop.set()
        worker.join(timeout=10)
        camera.Close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['capture', 'replay', 'flush', 'stats'])
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--outbox', default='runtime/edge.sqlite')
    parser.add_argument('--events', help='JSON list of protocol fixture events')
    parser.add_argument('--camera', default='/dev/video0')
    parser.add_argument('--network', default='ssd-mobilenet-v2')
    parser.add_argument('--threshold', type=float, default=.5)
    parser.add_argument('--width', type=int, default=640)
    parser.add_argument('--quality', type=int, default=75)
    parser.add_argument('--cooldown', type=float, default=5)
    parser.add_argument('--heartbeat', type=float, default=30)
    parser.add_argument('--node-id', default='jetson-nano-01')
    parser.add_argument('--question', default='Describe visible road objects and uncertainty.')
    args = parser.parse_args()
    if not 64 <= args.width <= 2048 or not 10 <= args.quality <= 95:
        parser.error('width must be 64..2048 and quality 10..95')
    outbox = Outbox(args.outbox)
    send = http_sender(args.url, os.getenv('API_KEY', ''))
    if args.mode == 'capture':
        capture(args, outbox, send)
    elif args.mode == 'replay':
        if not args.events:
            parser.error('--events required for replay')
        with open(args.events, encoding='utf-8') as f:
            for payload in json.load(f):
                outbox.add(payload)
        outbox.flush(send)
    elif args.mode == 'flush':
        outbox.flush(send)
    print(json.dumps(outbox.stats()))


if __name__ == '__main__':
    main()
