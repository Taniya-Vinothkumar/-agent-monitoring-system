"""Reviewer validation (Person 2). STATUS: REAL.

Validates dicts against the shared JSON schemas. The reviewer calls this on
its own output before returning it, so a schema violation fails loudly in the
reviewer instead of surfacing later in the API or frontend.
"""
import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "shared" / "schemas"


class SchemaValidationError(ValueError):
    def __init__(self, schema_name: str, errors: list[str]):
        super().__init__(f"{schema_name} failed validation: " + "; ".join(errors))
        self.schema_name = schema_name
        self.errors = errors


@lru_cache
def _validator(schema_name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{schema_name}.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def schema_errors(instance: dict, schema_name: str) -> list[str]:
    """Return human-readable errors ([] when valid). schema_name: execution | evidence | reviewer."""
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in sorted(_validator(schema_name).iter_errors(instance), key=lambda e: list(map(str, e.path)))
    ]


def _validate(instance: dict, schema_name: str) -> None:
    errors = schema_errors(instance, schema_name)
    if errors:
        raise SchemaValidationError(schema_name, errors)


def validate_review(review: dict) -> None:
    _validate(review, "reviewer")


def validate_execution(execution: dict) -> None:
    _validate(execution, "execution")


def validate_evidence(evidence: dict) -> None:
    _validate(evidence, "evidence")
