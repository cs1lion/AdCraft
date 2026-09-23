from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    mode: Literal["mock", "real"]
    agent_runtime: Literal["reachable", "unreachable", "disabled", "unknown"] | None = None
