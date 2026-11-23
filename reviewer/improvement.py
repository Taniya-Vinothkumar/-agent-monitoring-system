"""Controlled improvement (Person 2).

STATUS: PLACEHOLDER. A fixed lookup from failed checks to suggested fixes.
"Controlled" means: it only PROPOSES. Every item has status "proposed" and
requires_human_approval = true, and nothing in this codebase applies them.
"""

SUGGESTIONS = {
    "final_answer_present": "Make the agent always end a run with an explicit final answer, or report why it could not produce one.",
    "no_step_errors": "Inspect the failing step(s) cited in the evidence, add input validation or error handling for that tool, then re-run the task.",
    "trace_step_ids_consecutive": "Fix the trace recorder so step ids are 1-based and consecutive; a gap suggests steps were dropped.",
    "tool_results_independently_verified": "A tool output disagreed with an independent re-computation. Fix or replace that tool before trusting this agent's results.",
    "final_answer_matches_tool_results": "The final answer states a value different from the tool output. Build the answer directly from the tool result instead of re-deriving it.",
    "latency_within_budget": "Profile the slowest step and optimise it, or raise the latency budget if the current one is unrealistic.",
    "audit": "The review failed its own audit. Do not rely on this review; fix the reviewer and re-run it.",
}


def propose_improvements(review: dict) -> list[dict]:
    targets = [c["check_id"] for c in review["checks"] if c["status"] == "fail"]
    if not review["audit"]["passed"]:
        targets.append("audit")
    return [
        {
            "improvement_id": f"imp_{i}",
            "target_check": target,
            "suggestion": SUGGESTIONS[target],
            "requires_human_approval": True,
            "status": "proposed",
        }
        for i, target in enumerate(targets, start=1)
    ]
