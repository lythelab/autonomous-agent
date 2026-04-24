from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    thought: str
    python_code: str
    done: bool = False
    final_output: str = ""


class EpisodeRecord(BaseModel):
    id: Optional[int] = None
    session_id: str
    iteration: int
    thought: str
    code: str
    stdout: str
    stderr: str
    success: bool
    created_at: datetime


class AgentSession(BaseModel):
    session_id: str
    goal: str
    status: str
    iteration: int
    last_output: str = ""
    started_at: datetime
    updated_at: datetime


class StartRequest(BaseModel):
    goal: str = Field(min_length=3)
    session_id: Optional[str] = None


class AgentStatusResponse(BaseModel):
    session: Optional[AgentSession] = None
    outputs: List[str] = []


class MemoryItem(BaseModel):
    content: str
    score: float
    metadata: Dict[str, Any] = {}


class AgentLogEntry(BaseModel):
    id: Optional[int] = None
    session_id: str
    iteration: int
    level: str
    message: str
    created_at: datetime


class AgentLogsResponse(BaseModel):
    session_id: str
    logs: List[AgentLogEntry]


class SystemLogEntry(BaseModel):
    id: Optional[int] = None
    level: str
    source: str
    message: str
    request_id: str = ""
    created_at: datetime


class SystemLogsResponse(BaseModel):
    logs: List[SystemLogEntry]


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=3)
    question: str = Field(min_length=2)


class ChatResponse(BaseModel):
    session_id: str
    answer: str
