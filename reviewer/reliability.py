"""Reviewer reliability measurement and evidence-based trust gate."""

from __future__ import annotations

import math
from typing import Any

DEFAULT_MIN_SAMPLES_PER_CATEGORY = 10
DEFAULT_MIN_CLEAN_CONTROLS = 10
DEFAULT_MIN_DETECTION_RATE = 0.80
DEFAULT_MAX_FALSE_ALARM_RATE = 0.10


def _valid_rate(value: Any) -> bool:
    """Return True only for finite numeric rates between zero and one."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0.0 <= value <= 1.0
    )


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _group_valid_records(records: list, reviewer_name: str, category: Any):
    """Group records by scenario fingerprint, requiring source provenance."""
    groups: dict[str, list] = {}

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("reviewer") != reviewer_name:
            continue
        if record.get("category") != category:
            continue

        fingerprint = record.get("scenario_fingerprint")
        source = record.get("source_fingerprint")

        if not isinstance(fingerprint, str) or not fingerprint:
            continue
        if not isinstance(source, str) or not source:
            continue

        groups.setdefault(fingerprint, []).append(record)

    return groups


def build_reviewer_reliability(
    canary_result: dict[str, Any],
    *,
    min_samples_per_category: int = DEFAULT_MIN_SAMPLES_PER_CATEGORY,
    min_clean_controls: int = DEFAULT_MIN_CLEAN_CONTROLS,
    min_detection_rate: float = DEFAULT_MIN_DETECTION_RATE,
    max_false_alarm_rate: float = DEFAULT_MAX_FALSE_ALARM_RATE,
) -> dict[str, Any]:
    """Calculate reliability from distinct, provenance-bearing canary records.

    Aggregate counters and caller-supplied diversity claims are not used
    to establish independent evidence.
    """
    if min_samples_per_category < 1:
        raise ValueError("min_samples_per_category must be at least 1")
    if min_clean_controls < 1:
        raise ValueError("min_clean_controls must be at least 1")
    if not _valid_rate(min_detection_rate):
        raise ValueError("min_detection_rate must be between 0 and 1")
    if not _valid_rate(max_false_alarm_rate):
        raise ValueError("max_false_alarm_rate must be between 0 and 1")

    if not isinstance(canary_result, dict):
        canary_result = {}

    reviewers = canary_result.get(
        "reviewer_metrics",
        canary_result.get("reviewers", {}),
    )
    if not isinstance(reviewers, dict):
        reviewers = {}

    records = canary_result.get("results", [])
    if not isinstance(records, list):
        records = []

    reviewer_names = set(reviewers)
    reviewer_names.update(
        record.get("reviewer")
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("reviewer"), str)
    )

    output: dict[str, Any] = {
        "method": "distinct_fingerprinted_canary_records",
        "thresholds": {
            "min_samples_per_category": min_samples_per_category,
            "min_clean_controls": min_clean_controls,
            "min_detection_rate": min_detection_rate,
            "max_false_alarm_rate": max_false_alarm_rate,
        },
        "reviewers": {},
    }

    all_diverse = bool(reviewer_names)

    for reviewer_name in sorted(reviewer_names):
        clean_groups = _group_valid_records(records, reviewer_name, None)

        clean_controls = len(clean_groups)
        clean_source_count = len({
            record["source_fingerprint"]
            for group in clean_groups.values()
            for record in group
        })

        false_alarms = sum(
            any(record.get("false_alarm") is True for record in group)
            for group in clean_groups.values()
        )

        false_alarm_rate = (
            round(false_alarms / clean_controls, 4)
            if clean_controls
            else None
        )

        original_metrics = reviewers.get(reviewer_name, {})
        original_categories = (
            original_metrics.get("by_category", {})
            if isinstance(original_metrics, dict)
            else {}
        )
        if not isinstance(original_categories, dict):
            original_categories = {}

        category_names = set(original_categories)
        category_names.update(
            record.get("category")
            for record in records
            if isinstance(record, dict)
            and record.get("reviewer") == reviewer_name
            and isinstance(record.get("category"), str)
        )

        categories: dict[str, Any] = {}

        for category in sorted(category_names):
            groups = _group_valid_records(records, reviewer_name, category)

            sample_count = len(groups)
            source_count = len({
                record["source_fingerprint"]
                for group in groups.values()
                for record in group
            })

            available_groups = [
                group for group in groups.values()
                if all(
                    record.get("status", "completed") == "completed"
                    for record in group
                )
            ]

            unavailable_reviews = sample_count - len(available_groups)

            detections = sum(
                all(record.get("detected") is True for record in group)
                for group in available_groups
            )

            available_samples = len(available_groups)
            missed = available_samples - detections

            detection_rate = (
                round(detections / available_samples, 4)
                if available_samples
                else None
            )

            sufficient_sources = (
                source_count >= min_samples_per_category
            )

            categories[category] = {
                "sample_count": sample_count,
                "independent_source_count": source_count,
                "available_samples": available_samples,
                "detections": detections,
                "missed_detections": missed,
                "unavailable_reviews": unavailable_reviews,
                "observed_detection_rate": detection_rate,
                "sufficient_samples": (
                    sample_count >= min_samples_per_category
                    and sufficient_sources
                ),
                "sufficient_independent_sources": sufficient_sources,
                "meets_detection_threshold": (
                    detection_rate is not None
                    and detection_rate >= min_detection_rate
                ),
            }

            if not sufficient_sources:
                all_diverse = False

        sufficient_clean = (
            clean_controls >= min_clean_controls
            and clean_source_count >= min_clean_controls
        )

        if not sufficient_clean:
            all_diverse = False

        output["reviewers"][reviewer_name] = {
            "clean_controls": clean_controls,
            "independent_clean_source_count": clean_source_count,
            "false_alarms": false_alarms,
            "observed_false_alarm_rate": false_alarm_rate,
            "sufficient_clean_controls": sufficient_clean,
            "categories": categories,
        }

    output["evidence_diversity_confirmed"] = all_diverse
    return output


def evaluate_trust_gate(
    reliability: dict[str, Any],
    reviewer_name: str,
    category: str,
) -> dict[str, Any]:
    """Authorize a reviewer only when independent evidence meets thresholds."""
    reasons: list[str] = []

    reviewers = reliability.get("reviewers", {})
    reviewer = (
        reviewers.get(reviewer_name)
        if isinstance(reviewers, dict)
        else None
    )

    if not isinstance(reviewer, dict):
        return {
            "reviewer": reviewer_name,
            "category": category,
            "authorized": False,
            "status": "insufficient_evidence",
            "reasons": ["Reviewer metrics are missing or invalid."],
        }

    categories = reviewer.get("categories", {})
    category_metrics = (
        categories.get(category)
        if isinstance(categories, dict)
        else None
    )

    if not isinstance(category_metrics, dict):
        return {
            "reviewer": reviewer_name,
            "category": category,
            "authorized": False,
            "status": "insufficient_evidence",
            "reasons": ["Canary metrics for this category are missing."],
        }

    thresholds = reliability.get("thresholds", {})

    if not reviewer.get("sufficient_clean_controls", False):
        reasons.append(
            "Insufficient independent and diverse clean-control evidence."
        )

    false_alarm_rate = reviewer.get("observed_false_alarm_rate")
    max_false_alarm_rate = thresholds.get(
        "max_false_alarm_rate",
        DEFAULT_MAX_FALSE_ALARM_RATE,
    )

    if not _valid_rate(false_alarm_rate):
        reasons.append("False-alarm rate is missing or invalid.")
    elif false_alarm_rate > max_false_alarm_rate:
        reasons.append("False-alarm rate exceeds the permitted threshold.")

    if not category_metrics.get("sufficient_independent_sources", False):
        reasons.append(
            "Insufficient independent and diverse source cases for this category."
        )

    if not category_metrics.get("sufficient_samples", False):
        reasons.append("Insufficient distinct failure samples for this category.")

    detection_rate = category_metrics.get("observed_detection_rate")
    min_detection_rate = thresholds.get(
        "min_detection_rate",
        DEFAULT_MIN_DETECTION_RATE,
    )

    if not _valid_rate(detection_rate):
        reasons.append("Detection rate is missing or invalid.")
    elif detection_rate < min_detection_rate:
        reasons.append("Detection rate is below the required threshold.")

    authorized = not reasons

    return {
        "reviewer": reviewer_name,
        "category": category,
        "authorized": authorized,
        "status": "authorized" if authorized else "blocked",
        "reasons": reasons,
    }
