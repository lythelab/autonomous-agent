import json
from typing import List

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import Settings
from .models import MemoryItem, PlanStep


class GroqPlanner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = "https://api.groq.com/openai/v1/chat/completions"

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3), reraise=True)
    def plan_next_step(self, goal: str, recent_outputs: List[str], memories: List[MemoryItem]) -> PlanStep:
        memory_blob = "\n".join(f"- {item.content}" for item in memories) or "None"
        outputs_blob = "\n".join(f"- {line}" for line in recent_outputs[-8:]) or "None"

        system_prompt = (
            "You are an autonomous coding and reasoning planner. "
            "Return strict JSON with keys: thought, python_code, done, final_output. "
            "When done=true, python_code may be empty and final_output must contain the final answer."
        )
        user_prompt = f"""
Goal:
{goal}

Relevant long-term memory:
{memory_blob}

Recent computation outputs:
{outputs_blob}

Rules:
1) Produce exactly one incremental action using executable Python code.
2) Use only standard library Python unless absolutely required.
3) Print concrete outputs for verification.
4) If goal is complete, set done=true and provide final_output.
5) Return valid JSON only.
6) If you fetch the web, use short request timeouts and print the response status plus a short summary.
7) Prefer a quick best-effort answer over long scraping or waiting.
8) If the goal asks for recent, latest, current, news, snapshot, release, or changes, do not answer from memory; first fetch live web evidence.
9) For live/current goals, do not set done=true until you have printed evidence from the web or another live source.
10) If recent_outputs already contain live research, search results, or snippets, synthesize them into the final answer instead of generating another code step.
""".strip()

        payload = {
            "model": self._settings.groq_model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        headers = {
            "Authorization": f"Bearer {self._settings.groq_api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=60) as client:
            response = client.post(self._base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        return PlanStep(
            thought=parsed.get("thought", ""),
            python_code=parsed.get("python_code", ""),
            done=bool(parsed.get("done", False)),
            final_output=parsed.get("final_output", ""),
        )

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3), reraise=True)
    def summarize_episode(self, goal: str, thought: str, stdout: str, stderr: str) -> str:
        system_prompt = "Summarize this episode in 1-2 lines, keeping key learnings and useful facts."
        user_prompt = f"""
Goal: {goal}
Thought: {thought}
Stdout: {stdout}
Stderr: {stderr}
""".strip()

        payload = {
            "model": self._settings.groq_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        headers = {
            "Authorization": f"Bearer {self._settings.groq_api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30) as client:
            response = client.post(self._base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"].strip()

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3), reraise=True)
    def summarize_live_research(self, goal: str, research_text: str) -> str:
        system_prompt = (
            "You are a concise analyst. Summarize live web findings for the user's goal. "
            "Output plain text with: (1) a short direct answer, (2) key changes as bullets, "
            "(3) source URLs if present. If evidence is weak or blocked (403/timeout), say so clearly."
        )
        user_prompt = f"""
Goal:
{goal}

Live research notes:
{research_text}
""".strip()

        payload = {
            "model": self._settings.groq_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        headers = {
            "Authorization": f"Bearer {self._settings.groq_api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=45) as client:
            response = client.post(self._base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"].strip()

    @retry(wait=wait_exponential(multiplier=1, min=1, max=20), stop=stop_after_attempt(3), reraise=True)
    def answer_question_from_context(
        self,
        goal: str,
        question: str,
        outputs: List[str],
        agent_logs: List[str],
    ) -> str:
        outputs_blob = "\n".join(f"- {item}" for item in outputs[-20:]) or "None"
        logs_blob = "\n".join(f"- {item}" for item in agent_logs[-40:]) or "None"

        system_prompt = (
            "You are a helpful assistant that answers questions strictly using provided session context. "
            "If context is insufficient, say what is missing and propose the next action."
        )
        user_prompt = f"""
Session goal:
{goal}

Question:
{question}

Session outputs:
{outputs_blob}

Session runtime logs:
{logs_blob}

Rules:
1) Prefer direct, concise answers.
2) Cite key evidence from outputs/logs in plain text.
3) If uncertain, state uncertainty clearly.
""".strip()

        payload = {
            "model": self._settings.groq_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        headers = {
            "Authorization": f"Bearer {self._settings.groq_api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=45) as client:
            response = client.post(self._base_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        return data["choices"][0]["message"]["content"].strip()
