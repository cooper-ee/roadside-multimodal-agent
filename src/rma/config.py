from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    backend: str = 'mock'
    base_url: str = 'http://127.0.0.1:8002/v1'
    model: str = 'local-vlm'
    backend_key: str = ''
    api_key: str = ''
    database: str = 'runtime/events.sqlite'
    max_concurrency: int = 2
    timeout_s: float = 40.0
    circuit_failures: int = 3
    circuit_reset_s: float = 15.0

    def __post_init__(self):
        if self.backend not in {'mock', 'openai'}:
            raise ValueError('backend must be mock or openai')
        if self.max_concurrency < 1 or self.timeout_s <= 0 or self.circuit_failures < 1 or self.circuit_reset_s < 0:
            raise ValueError('invalid service limits')

    @classmethod
    def from_env(cls):
        return cls(backend=os.getenv('BACKEND', 'mock'), base_url=os.getenv('VLM_BASE_URL', 'http://127.0.0.1:8002/v1').rstrip('/'),
                   model=os.getenv('VLM_MODEL', 'local-vlm'), backend_key=os.getenv('VLM_API_KEY', ''),
                   api_key=os.getenv('API_KEY', ''), database=os.getenv('DATABASE', 'runtime/events.sqlite'),
                   max_concurrency=int(os.getenv('MAX_CONCURRENCY', '2')), timeout_s=float(os.getenv('REQUEST_TIMEOUT_S', '40')))
