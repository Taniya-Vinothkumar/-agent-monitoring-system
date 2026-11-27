"""Reviewer evaluation (Person 2).

STATUS: REAL but deliberately narrow. This is a rule-based reviewer. It checks
things that can be verified mechanically:
  - structure of the trace (answer present, no errors, consecutive step ids)
  - tool outputs, re-computed independently of the agent
  - agreement between tool outputs and the final answer
  - latency against a budget
It does NOT judge semantic quality, helpfulness or reasoning.

Input and output are plain dicts that follow shared/schemas/*.json, so this
module has no dependency on the backend.
"""
import math
import re
import ast
import operator
import uuid
from datetime import datetime, timezone

REVIEWER_INFO = {"name": "rule-based-reviewer", "version": "0.1.0", "mode": "rule_based"}
SEVERITY_WEIGHTS = {"info": 1, "warning": 2, "critical": 3}
REQUIRED_CHECK_IDS = [
    "final_answer_present",
    "no_step_errors",
    "trace_step_ids_consecutive",
    "tool_results_independently_verified",
    "final_answer_matches_tool_results",
    "latency_within_budget",
]

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


# ---- Independent re-computation -----------------------------------------
# Intentionally a separate implementation from the agent's calculator, so the
# reviewer does not inherit the agent's bugs.
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Mod: operator.mod}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval(node.operand)
        return v if isinstance(node.op, ast.UAdd) else -v
    raise ValueError("unsupported expression")


def recompute(claim: dict) -> float:
    if claim["kind"] == "arithmetic":
        if len(claim["input"]) > 200:
            raise ValueError("expression too long")
        return _eval(ast.parse(claim["input"], mode="eval"))
    if claim["kind"] == "word_count":
        return len(claim["input"].split())
    raise ValueError(f"unknown claim kind {claim['kind']}")


# ---- Scoring (shared with audit.py) -------------------------------------
def compute_score(checks: list[dict]) -> float:
    """Severity-weighted share of non-skipped checks that passed."""
    applicable = [c for c in checks if c["status"] != "skipped"]
    total = sum(SEVERITY_WEIGHTS[c["severity"]] for c in applicable)
    if total == 0:
        return 0.0
    passed = sum(SEVERITY_WEIGHTS[c["severity"]] for c in applicable if c["status"] == "pass")
    return round(passed / total, 4)


def derive_verdict(checks: list[dict]) -> str:
    failed = [c for c in checks if c["status"] == "fail"]
    if any(c["severity"] == "critical" for c in failed):
        return "fail"
    return "needs_attention" if failed else "pass"


# ---- Checks -------------------------------------------------------------
def _check(check_id, description, severity, status, detail, step_ids=()):
    return {"check_id": check_id, "description": description, "severity": severity,
            "status": status, "evidence_step_ids": list(step_ids), "detail": detail}


def _final_answer_present(execution, evidence):
    ok = bool(evidence["has_final_answer"])
    return _check("final_answer_present", "The run ended with a final answer.", "critical",
                  "pass" if ok else "fail",
                  "Final answer present." if ok else "The run ended without a final answer.")


def _no_step_errors(execution, evidence):
    errs = evidence["errors"]
    if not errs:
        return _check("no_step_errors", "No step reported an error.", "critical", "pass",
                      "All steps completed without errors.")
    detail = "; ".join(f"step {e['step_id']}: {e['message']}" for e in errs)
    return _check("no_step_errors", "No step reported an error.", "critical", "fail",
                  f"{len(errs)} step(s) errored: {detail}.", [e["step_id"] for e in errs])


def _step_ids_consecutive(execution, evidence):
    ids = [s["step_id"] for s in execution["steps"]]
    bad = [sid for i, sid in enumerate(ids, start=1) if sid != i]
    return _check("trace_step_ids_consecutive", "Trace step ids are 1-based and consecutive.",
                  "warning", "fail" if bad else "pass",
                  f"Unexpected step ids: {bad}." if bad else f"{len(ids)} step(s) in order.", bad)


def _tool_results_verified(execution, evidence):
    desc = "Tool outputs match an independent re-computation."
    claims = evidence["verifiable_claims"]
    if not claims:
        return _check("tool_results_independently_verified", desc, "critical", "skipped",
                      "No verifiable tool outputs in this run.")
    mismatches = []
    for c in claims:
        try:
            expected = recompute(c)
        except (ValueError, SyntaxError, ZeroDivisionError) as exc:
            mismatches.append((c["step_id"], f"could not re-compute ({exc})"))
            continue
        if not math.isclose(expected, c["claimed_result"], rel_tol=1e-9, abs_tol=1e-9):
            mismatches.append((c["step_id"], f"tool said {c['claimed_result']:g}, re-computed {expected:g}"))
    if mismatches:
        detail = "; ".join(f"step {sid}: {msg}" for sid, msg in mismatches)
        return _check("tool_results_independently_verified", desc, "critical", "fail",
                      detail, [sid for sid, _ in mismatches])
    return _check("tool_results_independently_verified", desc, "critical", "pass",
                  f"{len(claims)} tool output(s) re-computed and matched.", [c["step_id"] for c in claims])


def _answer_matches_tools(execution, evidence):
    desc = "The final answer states the value the tool returned."
    claims = evidence["verifiable_claims"]
    answer = evidence["final_answer"]
    if not claims or answer is None:
        return _check("final_answer_matches_tool_results", desc, "critical", "skipped",
                      "Nothing to compare (no tool outputs or no final answer).")
    missing = []
    for c in claims:
        # Remove the echoed input first so numbers inside the question don't count.
        stated = [float(n) for n in _NUMBER_RE.findall(answer.replace(c["input"], ""))]
        if not any(math.isclose(v, c["claimed_result"], rel_tol=1e-9, abs_tol=1e-9) for v in stated):
            missing.append(c)
    if missing:
        detail = "; ".join(f"step {c['step_id']}: tool returned {c['claimed_result']:g}, "
                           f"answer states {', '.join(_NUMBER_RE.findall(answer.replace(c['input'], ''))) or 'no number'}"
                           for c in missing)
        return _check("final_answer_matches_tool_results", desc, "critical", "fail",
                      detail, [c["step_id"] for c in missing])
    return _check("final_answer_matches_tool_results", desc, "critical", "pass",
                  "Final answer states the tool result(s).", [c["step_id"] for c in claims])


def _latency(execution, evidence, budget_ms):
    desc = f"Total run time is within {budget_ms:g} ms."
    total = evidence["total_duration_ms"]
    ok = total <= budget_ms
    return _check("latency_within_budget", desc, "warning", "pass" if ok else "fail",
                  f"Run took {total:g} ms (budget {budget_ms:g} ms).")


def _factual_evidence_contract_satisfied(execution, evidence):
    """Require factual QA evidence with declared status and sources."""
    records = evidence.get("factual_evidence") or []
    valid = bool(records) and all(
        item.get("verification_status") == "verified"
        and bool(item.get("sources"))
        and isinstance(item.get("step_id"), int)
        and item.get("step_id") > 0
        for item in records
    )

    step_ids = [
        item["step_id"] for item in records
        if isinstance(item.get("step_id"), int) and item["step_id"] > 0
    ]

    detail = (
        f"{len(records)} factual evidence record(s) have verified status and sources."
        if valid else
        "Factual evidence is missing, unsourced, or lacks declared verified status."
    )

    return _check(
        "factual_evidence_contract_satisfied",
        "Factual answers have evidence records with declared verification status and sources.",
        "critical",
        "pass" if valid else "fail",
        detail,
        step_ids,
    )


# ---- Entry point --------------------------------------------------------
def evaluate(execution: dict, evidence: dict, *, latency_budget_ms: float = 5000.0) -> dict:
    """Run all checks. Returns a review without audit/trust/improvements yet."""
    checks = [
        _final_answer_present(execution, evidence),
        _no_step_errors(execution, evidence),
        _step_ids_consecutive(execution, evidence),
        _tool_results_verified(execution, evidence),
        _answer_matches_tools(execution, evidence),
        _latency(execution, evidence, latency_budget_ms),
    ]

    is_factual = (
        "factual_qa" in evidence.get("tools_used", [])
        or bool(evidence.get("factual_evidence"))
    )
    if is_factual:
        checks.append(_factual_evidence_contract_satisfied(execution, evidence))

    return {
        "review_id": f"rev_{uuid.uuid4().hex[:12]}",
        "execution_id": execution["execution_id"],
        "reviewer": dict(REVIEWER_INFO),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "score": compute_score(checks),
        "verdict": derive_verdict(checks),
    }
