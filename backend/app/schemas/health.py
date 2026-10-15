from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["spotify-consolidator"] = "spotify-consolidator"
    stage: Literal["foundation"] = "foundation"
