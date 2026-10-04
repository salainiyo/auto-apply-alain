from pydantic import BaseModel


class DashboardSummary(BaseModel):
    available: int
    applied: int
    archived: int
