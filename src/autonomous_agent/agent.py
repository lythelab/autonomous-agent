import logging
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import Settings
from .e2b_runner import E2BExecutor
from .llm import GroqPlanner
from .models import AgentLogEntry, AgentSession, AgentStatusResponse, EpisodeRecord
from .storage import AgentStorage

logger = logging.getLogger(__name__)


LIVE_GOAL_KEYWORDS = (
    "recent",
    "latest",
    "current",
    "today",
    "news",
    "snapshot",
    "release",
    "changes",
    "update",
    "updates",
)


class AutonomousAgent:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._storage = AgentStorage(settings.agent_db_path)
        self._planner = GroqPlanner(settings)
        self._executor = E2BExecutor(
            api_key=settings.e2b_api_key,
            timeout_seconds=settings.e2b_timeout_seconds,
            step_timeout_seconds=settings.e2b_step_timeout_seconds,
        )

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running_lock = threading.Lock()
        self._active_session_id: Optional[str] = None

    def _write_log(self, session_id: str, level: str, message: str, iteration: int = 0) -> None:
        if level.upper() == "ERROR":
            logger.error("session_id=%s iter=%s %s", session_id, iteration, message)
        elif level.upper() == "WARNING":
            logger.warning("session_id=%s iter=%s %s", session_id, iteration, message)
        else:
            logger.info("session_id=%s iter=%s %s", session_id, iteration, message)
        self._storage.add_log(session_id=session_id, level=level, message=message, iteration=iteration)

    @staticmethod
    def _needs_live_research(goal: str) -> bool:
        goal_lower = goal.lower()
        return any(keyword in goal_lower for keyword in LIVE_GOAL_KEYWORDS)

    @staticmethod
    def _build_live_research_code(goal: str) -> str:
        goal_json = json.dumps(goal)
        return f'''import json
import re
import urllib.parse
import urllib.request

goal = {goal_json}
query = urllib.parse.quote_plus(goal)
search_url = f"https://html.duckduckgo.com/html/?q={{query}}"
headers = {{"User-Agent": "Mozilla/5.0"}}

def fetch(url, timeout=12):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")

def strip_html(text):
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\\s+", " ", text)
    return text.strip()

print(f"SEARCH QUERY: {{goal}}")
search_html = fetch(search_url, timeout=12)
print(f"SEARCH URL: {{search_url}}")
print(f"SEARCH BYTES: {{len(search_html)}}")

links = []
for match in re.finditer(r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', search_html, flags=re.S | re.I):
    href = match.group("href")
    title = strip_html(match.group("title"))
    links.append((title, urllib.parse.unquote(href)))
    if len(links) >= 3:
        break

if not links:
    print("NO SEARCH RESULTS FOUND")
else:
    for index, (title, url) in enumerate(links, start=1):
        print(f"RESULT {{index}}: {{title}}")
        print(f"URL {{index}}: {{url}}")
        try:
            page = fetch(url, timeout=10)
            snippet = strip_html(page)[:500]
            print(f"SNIPPET {{index}}: {{snippet}}")
        except Exception as exc:
            print(f"FETCH_ERROR {{index}}: {{type(exc).__name__}}: {{exc}}")
        print("---")
'''

    @staticmethod
    def _strip_html(text: str) -> str:
        text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _collect_live_research(self, goal: str) -> str:
        headers = {"User-Agent": "Mozilla/5.0"}
        search_url = f"https://html.duckduckgo.com/html/?q={httpx.QueryParams({'q': goal})['q']}"

        try:
            with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
                response = client.get(search_url)
                response.raise_for_status()
                search_html = response.text

                results: list[tuple[str, str]] = []
                for match in re.finditer(
                    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
                    search_html,
                    flags=re.S | re.I,
                ):
                    href = match.group("href")
                    title = self._strip_html(match.group("title"))
                    results.append((title, href))
                    if len(results) >= 3:
                        break

                lines = [f"SEARCH QUERY: {goal}", f"SEARCH URL: {search_url}"]
                if not results:
                    lines.append("NO SEARCH RESULTS FOUND")
                    return "\n".join(lines)

                for index, (title, href) in enumerate(results, start=1):
                    redirect_url = href if href.startswith(("http://", "https://")) else f"https:{href}" if href.startswith("//") else href
                    parsed = urlparse(redirect_url)
                    url = parse_qs(parsed.query).get("uddg", [redirect_url])[0]
                    url = unquote(url)
                    if url.startswith("//"):
                        url = f"https:{url}"
                    elif not url.startswith(("http://", "https://")):
                        url = f"https://{url.lstrip('/')}"
                    lines.append(f"RESULT {index}: {title}")
                    lines.append(f"URL {index}: {url}")
                    try:
                        page = client.get(url, timeout=12)
                        page.raise_for_status()
                        snippet = self._strip_html(page.text)[:500]
                        lines.append(f"SNIPPET {index}: {snippet}")
                    except Exception as exc:  # pylint: disable=broad-except
                        lines.append(f"FETCH_ERROR {index}: {type(exc).__name__}: {exc}")
                    lines.append("---")

                return "\n".join(lines)
        except Exception as exc:  # pylint: disable=broad-except
            return f"Live research failed for goal '{goal}': {type(exc).__name__}: {exc}"

    def start(self, goal: str, session_id: Optional[str] = None) -> str:
        existing_thread: Optional[threading.Thread] = None
        existing_session_id: Optional[str] = None

        with self._running_lock:
            if self.is_running:
                existing_thread = self._thread
                existing_session_id = self._active_session_id
                self._stop_event.set()

        if existing_thread is not None:
            self._write_log(existing_session_id or "unknown", "INFO", "Restart requested; stopping current session")
            existing_thread.join(timeout=max(5, self._settings.agent_cycle_sleep_seconds + 5))
            if existing_thread.is_alive():
                raise RuntimeError("Previous session is still stopping. Try again.")

        with self._running_lock:
            sid = session_id or str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            existing = self._storage.get_session(sid)

            if existing:
                session = existing.model_copy(update={"goal": goal, "status": "running", "updated_at": now})
            else:
                session = AgentSession(
                    session_id=sid,
                    goal=goal,
                    status="running",
                    iteration=0,
                    last_output="",
                    started_at=now,
                    updated_at=now,
                )

            self._storage.upsert_session(session)
            self._write_log(sid, "INFO", "Session started", iteration=session.iteration)
            self._active_session_id = sid
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, args=(sid,), daemon=True)
            self._thread.start()
            return sid

    def stop(self) -> None:
        with self._running_lock:
            self._stop_event.set()
            if self._active_session_id:
                self._write_log(self._active_session_id, "INFO", "Stop requested")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self, session_id: Optional[str] = None) -> AgentStatusResponse:
        sid = session_id or self._active_session_id
        if not sid:
            return AgentStatusResponse(session=None, outputs=[])

        session = self._storage.get_session(sid)
        if session is None:
            return AgentStatusResponse(session=None, outputs=[])

        outputs = self._storage.list_recent_outputs(sid, limit=20)
        return AgentStatusResponse(session=session, outputs=outputs)

    def logs(self, session_id: Optional[str] = None, limit: int = 100) -> list[AgentLogEntry]:
        sid = session_id or self._active_session_id
        if not sid:
            return []
        return self._storage.get_logs(sid, limit=limit)

    def answer_session_question(self, session_id: str, question: str) -> str:
        session = self._storage.get_session(session_id)
        if session is None:
            raise ValueError("Session not found")

        outputs = self._storage.list_recent_outputs(session_id, limit=80)
        logs = self._storage.get_logs(session_id, limit=120)
        log_lines = [f"iter={item.iteration} {item.level}: {item.message}" for item in logs]

        answer = self._planner.answer_question_from_context(
            goal=session.goal,
            question=question,
            outputs=outputs,
            agent_logs=log_lines,
        )
        return answer

    def _set_session_state(self, session_id: str, status: str, last_output: str = "", iteration: Optional[int] = None) -> None:
        existing = self._storage.get_session(session_id)
        if existing is None:
            return
        updated = existing.model_copy(
            update={
                "status": status,
                "last_output": last_output,
                "iteration": iteration if iteration is not None else existing.iteration,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._storage.upsert_session(updated)

    def _run_loop(self, session_id: str) -> None:
        self._write_log(session_id, "INFO", "Agent loop started")

        try:
            while not self._stop_event.is_set():
                session = self._storage.get_session(session_id)
                if session is None:
                    self._write_log(session_id, "ERROR", "Session missing from storage")
                    return

                if session.iteration >= self._settings.agent_max_iterations:
                    self._write_log(
                        session_id,
                        "WARNING",
                        "Maximum iteration limit reached",
                        iteration=session.iteration,
                    )
                    self._set_session_state(session_id, status="max_iterations_reached", iteration=session.iteration)
                    return

                memory_context = self._storage.search_memory(session_id, session.goal, limit=8)
                recent_episodes = self._storage.get_recent_episodes(
                    session_id,
                    limit=self._settings.agent_max_full_episodes,
                )
                recent_outputs = [episode.stdout for episode in reversed(recent_episodes) if episode.stdout]

                if self._needs_live_research(session.goal) and not recent_outputs:
                    next_iteration = session.iteration + 1
                    research_text = self._collect_live_research(session.goal)
                    try:
                        research_summary = self._planner.summarize_live_research(session.goal, research_text)
                    except Exception as exc:  # pylint: disable=broad-except
                        research_summary = (
                            "Unable to summarize live research with Groq at this moment. "
                            f"Raw research status: {type(exc).__name__}."
                        )

                    self._storage.add_episode(
                        EpisodeRecord(
                            session_id=session_id,
                            iteration=next_iteration,
                            thought="Collect live web research before answering.",
                            code="",
                            stdout=research_summary,
                            stderr="",
                            success=not research_text.startswith("Live research failed"),
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    self._storage.add_memory(session_id=session_id, content=research_text[:1000], score=0.9)
                    self._storage.add_memory(session_id=session_id, content=research_summary[:1000], score=0.95)
                    self._set_session_state(
                        session_id,
                        status="running",
                        last_output=research_summary,
                        iteration=next_iteration,
                    )
                    self._write_log(
                        session_id,
                        "INFO",
                        "Collected live web research",
                        iteration=next_iteration,
                    )
                    time.sleep(self._settings.agent_cycle_sleep_seconds)
                    continue

                plan = self._planner.plan_next_step(
                    goal=session.goal,
                    recent_outputs=recent_outputs,
                    memories=memory_context,
                )

                if plan.done and self._needs_live_research(session.goal) and not recent_outputs:
                    self._write_log(
                        session_id,
                        "INFO",
                        "Forcing live research step before completion",
                        iteration=session.iteration + 1,
                    )
                    plan = plan.model_copy(
                        update={
                            "done": False,
                            "python_code": self._build_live_research_code(session.goal),
                            "thought": "Fetch live web evidence before answering.",
                            "final_output": "",
                        }
                    )

                next_iteration = session.iteration + 1
                self._write_log(
                    session_id,
                    "INFO",
                    f"Planned iteration {next_iteration}: {plan.thought[:200]}",
                    iteration=next_iteration,
                )

                if plan.done:
                    final_output = plan.final_output.strip() or "Goal completed"
                    self._write_log(
                        session_id,
                        "INFO",
                        "Planner marked goal as completed",
                        iteration=next_iteration,
                    )
                    self._storage.add_episode(
                        EpisodeRecord(
                            session_id=session_id,
                            iteration=next_iteration,
                            thought=plan.thought,
                            code=plan.python_code,
                            stdout=final_output,
                            stderr="",
                            success=True,
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    self._set_session_state(
                        session_id,
                        status="completed",
                        last_output=final_output,
                        iteration=next_iteration,
                    )
                    return

                execution = self._executor.run_python(plan.python_code)
                stdout = execution.stdout.strip()
                stderr = execution.stderr.strip()
                self._write_log(
                    session_id,
                    "INFO" if execution.success else "ERROR",
                    "Code execution succeeded" if execution.success else "Code execution failed",
                    iteration=next_iteration,
                )

                self._storage.add_episode(
                    EpisodeRecord(
                        session_id=session_id,
                        iteration=next_iteration,
                        thought=plan.thought,
                        code=plan.python_code,
                        stdout=stdout,
                        stderr=stderr,
                        success=execution.success,
                        created_at=datetime.now(timezone.utc),
                    )
                )

                summary = self._planner.summarize_episode(
                    goal=session.goal,
                    thought=plan.thought,
                    stdout=stdout,
                    stderr=stderr,
                )
                score = 0.8 if execution.success else 0.4
                self._storage.add_memory(session_id=session_id, content=summary, score=score)
                self._write_log(
                    session_id,
                    "INFO",
                    "Episode summarized and memory updated",
                    iteration=next_iteration,
                )

                last_output = stdout if stdout else stderr
                self._set_session_state(
                    session_id,
                    status="running",
                    last_output=last_output,
                    iteration=next_iteration,
                )

                if self._stop_event.wait(timeout=self._settings.agent_cycle_sleep_seconds):
                    break

            self._set_session_state(session_id, status="stopped")
            self._write_log(session_id, "INFO", "Agent loop stopped")
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Agent loop crashed for session_id=%s", session_id)
            self._write_log(session_id, "ERROR", f"Agent loop crashed: {type(exc).__name__}")
            self._set_session_state(session_id, status=f"failed: {type(exc).__name__}")
        finally:
            self._write_log(session_id, "INFO", "Agent loop ended")

    def shutdown(self) -> None:
        self.stop()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=10)
        self._executor.close()
