from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .config import get_settings

try:
    from groq import Groq
except ImportError:
    Groq = None


class MemoryManager:
    def __init__(
        self,
        db_path: str | Path,
        max_full_episodes: int = 5,
        groq_client: Any | None = None,
        groq_model: str | None = None,
        summary_provider: Callable[[list[dict[str, Any]]], str] | None = None,
    ) -> None:
        settings = get_settings()

        self.db_path = Path(db_path)
        self.max_full_episodes = max_full_episodes
        self.groq_client = groq_client
        self.groq_model = groq_model or settings.groq_model
        self.summary_provider = summary_provider or self._summarize_with_groq

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema once
        self._initialize_schema()

    # ---------------------------
    # Connection Handling (KEY FIX)
    # ---------------------------
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        return conn

    # ---------------------------
    # Schema
    # ---------------------------
    def _initialize_schema(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_entries (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_meta (
                    meta_key TEXT PRIMARY KEY,
                    meta_value TEXT NOT NULL
                )
                """
            )

    # ---------------------------
    # CRUD
    # ---------------------------
    def write(self, key: str, value: dict[str, Any], timestamp: float | None = None) -> None:
        now = time.time() if timestamp is None else timestamp
        payload = json.dumps(value, sort_keys=True)

        with self._get_connection() as conn:
            existing = conn.execute(
                "SELECT created_at FROM memory_entries WHERE key = ?",
                (key,),
            ).fetchone()

            created_at = existing["created_at"] if existing else now

            conn.execute(
                """
                INSERT INTO memory_entries (key, value_json, entry_type, created_at, updated_at)
                VALUES (?, ?, 'full', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    entry_type = 'full',
                    updated_at = excluded.updated_at
                """,
                (key, payload, created_at, now),
            )

        self._compress_if_needed()

    def read(self, key: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT value_json FROM memory_entries WHERE key = ?",
                (key,),
            ).fetchone()

        return None if row is None else json.loads(row["value_json"])

    # ---------------------------
    # Retrieval
    # ---------------------------
    def get_full_episodes(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT key, value_json, entry_type, created_at, updated_at
                FROM memory_entries
                WHERE entry_type = 'full'
                ORDER BY created_at ASC, updated_at ASC, key ASC
                """
            ).fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_summary(self) -> str | None:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT meta_value FROM memory_meta WHERE meta_key = 'summary'"
            ).fetchone()

        return None if row is None else row["meta_value"]

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_terms = [t for t in re.findall(r"[\w-]+", query.lower()) if t]

        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT key, value_json, entry_type, created_at, updated_at
                FROM memory_entries
                ORDER BY updated_at DESC
                """
            ).fetchall()

        results = []
        for row in rows:
            text = f"{row['key']} {row['value_json']}".lower()

            base_score = sum(text.count(term) for term in query_terms) if query_terms else 0
            if query_terms and base_score == 0:
                continue

            score = base_score + self._recency_bonus(row["updated_at"])

            results.append({
                "key": row["key"],
                "value": json.loads(row["value_json"]),
                "entry_type": row["entry_type"],
                "score": score,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })

        results.sort(key=lambda x: (-x["score"], -x["updated_at"]))
        return results[:top_k]

    def get_context_pack(self, query: str | None = None, top_k: int = 5) -> dict[str, Any]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT key, value_json, entry_type, created_at, updated_at
                FROM memory_entries
                WHERE entry_type = 'full'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (top_k,),
            ).fetchall()

        context = {
            "summary": self.get_summary(),
            "recent_episodes": [self._row_to_record(r) for r in rows],
        }

        if query:
            context["matches"] = self.search(query, top_k)

        return context

    # ---------------------------
    # Compression
    # ---------------------------
    def _compress_if_needed(self) -> None:
        with self._get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM memory_entries WHERE entry_type='full'"
            ).fetchone()[0]

            if count <= self.max_full_episodes:
                return

            overflow = count - self.max_full_episodes

            rows = conn.execute(
                """
                SELECT key, value_json, entry_type, created_at, updated_at
                FROM memory_entries
                WHERE entry_type = 'full'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (overflow,),
            ).fetchall()

        records = [self._row_to_record(r) for r in rows]
        summary_text = self.summary_provider(records)

        now = time.time()
        summary_key = f"summary_{int(now * 1000)}"

        with self._get_connection() as conn:
            conn.executemany(
                "DELETE FROM memory_entries WHERE key = ?",
                [(r["key"],) for r in records],
            )

            conn.execute(
                """
                INSERT INTO memory_entries (key, value_json, entry_type, created_at, updated_at)
                VALUES (?, ?, 'summary', ?, ?)
                """,
                (
                    summary_key,
                    json.dumps({"summary": summary_text}, sort_keys=True),
                    now,
                    now,
                ),
            )

            conn.execute(
                """
                INSERT INTO memory_meta (meta_key, meta_value)
                VALUES ('summary', ?)
                ON CONFLICT(meta_key) DO UPDATE SET meta_value = excluded.meta_value
                """,
                (summary_text,),
            )

    # ---------------------------
    # Summarization
    # ---------------------------
    def _summarize_with_groq(self, records: list[dict[str, Any]]) -> str:
        client = self.groq_client or self._create_groq_client()

        prompt = "\n".join(
            f"- {r['key']}: {json.dumps(r['value'])}" for r in records
        )

        response = client.chat.completions.create(
            model=self.groq_model,
            messages=[
                {"role": "system", "content": "Summarize agent memory concisely."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )

        return response.choices[0].message.content.strip()

    def _create_groq_client(self) -> Any:
        if Groq is None:
            raise RuntimeError("Install 'groq' package.")

        api_key = get_settings().groq_api_key
        if not api_key:
            raise RuntimeError("Missing GROQ_API_KEY")

        return Groq(api_key=api_key)

    # ---------------------------
    # Utils
    # ---------------------------
    def _recency_bonus(self, updated_at: float) -> float:
        age = max(time.time() - updated_at, 0)
        return max(0, 100 - age / 60)

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "key": row["key"],
            "value": json.loads(row["value_json"]),
            "entry_type": row["entry_type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }