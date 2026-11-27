"""Ollama-powered agent executor.

Ollama selects a registered tool.
Trusted Python functions execute all tools.
"""

import json
from typing import Any

import httpx

from backend.app.agent.task_handler import TOOLS
from backend.app.agent.tools import validate_tool_input
from backend.app.api.schemas import AgentInfo, ExecutionTrace, TaskRequest
from backend.app.config import Settings
from backend.app.monitoring.trace_recorder import TraceRecorder


class OllamaAgentExecutor:
    """Plans tasks using Ollama and executes registered Python tools."""

    VERSION = "1.0.0"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.agent = AgentInfo(
            name=settings.ollama_model,
            version=self.VERSION,
            mode="ollama",
        )

    def _request_plan(self, task: str) -> dict[str, Any]:
        """Ask Ollama to select a registered tool."""

        system_prompt = """
You are an AI agent planner.

You can select ONLY these tools:

1. calculator
   Input: {"expression": "arithmetic expression"}

2. text_stats
   Input: {"text": "text to analyze"}

Rules:
- Use calculator for arithmetic.
- Use text_stats for word counting and text analysis.
- Never invent tools.
- Never return Python code.
- Never calculate results yourself.
- Return exactly three fields:
  tool, tool_input, rationale.
- Return valid JSON only.

Example calculator response:
{
  "tool": "calculator",
  "tool_input": {"expression": "25 * 4 + 10"},
  "rationale": "Arithmetic task"
}

Example text response:
{
  "tool": "text_stats",
  "tool_input": {"text": "AI agents monitor their own execution"},
  "rationale": "Text analysis task"
}
"""

        payload = {
            "model": self.settings.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ],
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {
                "temperature": 0,
                "num_predict": 96,
            },
        }

        url = self.settings.ollama_base_url.rstrip("/") + "/api/chat"

        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self.settings.ollama_timeout_seconds,
            )
            response.raise_for_status()
            response_data = response.json()
            content = response_data["message"]["content"]
            plan = json.loads(content)

        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(
                f"Ollama planning failed: {exc}"
            ) from None

        if not isinstance(plan, dict):
            raise ValueError("Agent plan must be a JSON object.")

        if "tool" not in plan or "tool_input" not in plan:
            raise ValueError("Ollama omitted required planning fields.")

        if "rationale" not in plan:
            plan["rationale"] = "Tool selected by Ollama."

        plan = {
            "tool": plan["tool"],
            "tool_input": plan["tool_input"],
            "rationale": plan["rationale"],
        }

        self._validate_plan(plan)
        return plan

    def request_guardian_plan(
        self, task: str, agent_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Ask Ollama to select only from the six M1 trusted tools."""
        tool_contracts = {
            "business_database_query": {"table": "customers|invoices|inventory", "filters": {}},
            "policy_document_search": {"query": "text", "top_k": 3, "source_ids": []},
            "calculator": [
                {"operation": "calculate", "expression": "2 + 2"},
                {"operation": "add_days", "date": "2026-01-01", "days": 1},
                {
                    "operation": "days_between",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-02",
                },
            ],
            "text_extraction": {"text": "source text", "field": "emails|dates|amounts|word_count"},
            "notes_memory": {"query": "text"},
            "protected_record_access": {"record_id": "PR-1001", "purpose": "business purpose"},
        }
        system_prompt = (
            "Select exactly one registered trusted tool. Return JSON with exactly "
            "tool, tool_input, rationale. Never return code or calculate results. "
            "The Python tool implementation performs all operations. "
            f"Tool input contracts: {json.dumps(tool_contracts, sort_keys=True)}. "
            f"Agent instructions: {agent_config['instructions']} "
            f"Routing rules: {json.dumps(agent_config['tool_routing_rules'], sort_keys=True)}"
        )
        payload = {
            "model": self.settings.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ],
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "options": {"temperature": 0, "num_predict": 128},
        }
        url = self.settings.ollama_base_url.rstrip("/") + "/api/chat"
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=self.settings.ollama_timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            plan = json.loads(content)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError(f"Ollama planning failed: {exc}") from None
        if (
            not isinstance(plan, dict)
            or set(plan) != {"tool", "tool_input", "rationale"}
            or not isinstance(plan["rationale"], str)
            or not plan["rationale"].strip()
        ):
            raise ValueError("Ollama returned an invalid GuardianLoop plan.")
        validate_tool_input(plan["tool"], plan["tool_input"])
        return plan

    @staticmethod
    def _validate_plan(plan: Any) -> None:
        """Strictly validate tool names and arguments."""

        if not isinstance(plan, dict):
            raise ValueError("Invalid agent plan.")

        if set(plan) != {"tool", "tool_input", "rationale"}:
            raise ValueError("Invalid planning fields.")

        tool = plan["tool"]
        tool_input = plan["tool_input"]
        rationale = plan["rationale"]

        if not isinstance(tool, str) or tool not in TOOLS:
            raise ValueError("Unregistered tool selected.")

        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("Invalid planning rationale.")

        if not isinstance(tool_input, dict):
            raise ValueError("Tool input must be an object.")

        if tool == "calculator":
            if set(tool_input) != {"expression"}:
                raise ValueError("Invalid calculator arguments.")

            expression = tool_input["expression"]

            if (
                not isinstance(expression, str)
                or not expression.strip()
                or len(expression) > 200
            ):
                raise ValueError("Invalid calculator expression.")

        elif tool == "text_stats":
            if set(tool_input) != {"text"}:
                raise ValueError("Invalid text arguments.")

            text = tool_input["text"]

            if not isinstance(text, str) or len(text) > 500:
                raise ValueError("Invalid text input.")

    @staticmethod
    def _extract_text(task: str, planned_text: str) -> str:
        """Extract text after a colon for common text-analysis requests."""

        if not isinstance(planned_text, str):
            raise ValueError("Invalid planned text.")

        if ":" in task:
            candidate = task.split(":", 1)[1].strip()
            if candidate:
                return candidate[:500]

        return planned_text.strip()[:500]

    def run(self, request: TaskRequest) -> ExecutionTrace:
        recorder = TraceRecorder(
            request.task,
            self.agent,
            request.fault_injection,
        )

        try:
            with recorder.step(
                "plan",
                "ollama_planner",
                {"task": request.task},
            ) as step:

                plan = self._request_plan(request.task)

                if plan["tool"] == "text_stats":
                    plan["tool_input"]["text"] = self._extract_text(
                        request.task,
                        plan["tool_input"]["text"],
                    )

                step.output = {
                    "model": self.settings.ollama_model,
                    "tool": plan["tool"],
                    "tool_input": plan["tool_input"],
                    "rationale": plan["rationale"],
                }

        except Exception:
            return recorder.finalize(final_answer=None)

        tool_name = plan["tool"]
        tool_input = plan["tool_input"]

        try:
            with recorder.step(
                "tool_call",
                tool_name,
                tool_input,
            ) as step:

                result = TOOLS[tool_name](**tool_input)

                if request.fault_injection == "wrong_tool_result":
                    key = (
                        "result"
                        if tool_name == "calculator"
                        else "word_count"
                    )
                    result[key] += 1

                step.output = result

        except Exception:
            return recorder.finalize(final_answer=None)

        if tool_name == "calculator":
            value = result["result"]

            stated = (
                float(value) + 1
                if request.fault_injection == "inconsistent_answer"
                else value
            )

            formatted = (
                str(int(stated))
                if float(stated).is_integer()
                else f"{stated:.10g}"
            )

            answer = (
                f"The result of {tool_input['expression']} is {formatted}."
            )

        else:
            stated = (
                result["word_count"] + 1
                if request.fault_injection == "inconsistent_answer"
                else result["word_count"]
            )

            answer = f"The text contains {stated} words."

        with recorder.step(
            "final_answer",
            "compose_answer",
            {"tool_result": result},
        ) as step:
            step.output = {"text": answer}

        return recorder.finalize(final_answer=answer)
