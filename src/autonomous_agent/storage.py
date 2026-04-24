import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .models import AgentLogEntry, AgentSession, EpisodeRecord, MemoryItem, SystemLogEntry


class AgentStorage:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    iteration INTEGER NOT NULL DEFAULT 0,
                    last_output TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL,
                    thought TEXT NOT NULL,
                    code TEXT NOT NULL,
                    stdout TEXT NOT NULL,
                    stderr TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    content TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    iteration INTEGER NOT NULL DEFAULT 0,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
                );

                CREATE TABLE IF NOT EXISTS system_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    request_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_episodes_session_iteration
                    ON episodes(session_id, iteration);

                CREATE INDEX IF NOT EXISTS idx_memory_session_score
                    ON long_term_memory(session_id, score DESC);

                CREATE INDEX IF NOT EXISTS idx_agent_logs_session_id
                    ON agent_logs(session_id, id DESC);

                CREATE INDEX IF NOT EXISTS idx_system_logs_id
                    ON system_logs(id DESC);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def upsert_session(self, session: AgentSession) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (session_id, goal, status, iteration, last_output, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    goal = excluded.goal,
                    status = excluded.status,
                    iteration = excluded.iteration,
                    last_output = excluded.last_output,
                    updated_at = excluded.updated_at
                """,
                (
                    session.session_id,
                    session.goal,
                    session.status,
                    session.iteration,
                    session.last_output,
                    session.started_at.isoformat(),
                    session.updated_at.isoformat(),
                ),
            )

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            if row is None:
                return None
            return AgentSession(
                session_id=row["session_id"],
                goal=row["goal"],
                status=row["status"],
                iteration=row["iteration"],
                last_output=row["last_output"],
                started_at=datetime.fromisoformat(row["started_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def list_recent_outputs(self, session_id: str, limit: int = 20) -> List[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT stdout FROM episodes
                WHERE session_id = ? AND stdout <> ''
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [row["stdout"] for row in reversed(rows)]

    def add_episode(self, episode: EpisodeRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO episodes (session_id, iteration, thought, code, stdout, stderr, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.session_id,
                    episode.iteration,
                    episode.thought,
                    episode.code,
                    episode.stdout,
                    episode.stderr,
                    int(episode.success),
                    episode.created_at.isoformat(),
                ),
            )

    def get_recent_episodes(self, session_id: str, limit: int = 25) -> List[EpisodeRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM episodes
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [
                EpisodeRecord(
                    id=row["id"],
                    session_id=row["session_id"],
                    iteration=row["iteration"],
                    thought=row["thought"],
                    code=row["code"],
                    stdout=row["stdout"],
                    stderr=row["stderr"],
                    success=bool(row["success"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    def add_memory(self, session_id: str, content: str, score: float, metadata: str = "{}") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO long_term_memory (session_id, content, score, metadata, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, content, score, metadata, self._now()),
            )

    def search_memory(self, session_id: str, query: str, limit: int = 8) -> List[MemoryItem]:
        like_query = f"%{query.strip()}%"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT content, score, metadata FROM long_term_memory
                WHERE session_id = ? AND content LIKE ?
                ORDER BY score DESC, id DESC
                LIMIT ?
                """,
                (session_id, like_query, limit),
            ).fetchall()

            if not rows:
                rows = conn.execute(
                    """
                    SELECT content, score, metadata FROM long_term_memory
                    WHERE session_id = ?
                    ORDER BY score DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()

            return [
                MemoryItem(content=row["content"], score=row["score"], metadata={"raw": row["metadata"]})
                for row in rows
            ]

    def add_log(self, session_id: str, level: str, message: str, iteration: int = 0) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_logs (session_id, iteration, level, message, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, iteration, level.upper(), message, self._now()),
            )

    def get_logs(self, session_id: str, limit: int = 100) -> List[AgentLogEntry]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_logs
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()

            return [
                AgentLogEntry(
                    id=row["id"],
                    session_id=row["session_id"],
                    iteration=row["iteration"],
                    level=row["level"],
                    message=row["message"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]

    def add_system_log(self, level: str, source: str, message: str, request_id: str = "") -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO system_logs (level, source, message, request_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (level.upper(), source, message, request_id, self._now()),
            )

    def get_system_logs(self, limit: int = 200) -> List[SystemLogEntry]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM system_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            return [
                SystemLogEntry(
                    id=row["id"],
                    level=row["level"],
                    source=row["source"],
                    message=row["message"],
                    request_id=row["request_id"],
                    created_at=datetime.fromisoformat(row["created_at"]),
                )
                for row in rows
            ]
