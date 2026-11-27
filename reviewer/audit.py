"""Reviewer audit (Person 2).

STATUS: REAL (rule-based). Audits the *review itself*, not the agent: are its
numbers reproducible, does it cite steps that exist, did it skip a required
check? It reuses the scoring helpers from evaluator.py, so it catches
tampering and bookkeeping errors, not a flawed scoring rule.
"""
import math

from reviewer.evaluator import REQUIRED_CHECK_IDS, compute_score, derive_verdict


def _finding(audit_id, description, ok, detail):
    return {"audit_id": audit_id, "status": "pass" if ok else "fail",
            "description": description, "detail": detail}


def audit_review(review: dict, execution: dict, evidence: dict) -> dict:
    checks = review["checks"]
    findings = []

    step_ids = {s["step_id"] for s in execution["steps"]}
    dangling = sorted({i for c in checks for i in c["evidence_step_ids"]} - step_ids)
    findings.append(_finding("evidence_steps_exist", "Every cited step exists in the trace.",
                             not dangling,
                             f"Cited steps not in trace: {dangling}." if dangling else "All cited steps exist."))

    recomputed = compute_score(checks)
    findings.append(_finding("score_reproducible", "The score can be recomputed from the checks.",
                             math.isclose(recomputed, review["score"], abs_tol=1e-6),
                             f"Reported {review['score']}, recomputed {recomputed}."))

    verdict = derive_verdict(checks)
    findings.append(_finding("verdict_consistent", "The verdict follows from the checks.",
                             verdict == review["verdict"],
                             f"Reported '{review['verdict']}', derived '{verdict}'."))

    unexplained = [c["check_id"] for c in checks if c["status"] == "fail" and not c["detail"].strip()]
    findings.append(_finding("failures_explained", "Every failed check has an explanation.",
                             not unexplained,
                             f"No detail for: {unexplained}." if unexplained else "All failures explained."))

    ids = {review["execution_id"], execution["execution_id"], evidence["execution_id"]}
    findings.append(_finding("ids_consistent", "Review, trace and evidence refer to the same execution.",
                             len(ids) == 1, f"Ids seen: {sorted(ids)}."))

    present = {c["check_id"] for c in checks}
    required_ids = list(REQUIRED_CHECK_IDS)

    is_factual = (
        "factual_qa" in evidence.get("tools_used", [])
        or bool(evidence.get("factual_evidence"))
    )
    if is_factual:
        required_ids.append("factual_evidence_contract_satisfied")

    absent = [c for c in required_ids if c not in present]
    findings.append(_finding("required_checks_present", "No required check was dropped.",
                             not absent,
                             f"Missing checks: {absent}." if absent else "All required checks present."))

    return {"passed": all(f["status"] == "pass" for f in findings), "findings": findings}
