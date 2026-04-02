from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

try:
    from groq import Groq
except ImportError:  # pragma: no cover - optional dependency for local test runs
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
        self.db_path = Path(db_path)
        self.max_full_episodes = max_full_episodes
        self.groq_client = groq_client
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.summary_provider = summary_provider or self._summarize_with_groq
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()

    def __enter__(self) -> MemoryManager:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def _initialize_schema(self) -> None:
        with self.connection:
            self.connection.execute(
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
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_meta (
                    meta_key TEXT PRIMARY KEY,
                    meta_value TEXT NOT NULL
                )
                """
            )

    def write(self, key: str, value: dict[str, Any], timestamp: float | None = None) -> None:
        now = time.time() if timestamp is None else timestamp
        payload = json.dumps(value, sort_keys=True)
        with self.connection:
            existing = self.connection.execute(
                "SELECT created_at FROM memory_entries WHERE key = ?",
                (key,),
            ).fetchone()
            created_at = existing["created_at"] if existing is not None else now
            self.connection.execute(
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
        row = self.connection.execute(
            "SELECT value_json FROM memory_entries WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["value_json"])

    def get_full_episodes(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT key, value_json, entry_type, created_at, updated_at
            FROM memory_entries
            WHERE entry_type = 'full'
            ORDER BY created_at ASC, updated_at ASC, key ASC
            """
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_summary(self) -> str | None:
        row = self.connection.execute(
            """
            SELECT meta_value
            FROM memory_meta
            WHERE meta_key = 'summary'
            """
        ).fetchone()
        return None if row is None else row["meta_value"]

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_terms = [term for term in re.findall(r"[\w-]+", query.lower()) if term]
        rows = self.connection.execute(
            """
            SELECT key, value_json, entry_type, created_at, updated_at
            FROM memory_entries
            ORDER BY updated_at DESC, key ASC
            """
        ).fetchall()

        scored_results: list[dict[str, Any]] = []
        for row in rows:
            payload_text = row["value_json"].lower()
            haystack = f"{row['key'].lower()} {payload_text}"
            base_score = sum(haystack.count(term) for term in query_terms) if query_terms else 0
            recency_bonus = self._recency_bonus(row["updated_at"])
            score = base_score + recency_bonus
            if query_terms and base_score == 0:
                continue
            scored_results.append(
                {
                    "key": row["key"],
                    "value": json.loads(row["value_json"]),
                    "entry_type": row["entry_type"],
                    "score": score,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )

        scored_results.sort(key=lambda item: (-item["score"], -item["updated_at"], item["key"]))
        return scored_results[:top_k]

    def _compress_if_needed(self) -> None:
        full_count = self.connection.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE entry_type = 'full'"
        ).fetchone()[0]
        if full_count <= self.max_full_episodes:
            return

        overflow = full_count - self.max_full_episodes
        rows = self.connection.execute(
            """
            SELECT key, value_json, entry_type, created_at, updated_at
            FROM memory_entries
            WHERE entry_type = 'full'
            ORDER BY created_at ASC, updated_at ASC, key ASC
            LIMIT ?
            """,
            (overflow,),
        ).fetchall()

        if not rows:
            return

        records = [self._row_to_record(row) for row in rows]
        summary_text = self.summary_provider(records)
        summary_key = f"summary_{int(time.time() * 1000)}"
        now = time.time()

        with self.connection:
            self.connection.executemany(
                "DELETE FROM memory_entries WHERE key = ?",
                [(record["key"],) for record in records],
            )
            self.connection.execute(
                """
                INSERT INTO memory_entries (key, value_json, entry_type, created_at, updated_at)
                VALUES (?, ?, 'summary', ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    entry_type = 'summary',
                    updated_at = excluded.updated_at
                """,
                (
                    summary_key,
                    json.dumps({"summary": summary_text, "sources": [record["key"] for record in records]}, sort_keys=True),
                    now,
                    now,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO memory_meta (meta_key, meta_value)
                VALUES ('summary', ?)
                ON CONFLICT(meta_key) DO UPDATE SET meta_value = excluded.meta_value
                """,
                (summary_text,),
            )

    def _summarize_episodes(self, records: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for record in records:
            value = record["value"]
            if isinstance(value, dict):
                snippet = ", ".join(f"{key}={value[key]}" for key in sorted(value)[:4])
            else:
                snippet = str(value)
            parts.append(f"{record['key']}: {snippet}")
        return " | ".join(parts)

    def _summarize_with_groq(self, records: list[dict[str, Any]]) -> str:
        client = self.groq_client or self._create_groq_client()
        prompt = self._build_summary_prompt(records)
        response = client.chat.completions.create(
            model=self.groq_model,
            messages=[
                {
                    "role": "system",
                    "content": "You compress agent episode history into a concise persistent summary.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        return response.choices[0].message.content.strip()

    def _create_groq_client(self) -> Any:
        if Groq is None:
            raise RuntimeError("Groq SDK is not installed. Install the 'groq' package and set GROQ_API_KEY.")

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required for Groq-backed compression.")

        return Groq(api_key=api_key)

    def _build_summary_prompt(self, records: list[dict[str, Any]]) -> str:
        lines = [
            "Summarize the following memory episodes for long-term persistence.",
            "Keep key facts, recent progress, unfinished work, and important identifiers.",
            "Return a compact summary in plain text.",
            "",
        ]
        for record in records:
            lines.append(f"- {record['key']}: {json.dumps(record['value'], sort_keys=True)}")
        return "\n".join(lines)

    def _recency_bonus(self, updated_at: float) -> float:
        age_seconds = max(time.time() - updated_at, 0.0)
        return max(0.0, 100.0 - age_seconds / 60.0)

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "key": row["key"],
            "value": json.loads(row["value_json"]),
            "entry_type": row["entry_type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
