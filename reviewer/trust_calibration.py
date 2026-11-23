"""Trust calibration (Person 2).

STATUS: PLACEHOLDER. The arithmetic is real, but the output is NOT empirically
calibrated: there is no ground-truth data yet to calibrate against.

Method ("beta_prior_uncalibrated"): treat severity-weighted check outcomes as
evidence for a Beta(1 + passed_weight, 1 + failed_weight) distribution.
trust.score is its mean; lower/upper are a 95% normal-approximation interval.
Few checks => wide interval.

Two cap rules keep the number honest (ceiling TRUST_CAP = 0.5, and the
interval's upper end moves down to the ceiling too):
  - a critical check failed  -> a run with a verifiably wrong result is never
                                "mostly trusted", whatever its pass rate
  - the review failed audit  -> the review itself cannot be relied on
Both flags in the output say that the rule's condition held.

To replace with real calibration later: keep the output shape (see
shared/schemas/reviewer.json), change only the maths in this file.
"""
import math

from reviewer.evaluator import SEVERITY_WEIGHTS

TRUST_CAP = 0.5


def calibrate_trust(review: dict) -> dict:
    applicable = [c for c in review["checks"] if c["status"] != "skipped"]
    passed_w = sum(SEVERITY_WEIGHTS[c["severity"]] for c in applicable if c["status"] == "pass")
    failed_w = sum(SEVERITY_WEIGHTS[c["severity"]] for c in applicable if c["status"] == "fail")
    a, b = 1 + passed_w, 1 + failed_w
    mean = a / (a + b)
    sd = math.sqrt(a * b / ((a + b) ** 2 * (a + b + 1)))
    lower = max(0.0, mean - 1.96 * sd)
    upper = min(1.0, mean + 1.96 * sd)

    audit_failed = not review["audit"]["passed"]
    critical_failed = any(c["status"] == "fail" and c["severity"] == "critical" for c in applicable)
    if (audit_failed or critical_failed) and mean > TRUST_CAP:
        lower = max(0.0, lower - (mean - TRUST_CAP))
        mean = upper = TRUST_CAP

    return {
        "score": round(mean, 4),
        "lower": round(lower, 4),
        "upper": round(upper, 4),
        "method": "beta_prior_uncalibrated",
        "n_checks": len(applicable),
        "audit_penalty_applied": audit_failed,
        "critical_failure_cap_applied": critical_failed,
    }
