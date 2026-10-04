from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ResumeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    status: str
    is_current: bool
    created_at: datetime


class CurrentResumeResponse(ResumeResponse):
    converted_text: str | None = None
    error: str | None = None
