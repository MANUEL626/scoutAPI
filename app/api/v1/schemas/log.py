from datetime import datetime

from pydantic import BaseModel


class JobLogResponse(BaseModel):
    id: str
    job_id: str
    level: str
    message: str
    data: dict
    created_at: datetime

    model_config = {"from_attributes": True}
