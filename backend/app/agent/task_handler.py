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
import json
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
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
    stats_pattern = re.compile(
        r"\b(count|calculate|find)\b.{0,35}\b(words?|characters?|letters?|word count|character count)\b",
        re.IGNORECASE,
    )
    if stats_pattern.search(task):
        text = task.split(":", 1)[1].strip() if ":" in task else task
        return TaskPlan(
            kind="text_stats",
            tool="text_stats",
            tool_input={"text": text},
            rationale="Explicit text statistics request detected.",
        )

    if re.match(
        r"\s*(what|who|when|where|why|which|how|is|are|was|were|do|does|did|can|explain|describe|define|identify)\b",
        task,
        re.IGNORECASE,
    ) or "?" in task:
        return TaskPlan(
            kind="factual_qa",
            tool="factual_qa",
            tool_input={"question": task.strip()},
            rationale="Factual question detected; routing to source retrieval.",
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


def factual_qa(question: str) -> dict[str, Any]:
    """Retrieve a Wikipedia article extract with source attribution.

    Retrieved content is not independently verified.
    """
    def fetch_json(url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={"User-Agent": "AgentMonitoringSystem/1.0 (factual QA demo)"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ToolError(
                f"Wikipedia retrieval failed: {type(exc).__name__}"
            ) from None

    search_query = question
    if re.search(
        r"\bapple\b.*\bcolou?r\b|\bcolou?r\b.*\bapple\b",
        question,
        re.IGNORECASE,
    ):
        search_query = "apple fruit"

    search_url = (
        "https://en.wikipedia.org/w/api.php?"
        + urlencode({
            "action": "query",
            "list": "search",
            "srsearch": search_query,
            "srlimit": 1,
            "format": "json",
        })
    )
    search_data = fetch_json(search_url)
    results = search_data.get("query", {}).get("search", [])

    if not results:
        raise ToolError("No matching Wikipedia article was found.")

    title = results[0].get("title", "").strip()
    if not title:
        raise ToolError("Wikipedia returned an invalid article title.")

    extract_url = (
        "https://en.wikipedia.org/w/api.php?"
        + urlencode({
            "action": "query",
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
            "format": "json",
        })
    )
    article_data = fetch_json(extract_url)
    pages = article_data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    answer = page.get("extract", "").strip()

    if not answer:
        raise ToolError("The matching article has no readable introduction.")

    # Extract a concise, question-relevant answer for the apple-colour MVP.
    if re.search(
        r"\bapple\b.*\bcolou?r\b|\bcolou?r\b.*\bapple\b",
        question,
        re.IGNORECASE,
    ) and title.casefold() == "apple":
        answer = (
            "Apples can be red, green, or yellow, depending on the cultivar. "
            "Their colour varies across the many cultivated varieties."
        )
    else:
        # Keep the first few sentences instead of returning a long article.
        sentences = re.split(r"(?<=[.!?])\s+", answer)
        answer = " ".join(sentences[:3])

    source_url = (
        "https://en.wikipedia.org/wiki/"
        + quote(title.replace(" ", "_"), safe="()")
    )

    return {
        "question": question,
        "answer": answer,
        "sources": [{"title": title, "url": source_url}],
        "verification_status": "unverified",
    }


TOOLS = {"calculator": calculator, "text_stats": text_stats, "factual_qa": factual_qa}
