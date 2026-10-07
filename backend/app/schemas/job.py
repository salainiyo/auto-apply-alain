from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobMatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role_id: UUID | None
    title: str
    company: str
    location: str | None
    url: str
    source: str
    job_type: str | None
    is_remote: bool
    locality: str
    posted_at: datetime | None
    status: str
    apply_mechanism: str
    created_at: datetime


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_match_id: UUID
    status: str
    cover_letter: str | None = None
    detail: str | None = None
    created_at: datetime
    updated_at: datetime
