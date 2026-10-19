from pydantic import BaseModel, ConfigDict, Field


class Detection(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    label: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0, le=1)
    bbox: tuple[float, float, float, float] | None = None


class Event(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    event_id: str = Field(min_length=1, max_length=100)
    node_id: str = Field(min_length=1, max_length=100)
    captured_at: float = Field(ge=0)
    detections: list[Detection] = Field(default_factory=list, max_length=100)
    image_b64: str | None = Field(default=None, max_length=2_800_000)
    question: str = Field(default='请描述道路场景，区分可见事实与推测。', min_length=1, max_length=1000)
    edge_processing_ms: float = Field(default=0, ge=0, le=1_000_000)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
