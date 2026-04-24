import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .agent import AutonomousAgent
from .config import get_settings
from .logging_config import configure_logging
from .models import AgentLogsResponse, AgentStatusResponse, ChatRequest, ChatResponse, StartRequest, SystemLogsResponse
from .storage import AgentStorage

settings = get_settings()
configure_logging()
agent = AutonomousAgent(settings=settings)
storage = AgentStorage(settings.agent_db_path)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    agent.shutdown()


app = FastAPI(title="Autonomous Agent", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins_list,
    allow_origin_regex=settings.frontend_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        message = (
            f"{request.method} {request.url.path} -> {response.status_code} "
            f"in {latency_ms}ms"
        )
        logger.info("request_id=%s %s", request_id, message)
        storage.add_system_log("INFO", "api", message, request_id=request_id)
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:  # pylint: disable=broad-except
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        message = (
            f"{request.method} {request.url.path} -> 500 in {latency_ms}ms "
            f"({type(exc).__name__}: {exc})"
        )
        logger.exception("request_id=%s %s", request_id, message)
        storage.add_system_log("ERROR", "api", message, request_id=request_id)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/agent/start")
def start_agent(request: StartRequest) -> dict:
    try:
        session_id = agent.start(goal=request.goal, session_id=request.session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"session_id": session_id, "status": "running"}


@app.post("/agent/stop")
def stop_agent() -> dict:
    agent.stop()
    return {"status": "stopping"}


@app.get("/agent/status", response_model=AgentStatusResponse)
def agent_status(session_id: Optional[str] = Query(default=None)) -> AgentStatusResponse:
    return agent.status(session_id=session_id)


@app.get("/agent/output")
def agent_output(session_id: Optional[str] = Query(default=None), limit: int = Query(default=20, ge=1, le=200)) -> dict:
    status = agent.status(session_id=session_id)
    if status.session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    outputs = status.outputs[-limit:]
    return {
        "session_id": status.session.session_id,
        "status": status.session.status,
        "outputs": outputs,
    }


@app.get("/agent/logs", response_model=AgentLogsResponse)
def agent_logs(session_id: Optional[str] = Query(default=None), limit: int = Query(default=100, ge=1, le=1000)) -> AgentLogsResponse:
    status = agent.status(session_id=session_id)
    if status.session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    logs = agent.logs(session_id=status.session.session_id, limit=limit)
    return AgentLogsResponse(session_id=status.session.session_id, logs=logs)


@app.get("/system/logs", response_model=SystemLogsResponse)
def system_logs(limit: int = Query(default=200, ge=1, le=2000)) -> SystemLogsResponse:
    logs = storage.get_system_logs(limit=limit)
    return SystemLogsResponse(logs=logs)


@app.post("/agent/chat", response_model=ChatResponse)
def agent_chat(request: ChatRequest) -> ChatResponse:
    status = agent.status(session_id=request.session_id)
    if status.session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        answer = agent.answer_session_question(request.session_id, request.question)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return ChatResponse(session_id=request.session_id, answer=answer)
