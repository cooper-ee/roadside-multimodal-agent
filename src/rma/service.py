from pathlib import Path
from contextlib import asynccontextmanager
import asyncio
import hashlib
import json
import sqlite3
import time
from .backend import VLMBackend
from .schema import Event
from .vision import scene_rules, validate_image


class ConflictError(ValueError):
    pass


class EventService:
    def __init__(self, settings, backend=None):
        self.settings = settings
        self.backend = backend or VLMBackend(settings)
        Path(settings.database).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, event_id TEXT, question TEXT, answer TEXT, duration_ms REAL);
            ''')
        self.locks = {}
        self.semaphore = asyncio.Semaphore(settings.max_concurrency)
        self.counters = {'received': 0, 'replayed': 0, 'processed': 0, 'errors': 0}

    def connect(self):
        return sqlite3.connect(self.settings.database, timeout=10)

    @asynccontextmanager
    async def event_lock(self, key):
        lock, users = self.locks.get(key, (asyncio.Lock(), 0))
        self.locks[key] = lock, users + 1
        try:
            async with lock:
                yield
        finally:
            lock, users = self.locks[key]
            if users == 1:
                del self.locks[key]
            else:
                self.locks[key] = lock, users - 1

    def lookup(self, event_id):
        with self.connect() as db:
            row = db.execute('SELECT payload,result,fingerprint FROM events WHERE id=?', (event_id,)).fetchone()
        if not row:
            raise KeyError(event_id)
        return Event.model_validate_json(row[0]), json.loads(row[1]), row[2]

    async def process(self, event):
        self.counters['received'] += 1
        try:
            return await asyncio.wait_for(self._process(event), self.settings.timeout_s)
        except Exception:
            self.counters['errors'] += 1
            raise

    async def _process(self, event):
        start = time.perf_counter()
        validate_image(event.image_b64)
        encoded = event.model_dump_json()
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        async with self.event_lock(event.event_id):
            try:
                _, old, old_fingerprint = self.lookup(event.event_id)
            except KeyError:
                old = None
            if old is not None:
                if fingerprint != old_fingerprint:
                    raise ConflictError('event_id already associated with different payload')
                self.counters['replayed'] += 1
                return {**old, 'replayed': True}
            async with self.semaphore:
                queue_ms = (time.perf_counter() - start) * 1000
                inference_start = time.perf_counter()
                answer = await self.backend.ask(event, event.question)
                inference_ms = (time.perf_counter() - inference_start) * 1000
            result = {'event_id': event.event_id, 'node_id': event.node_id, 'backend': self.settings.backend,
                      'answer': answer, 'rules': scene_rules(event.detections), 'replayed': False,
                      'timing': {'cloud_queue_ms': queue_ms, 'vlm_ms': inference_ms,
                                 'cloud_processing_ms': (time.perf_counter() - start) * 1000,
                                 'edge_processing_ms': event.edge_processing_ms},
                      'tool_action': 'suggestion_only', 'image_bytes': len(validate_image(event.image_b64) or b'')}
            with self.connect() as db:
                db.execute('INSERT INTO events VALUES (?,?,?,?)', (event.event_id, fingerprint, encoded, json.dumps(result, ensure_ascii=False)))
            self.counters['processed'] += 1
            return result

    async def question(self, event_id, question):
        event, _, _ = self.lookup(event_id)
        async def run():
            start = time.perf_counter()
            async with self.semaphore:
                answer = await self.backend.ask(event, question)
            duration_ms = (time.perf_counter() - start) * 1000
            with self.connect() as db:
                db.execute('INSERT INTO questions(event_id,question,answer,duration_ms) VALUES (?,?,?,?)', (event_id, question, answer, duration_ms))
            return {'event_id': event_id, 'question': question, 'answer': answer, 'backend': self.settings.backend, 'duration_ms': duration_ms}
        return await asyncio.wait_for(run(), self.settings.timeout_s)
