"""Six trusted business tools and independent deterministic output checkers."""

import ast
import operator
import re
from datetime import date, timedelta
from typing import Any, Callable, Mapping

from backend.app.agent.business_world import (
    BUSINESS_DATABASE,
    NOTES,
    POLICY_DOCUMENTS,
    PROTECTED_RECORDS,
)
from backend.app.agent.task_handler import ToolError, calculator


TOOL_NAMES = (
    "business_database_query",
    "policy_document_search",
    "calculator",
    "text_extraction",
    "notes_memory",
    "protected_record_access",
)


class ToolInputError(ValueError):
    """Raised when a trusted tool receives invalid or unauthorized input."""


def _require_exact_keys(value: Mapping[str, Any], keys: set[str]) -> None:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ToolInputError(f"Expected exactly these fields: {sorted(keys)}")


def _validate_database_input(table: Any, filters: Any) -> None:
    if not isinstance(table, str) or table not in BUSINESS_DATABASE:
        raise ToolInputError("Unknown business table.")
    if not isinstance(filters, dict):
        raise ToolInputError("Database filters must be an object.")
    columns = set(BUSINESS_DATABASE[table][0]) if BUSINESS_DATABASE[table] else set()
    if not set(filters).issubset(columns):
        raise ToolInputError("Database filter contains an unknown column.")
    if any(not isinstance(value, (str, int, float, bool)) for value in filters.values()):
        raise ToolInputError("Database filter values must be scalar.")


def business_database_query(table: str, filters: dict[str, Any]) -> dict[str, Any]:
    _validate_database_input(table, filters)
    rows = [
        dict(row)
        for row in BUSINESS_DATABASE[table]
        if all(row.get(key) == value for key, value in filters.items())
    ]
    return {"table": table, "rows": rows}


def check_business_database_query(
    inputs: Mapping[str, Any], output: Any, context: Mapping[str, Any] | None = None
) -> bool:
    _require_exact_keys(inputs, {"table", "filters"})
    _validate_database_input(inputs["table"], inputs["filters"])
    expected_rows = []
    for row in BUSINESS_DATABASE[inputs["table"]]:
        matches = True
        for key, expected_value in inputs["filters"].items():
            if row[key] != expected_value:
                matches = False
                break
        if matches:
            expected_rows.append(dict(row))
    return output == {"table": inputs["table"], "rows": expected_rows}


def _policy_results(query: str, top_k: int, source_ids: list[str]) -> list[dict[str, Any]]:
    terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    documents = [doc for doc in POLICY_DOCUMENTS if not source_ids or doc["document_id"] in source_ids]
    ranked = []
    for doc in documents:
        content_terms = set(re.findall(r"[a-z0-9]+", f'{doc["title"]} {doc["text"]}'.casefold()))
        score = len(terms & content_terms)
        if score:
            ranked.append((score, doc))
    ranked.sort(key=lambda item: (-item[0], item[1]["document_id"]))
    return [
        {"document_id": doc["document_id"], "title": doc["title"], "text": doc["text"], "score": score}
        for score, doc in ranked[:top_k]
    ]


def policy_document_search(
    query: str, top_k: int = 3, source_ids: list[str] | None = None
) -> dict[str, Any]:
    source_ids = [] if source_ids is None else source_ids
    _require_exact_keys({"query": query, "top_k": top_k, "source_ids": source_ids}, {"query", "top_k", "source_ids"})
    if not isinstance(query, str) or not query.strip():
        raise ToolInputError("Policy search query cannot be empty.")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 0:
        raise ToolInputError("top_k must be a non-negative integer.")
    known_sources = {doc["document_id"] for doc in POLICY_DOCUMENTS}
    if not isinstance(source_ids, list) or any(
        not isinstance(source_id, str) or source_id not in known_sources
        for source_id in source_ids
    ) or len(source_ids) != len(set(source_ids)):
        raise ToolInputError("Unknown policy source.")
    return {"results": _policy_results(query, top_k, source_ids)}


def check_policy_document_search(
    inputs: Mapping[str, Any], output: Any, context: Mapping[str, Any] | None = None
) -> bool:
    _require_exact_keys(inputs, {"query", "top_k", "source_ids"})
    query, top_k, source_ids = inputs["query"], inputs["top_k"], inputs["source_ids"]
    if not isinstance(query, str) or not query.strip():
        raise ToolInputError("Policy search query cannot be empty.")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 0:
        raise ToolInputError("top_k must be a non-negative integer.")
    known_sources = {doc["document_id"] for doc in POLICY_DOCUMENTS}
    if not isinstance(source_ids, list) or any(
        not isinstance(source_id, str) or source_id not in known_sources
        for source_id in source_ids
    ) or len(source_ids) != len(set(source_ids)):
        raise ToolInputError("Unknown policy source.")
    terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    expected = []
    for doc in POLICY_DOCUMENTS:
        if source_ids and doc["document_id"] not in source_ids:
            continue
        tokens = set(re.findall(r"[a-z0-9]+", (doc["title"] + " " + doc["text"]).casefold()))
        overlap = len(terms.intersection(tokens))
        if overlap:
            expected.append(
                (overlap, {"document_id": doc["document_id"], "title": doc["title"], "text": doc["text"], "score": overlap})
            )
    expected.sort(key=lambda item: (-item[0], item[1]["document_id"]))
    return output == {"results": [item[1] for item in expected[:top_k]]}


def _date_operation(operation: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    if operation == "calculate":
        _require_exact_keys(inputs, {"operation", "expression"})
        expression = inputs["expression"]
        if not isinstance(expression, str):
            raise ToolInputError("Expression must be text.")
        return calculator(expression)
    if operation == "add_days":
        _require_exact_keys(inputs, {"operation", "date", "days"})
        if not isinstance(inputs["date"], str) or not isinstance(inputs["days"], int) or isinstance(inputs["days"], bool):
            raise ToolInputError("add_days requires an ISO date and integer day count.")
        try:
            result = date.fromisoformat(inputs["date"]) + timedelta(days=inputs["days"])
        except ValueError as exc:
            raise ToolInputError("Invalid ISO date.") from exc
        return {"result_date": result.isoformat()}
    if operation == "days_between":
        _require_exact_keys(inputs, {"operation", "start_date", "end_date"})
        if not isinstance(inputs["start_date"], str) or not isinstance(inputs["end_date"], str):
            raise ToolInputError("days_between requires two ISO dates.")
        try:
            start = date.fromisoformat(inputs["start_date"])
            end = date.fromisoformat(inputs["end_date"])
        except ValueError as exc:
            raise ToolInputError("Invalid ISO date.") from exc
        return {"days": (end - start).days}
    raise ToolInputError("Unsupported calculator/date operation.")


def calculator_date(operation: str, **inputs: Any) -> dict[str, Any]:
    return _date_operation(operation, {"operation": operation, **inputs})


def check_calculator_date(
    inputs: Mapping[str, Any], output: Any, context: Mapping[str, Any] | None = None
) -> bool:
    if not isinstance(inputs, Mapping) or "operation" not in inputs:
        raise ToolInputError("Calculator/date operation is required.")
    operation = inputs["operation"]
    if operation == "calculate":
        _require_exact_keys(inputs, {"operation", "expression"})
        expression = inputs["expression"]
        if not isinstance(expression, str) or not expression.strip():
            raise ToolInputError("Expression must be non-empty text.")
        # Re-evaluate the restricted AST rather than trusting the tool output.
        parsed = ast.parse(expression, mode="eval")
        allowed = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Mod: operator.mod}

        def evaluate(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return evaluate(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in allowed:
                return allowed[type(node.op)](evaluate(node.left), evaluate(node.right))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            raise ToolInputError("Unsupported arithmetic expression.")

        expected_value = evaluate(parsed)
        if isinstance(expected_value, float):
            expected_value = int(expected_value) if expected_value.is_integer() else round(expected_value, 10)
        return output == {"result": expected_value}
    return output == _date_operation(operation, inputs)


_EXTRACTION_PATTERNS = {
    "emails": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "dates": re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    "amounts": re.compile(r"(?<!\w)\$\d+(?:\.\d{2})?\b"),
}


def text_extraction(text: str, field: str) -> dict[str, Any]:
    if not isinstance(text, str) or not isinstance(field, str) or field not in {*_EXTRACTION_PATTERNS, "word_count"}:
        raise ToolInputError("Text extraction input or field is invalid.")
    if field == "word_count":
        return {"word_count": len(text.split())}
    return {"matches": _EXTRACTION_PATTERNS[field].findall(text)}


def check_text_extraction(
    inputs: Mapping[str, Any], output: Any, context: Mapping[str, Any] | None = None
) -> bool:
    _require_exact_keys(inputs, {"text", "field"})
    text, field = inputs["text"], inputs["field"]
    if not isinstance(text, str) or not isinstance(field, str) or field not in {*_EXTRACTION_PATTERNS, "word_count"}:
        raise ToolInputError("Text extraction input or field is invalid.")
    if field == "word_count":
        return output == {"word_count": len(text.split())}
    pattern = _EXTRACTION_PATTERNS[field]
    matches = [match.group(0) for match in pattern.finditer(text)]
    return output == {"matches": matches}


def _matching_notes(query: str) -> list[dict[str, str]]:
    terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    return [
        dict(note)
        for note in NOTES
        if terms.intersection(re.findall(r"[a-z0-9]+", note["text"].casefold()))
    ]


def notes_memory(query: str) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ToolInputError("Notes query cannot be empty.")
    return {"notes": _matching_notes(query)}


def check_notes_memory(
    inputs: Mapping[str, Any], output: Any, context: Mapping[str, Any] | None = None
) -> bool:
    _require_exact_keys(inputs, {"query"})
    query = inputs["query"]
    if not isinstance(query, str) or not query.strip():
        raise ToolInputError("Notes query cannot be empty.")
    terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
    expected = []
    for note in NOTES:
        note_terms = set(re.findall(r"[a-z0-9]+", note["text"].casefold()))
        if any(term in note_terms for term in terms):
            expected.append(dict(note))
    return output == {"notes": expected}


def _authorized_record(record_id: str, context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    entry = PROTECTED_RECORDS.get(record_id)
    if not entry or not isinstance(context, Mapping):
        return None
    principal = context.get("principal")
    roles = principal.get("roles", []) if isinstance(principal, Mapping) else []
    if not isinstance(roles, list) or entry["required_role"] not in roles:
        return None
    return dict(entry["record"])


def protected_record_access(
    record_id: str, purpose: str, context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(record_id, str) or not record_id.strip():
        raise ToolInputError("record_id is required.")
    if not isinstance(purpose, str) or not purpose.strip():
        raise ToolInputError("A business purpose is required.")
    record = _authorized_record(record_id, context)
    return {"record_id": record_id, "authorized": record is not None, "record": record}


def check_protected_record_access(
    inputs: Mapping[str, Any], output: Any, context: Mapping[str, Any] | None = None
) -> bool:
    _require_exact_keys(inputs, {"record_id", "purpose"})
    record_id, purpose = inputs["record_id"], inputs["purpose"]
    if not isinstance(record_id, str) or not record_id.strip() or not isinstance(purpose, str) or not purpose.strip():
        raise ToolInputError("record_id and business purpose are required.")
    expected_record = None
    entry = PROTECTED_RECORDS.get(record_id)
    if entry and isinstance(context, Mapping):
        principal = context.get("principal")
        roles = principal.get("roles", []) if isinstance(principal, Mapping) else []
        if isinstance(roles, list) and entry["required_role"] in roles:
            expected_record = dict(entry["record"])
    return output == {
        "record_id": record_id,
        "authorized": expected_record is not None,
        "record": expected_record,
    }


TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "business_database_query": business_database_query,
    "policy_document_search": policy_document_search,
    "calculator": calculator_date,
    "text_extraction": text_extraction,
    "notes_memory": notes_memory,
    "protected_record_access": protected_record_access,
}

TOOL_CHECKERS: dict[str, Callable[..., bool]] = {
    "business_database_query": check_business_database_query,
    "policy_document_search": check_policy_document_search,
    "calculator": check_calculator_date,
    "text_extraction": check_text_extraction,
    "notes_memory": check_notes_memory,
    "protected_record_access": check_protected_record_access,
}


def validate_tool_input(tool_name: str, tool_input: Mapping[str, Any]) -> None:
    if tool_name not in TOOL_FUNCTIONS:
        raise ToolInputError("Unregistered trusted tool.")
    if not isinstance(tool_input, Mapping):
        raise ToolInputError("Tool input must be an object.")
    if tool_name == "business_database_query":
        _require_exact_keys(tool_input, {"table", "filters"})
        _validate_database_input(tool_input["table"], tool_input["filters"])
    elif tool_name == "policy_document_search":
        _require_exact_keys(tool_input, {"query", "top_k", "source_ids"})
        check_policy_document_search(tool_input, {"results": []})
    elif tool_name == "calculator":
        check_calculator_date(tool_input, {})
    elif tool_name == "text_extraction":
        check_text_extraction(tool_input, {})
    elif tool_name == "notes_memory":
        check_notes_memory(tool_input, {})
    elif tool_name == "protected_record_access":
        check_protected_record_access(tool_input, {})


def run_checked_tool(
    tool_name: str,
    tool_input: Mapping[str, Any],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validate_tool_input(tool_name, tool_input)
    function = TOOL_FUNCTIONS[tool_name]
    if tool_name == "protected_record_access":
        output = function(**dict(tool_input), context=context)
    else:
        output = function(**dict(tool_input))
    if not TOOL_CHECKERS[tool_name](tool_input, output, context):
        raise ToolError(f"Deterministic checker rejected {tool_name} output.")
    return output
