from contextlib import asynccontextmanager
import asyncio
import hmac
import httpx
from fastapi import FastAPI, Header, HTTPException, Depends
from .config import Settings
from .schema import Event, Question
from .backend import CircuitOpenError
from .service import EventService, ConflictError


def create_app(settings=None):
    settings = settings or Settings.from_env()
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = EventService(settings)
        yield
    app = FastAPI(title='Roadside Multimodal Agent', version='0.1.0', lifespan=lifespan)

    def auth(authorization: str = Header(default='')):
        if settings.api_key and not hmac.compare_digest(authorization, 'Bearer ' + settings.api_key):
            raise HTTPException(401, 'Invalid API key')

    @app.get('/health')
    def health():
        return {'status': 'ok', 'backend': settings.backend, 'model': settings.model}

    @app.get('/metrics', dependencies=[Depends(auth)])
    def metrics():
        return app.state.service.counters

    async def guarded(coro):
        try:
            return await coro
        except ConflictError as error:
            raise HTTPException(409, str(error)) from error
        except KeyError as error:
            raise HTTPException(404, 'event not found') from error
        except CircuitOpenError as error:
            raise HTTPException(503, str(error)) from error
        except asyncio.TimeoutError as error:
            raise HTTPException(504, 'request deadline exceeded') from error
        except httpx.HTTPError as error:
            raise HTTPException(502, 'VLM upstream failure') from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.post('/v1/events', dependencies=[Depends(auth)])
    async def process(event: Event):
        return await guarded(app.state.service.process(event))

    @app.get('/v1/events/{event_id}', dependencies=[Depends(auth)])
    def get_event(event_id: str):
        try:
            return app.state.service.lookup(event_id)[1]
        except KeyError as error:
            raise HTTPException(404, 'event not found') from error

    @app.post('/v1/events/{event_id}/questions', dependencies=[Depends(auth)])
    async def question(event_id: str, query: Question):
        return await guarded(app.state.service.question(event_id, query.question))

    return app
