"""Configured GuardianLoop agent implementing the frozen adapter contract."""

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from backend.app.agent.adapter import AgentAdapter
from backend.app.agent.ollama_executor import OllamaAgentExecutor
from backend.app.agent.task_handler import extract_expression
from backend.app.agent.tools import TOOL_NAMES, run_checked_tool
from backend.app.api.schemas import AgentInfo
from backend.app.config import Settings
from backend.app.monitoring.trace_recorder import TraceRecorder
from backend.app.agent.trace_compat import legacy_trace_to_v1


SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "shared"
    / "schemas"
    / "agent_config.json"
)
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "guardian_agent_v1.json"


def canonical_config_hash(config: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in config.items() if key != "content_hash"}
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def validate_agent_config(config: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise ValueError("Agent configuration must be a JSON object.")
    data = copy.deepcopy(dict(config))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(data),
        key=lambda error: list(map(str, error.path)),
    )
    if errors:
        detail = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"Agent configuration failed schema validation: {detail}")
    if data["content_hash"] != canonical_config_hash(data):
        raise ValueError("Agent configuration content_hash does not match canonical JSON.")
    if any(rule["tool_name"] not in TOOL_NAMES for rule in data["tool_routing_rules"]):
        raise ValueError("Agent configuration references an unregistered tool.")
    return data


class GuardianAgentAdapter(AgentAdapter):
    """Execute through trusted tools and keep candidate configs inactive."""

    def __init__(
        self,
        settings: Settings,
        config: Mapping[str, Any] | None = None,
        config_path: Path | None = None,
    ) -> None:
        self.settings = settings
        if config is not None:
            self._active_config = validate_agent_config(config)
        else:
            path = config_path or settings.agent_config_path or DEFAULT_CONFIG_PATH
            self._active_config = validate_agent_config(
                json.loads(Path(path).read_text(encoding="utf-8"))
            )
        self._candidate_config: dict[str, Any] | None = None

    def get_config(self) -> Mapping[str, Any]:
        return copy.deepcopy(self._active_config)

    def apply_config(self, config_copy: Mapping[str, Any]) -> Mapping[str, Any]:
        self._candidate_config = validate_agent_config(config_copy)
        return copy.deepcopy(self._candidate_config)

    def run_task(
        self,
        task: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not isinstance(task, Mapping):
            raise ValueError("Task must be an object.")
        task_text = task.get("text", task.get("task"))
        if not isinstance(task_text, str) or not task_text.strip() or len(task_text) > 500:
            raise ValueError("Task text must contain 1 to 500 characters.")
        fault_injection = task.get("fault_injection")
        if fault_injection not in {None, "wrong_tool_result", "inconsistent_answer"}:
            raise ValueError("Unsupported fault injection.")
        if context is not None and not isinstance(context, Mapping):
            raise ValueError("Execution context must be an object.")

        agent = AgentInfo(
            name="guardian-loop-agent",
            version=self._active_config["config_version"],
            mode=self.settings.agent_mode,
        )
        recorder = TraceRecorder(
            task_text,
            agent,
            fault_injection,
        )
        try:
            with recorder.step("plan", "guardian_planner", {"task": task_text}) as step:
                plan = self._plan(task_text)
                step.output = plan
        except Exception:
            legacy = recorder.finalize(None).model_dump(mode="json")
            return legacy_trace_to_v1(legacy, self._active_config["config_version"])

        if plan["verification_status"] == "unverified":
            answer = f"UNVERIFIED: {plan['reason']}"
            with recorder.step("final_answer", "compose_answer", {}) as step:
                step.output = {
                    "text": answer,
                    "verification_status": "unverified",
                }
            legacy = recorder.finalize(answer).model_dump(mode="json")
            return legacy_trace_to_v1(legacy, self._active_config["config_version"])

        try:
            with recorder.step(
                "tool_call",
                plan["tool"],
                plan["tool_input"],
            ) as step:
                result = run_checked_tool(
                    plan["tool"],
                    plan["tool_input"],
                    context,
                )
                result = self._apply_fault_injection(
                    result,
                    fault_injection,
                    plan["tool"],
                )
                step.output = result
        except Exception:
            legacy = recorder.finalize(None).model_dump(mode="json")
            return legacy_trace_to_v1(legacy, self._active_config["config_version"])

        answer = self._format_answer(
            plan["tool"],
            plan["tool_input"],
            result,
            fault_injection,
        )
        with recorder.step(
            "final_answer",
            "compose_answer",
            {"tool_result": result},
        ) as step:
            step.output = {"text": answer}
        legacy = recorder.finalize(answer).model_dump(mode="json")
        return legacy_trace_to_v1(legacy, self._active_config["config_version"])

    def _plan(self, task_text: str) -> dict[str, Any]:
        lowered = task_text.casefold()
        matching_rules = [
            rule
            for rule in self._active_config["tool_routing_rules"]
            if rule["task_match"].casefold() in lowered
        ]
        if matching_rules:
            matching_rules.sort(key=lambda rule: (-rule["priority"], rule["rule_id"]))
            tool_name = matching_rules[0]["tool_name"]
            if (
                tool_name == "policy_document_search"
                and not self._active_config["retrieval_settings"]["enabled"]
            ):
                return self._unverified_plan()
            tool_input = self._complete_tool_input(tool_name, {}, task_text)
            return self._select_with_configured_planner(task_text, {
                "verification_status": "verified",
                "tool": tool_name,
                "tool_input": tool_input,
                "rationale": f"Matched configured route {matching_rules[0]['rule_id']}.",
            })

        date_plan = self._date_plan(task_text)
        if date_plan:
            return self._select_with_configured_planner(task_text, {
                "verification_status": "verified",
                "tool": "calculator",
                "tool_input": date_plan,
                "rationale": "Detected a supported date operation.",
            })

        expression = extract_expression(task_text)
        if expression:
            return self._select_with_configured_planner(task_text, {
                "verification_status": "verified",
                "tool": "calculator",
                "tool_input": {"operation": "calculate", "expression": expression},
                "rationale": "Detected a supported arithmetic expression.",
            })

        if any(word in lowered for word in ("protected record", "confidential record", "restricted record")):
            tool_name = "protected_record_access"
        elif any(word in lowered for word in ("customer", "invoice", "inventory", "business database")):
            tool_name = "business_database_query"
        elif "policy" in lowered or "procedure" in lowered:
            tool_name = "policy_document_search"
        elif "note" in lowered or "remember" in lowered:
            tool_name = "notes_memory"
        elif any(word in lowered for word in ("extract", "email address", "date from", "amount from")):
            tool_name = "text_extraction"
        else:
            return self._unverified_plan()

        return self._select_with_configured_planner(task_text, {
            "verification_status": "verified",
            "tool": tool_name,
            "tool_input": self._complete_tool_input(tool_name, {}, task_text),
            "rationale": "Matched a supported deterministic task route.",
        })

    @staticmethod
    def _unverified_plan() -> dict[str, Any]:
        return {
            "verification_status": "unverified",
            "tool": None,
            "tool_input": {},
            "reason": "The request is outside the configured, verified tool capabilities.",
        }

    def _select_with_configured_planner(
        self, task_text: str, deterministic_plan: dict[str, Any]
    ) -> dict[str, Any]:
        if self.settings.agent_mode != "ollama":
            return deterministic_plan
        if deterministic_plan["tool"] == "calculator" and deterministic_plan["tool_input"][
            "operation"
        ] != "calculate":
            return deterministic_plan
        raw = OllamaAgentExecutor(self.settings).request_guardian_plan(
            task_text,
            self._active_config,
        )
        tool_name = raw["tool"]
        return {
            "verification_status": "verified",
            "tool": tool_name,
            "tool_input": self._complete_tool_input(
                tool_name,
                raw["tool_input"],
                task_text,
            ),
            "rationale": raw["rationale"],
        }

    def _complete_tool_input(
        self, tool_name: str, raw_input: Mapping[str, Any], task_text: str
    ) -> dict[str, Any]:
        if tool_name == "business_database_query":
            table = "customers" if "customer" in task_text.casefold() else (
                "invoices" if "invoice" in task_text.casefold() else "inventory"
            )
            return {"table": raw_input.get("table", table), "filters": raw_input.get("filters", {})}
        if tool_name == "policy_document_search":
            return {
                "query": raw_input.get("query", task_text),
                "top_k": raw_input.get("top_k", self._active_config["retrieval_settings"]["top_k"]),
                "source_ids": raw_input.get(
                    "source_ids", self._active_config["retrieval_settings"]["source_ids"]
                ),
            }
        if tool_name == "calculator":
            if raw_input:
                return dict(raw_input)
            expression = extract_expression(task_text)
            if expression:
                return {"operation": "calculate", "expression": expression}
            date_plan = self._date_plan(task_text)
            if date_plan:
                return date_plan
            raise ValueError("No supported calculator/date operation was found.")
        if tool_name == "text_extraction":
            field = "emails" if "email" in task_text.casefold() else (
                "dates" if "date" in task_text.casefold() else (
                    "amounts" if "amount" in task_text.casefold() else "word_count"
                )
            )
            text = raw_input.get("text", task_text.split(":", 1)[-1].strip())
            return {"text": text, "field": raw_input.get("field", field)}
        if tool_name == "notes_memory":
            return {"query": raw_input.get("query", task_text)}
        if tool_name == "protected_record_access":
            record_match = re.search(r"\bPR-\d+\b", task_text, re.IGNORECASE)
            return {
                "record_id": raw_input.get("record_id", record_match.group(0).upper() if record_match else "unknown"),
                "purpose": raw_input.get("purpose", task_text),
            }
        raise ValueError(f"Unregistered tool in configuration: {tool_name}")

    @staticmethod
    def _date_plan(task_text: str) -> dict[str, Any] | None:
        add_match = re.search(r"add\s+(-?\d+)\s+days?\s+to\s+(\d{4}-\d{2}-\d{2})", task_text, re.IGNORECASE)
        if add_match:
            return {
                "operation": "add_days",
                "date": add_match.group(2),
                "days": int(add_match.group(1)),
            }
        between_match = re.search(
            r"days?\s+between\s+(\d{4}-\d{2}-\d{2})\s+and\s+(\d{4}-\d{2}-\d{2})",
            task_text,
            re.IGNORECASE,
        )
        if between_match:
            return {
                "operation": "days_between",
                "start_date": between_match.group(1),
                "end_date": between_match.group(2),
            }
        return None

    @staticmethod
    def _apply_fault_injection(
        result: dict[str, Any], fault_injection: str | None, tool_name: str
    ) -> dict[str, Any]:
        result = copy.deepcopy(result)
        if fault_injection == "wrong_tool_result":
            key = "result" if tool_name == "calculator" else "word_count"
            if key in result:
                result[key] += 1
        return result

    @staticmethod
    def _format_answer(
        tool_name: str,
        tool_input: Mapping[str, Any],
        result: Mapping[str, Any],
        fault_injection: str | None = None,
    ) -> str:
        if tool_name == "calculator":
            if tool_input["operation"] == "calculate":
                value = result["result"]
                if fault_injection == "inconsistent_answer":
                    value += 1
                value = int(value) if isinstance(value, float) and value.is_integer() else value
                return f"The result of {tool_input['expression']} is {value}."
            return f"Date operation result: {json.dumps(result, sort_keys=True)}"
        if tool_name == "text_extraction" and "word_count" in result:
            value = result["word_count"] + (
                1 if fault_injection == "inconsistent_answer" else 0
            )
            return f"The text contains {value} words."
        if tool_name == "protected_record_access" and not result["authorized"]:
            return "Access denied; no protected record was disclosed."
        return json.dumps(result, sort_keys=True)
