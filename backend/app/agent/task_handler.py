"""Task processing: planning and tools (Person 1).

STATUS
  plan_task ........ MOCK   rule-based keyword/regex planner. No LLM, no reasoning.
  calculator ....... REAL   safe arithmetic evaluator (+ - * / % and parentheses).
  text_stats ....... REAL   counts words/characters.

Supported tasks: an arithmetic expression inside the text, or any other text
(treated as a request for text statistics).
"""
import ast
import math
import operator
import re
from dataclasses import asdict, dataclass
from typing import Any

MAX_EXPRESSION_LENGTH = 200


class ToolError(Exception):
    """Raised by a tool when it cannot complete; the executor records it."""


@dataclass
class TaskPlan:
    kind: str                 # "arithmetic" | "text_stats"
    tool: str                 # tool the executor should call
    tool_input: dict[str, Any]
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- Planner (MOCK) ------------------------------------------------------
_EXPR_RE = re.compile(r"[\d.\s+\-*/%()]{3,}")


def extract_expression(text: str) -> str | None:
    """Longest run of arithmetic characters that has a digit and an operator."""
    best: str | None = None
    for match in _EXPR_RE.findall(text):
        candidate = match.strip()
        if re.search(r"\d", candidate) and re.search(r"[+\-*/%]", candidate):
            if best is None or len(candidate) > len(best):
                best = candidate
    return best


def plan_task(task: str) -> TaskPlan:
    expression = extract_expression(task)
    if expression:
        return TaskPlan(
            kind="arithmetic",
            tool="calculator",
            tool_input={"expression": expression},
            rationale="Found an arithmetic expression in the task text.",
        )
    text = task.split(":", 1)[1].strip() if ":" in task else task
    return TaskPlan(
        kind="text_stats",
        tool="text_stats",
        tool_input={"text": text},
        rationale="No arithmetic expression found; defaulting to text statistics.",
    )


# ---- Tools (REAL) --------------------------------------------------------
_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        return _BINARY_OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval(node.operand))
    raise ToolError("unsupported expression")


def calculator(expression: str) -> dict[str, Any]:
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ToolError("expression too long")
    try:
        value = _eval(ast.parse(expression, mode="eval"))
    except ZeroDivisionError:
        raise ToolError("division by zero") from None
    except SyntaxError:
        raise ToolError("invalid expression syntax") from None
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ToolError("result is not finite")
        value = int(value) if value.is_integer() else round(value, 10)
    return {"result": value}


def text_stats(text: str) -> dict[str, Any]:
    words = text.split()
    return {
        "word_count": len(words),
        "char_count": len(text),
        "longest_word": max(words, key=len) if words else "",
    }


TOOLS = {"calculator": calculator, "text_stats": text_stats}
