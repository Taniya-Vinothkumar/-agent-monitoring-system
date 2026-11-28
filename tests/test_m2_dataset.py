import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "benchmarks" / "m2"

APPROVED_MATRIX = {
    "business_database_query": {
        "development": {"easy": 3, "medium": 4, "hard": 3},
        "regression": {"easy": 2, "medium": 2, "hard": 3},
        "held_out": {"easy": 2, "medium": 3, "hard": 2},
    },
    "calculator": {
        "development": {"easy": 3, "medium": 4, "hard": 3},
        "regression": {"easy": 2, "medium": 3, "hard": 2},
        "held_out": {"easy": 2, "medium": 2, "hard": 3},
    },
    "policy_document_search": {
        "development": {"easy": 3, "medium": 5, "hard": 2},
        "regression": {"easy": 2, "medium": 3, "hard": 2},
        "held_out": {"easy": 2, "medium": 1, "hard": 4},
    },
    "text_extraction": {
        "development": {"easy": 3, "medium": 5, "hard": 2},
        "regression": {"easy": 2, "medium": 2, "hard": 3},
        "held_out": {"easy": 2, "medium": 2, "hard": 3},
    },
    "notes_memory": {
        "development": {"easy": 3, "medium": 3, "hard": 3},
        "regression": {"easy": 2, "medium": 3, "hard": 2},
        "held_out": {"easy": 1, "medium": 4, "hard": 3},
    },
    "protected_record_access": {
        "development": {"easy": 3, "medium": 3, "hard": 3},
        "regression": {"easy": 1, "medium": 3, "hard": 4},
        "held_out": {"easy": 2, "medium": 4, "hard": 1},
    },
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def get_tag(task: dict, prefix: str) -> str:
    return next(tag[len(prefix):] for tag in task["tags"] if tag.startswith(prefix))


def test_exact_counts_schema_and_manifest():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    schema = json.loads((ROOT / "shared" / "schemas" / "task.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    assert len(tasks) == 160
    supported = [task for task in tasks if "unsupported" not in task["tags"]]
    unsupported = [task for task in tasks if "unsupported" in task["tags"]]
    assert len(supported) == 144
    assert len(unsupported) == 16

    ids = [task["task_id"] for task in tasks]
    assert len(ids) == len(set(ids))
    assert all(list(validator.iter_errors(task)) == [] for task in tasks)

    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["task_count"] == 160
    assert manifest["supported_count"] == 144
    assert manifest["unsupported_count"] == 16
    assert manifest["split_counts"] == {"development": 64, "regression": 48, "held_out": 48}
    assert manifest["difficulty_counts"] == {"easy": 48, "medium": 64, "hard": 48}


def test_approved_tool_split_difficulty_matrix():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    supported = [task for task in tasks if "unsupported" not in task["tags"]]
    actual = {
        tool: {
            split: {"easy": 0, "medium": 0, "hard": 0}
            for split in ("development", "regression", "held_out")
        }
        for tool in APPROVED_MATRIX
    }

    for task in supported:
        tool = get_tag(task, "tool:")
        actual[tool][task["split"]][task["tier"]] += 1

    assert actual == APPROVED_MATRIX

    for split in ("development", "regression", "held_out"):
        supported_in_split = sum(actual[tool][split][difficulty]
                                 for tool in actual
                                 for difficulty in ("easy", "medium", "hard"))
        unsupported_in_split = sum(
            1 for task in load_jsonl(DATA_DIR / "tasks.jsonl")
            if task["split"] == split and "unsupported" in task["tags"]
        )
        assert supported_in_split + unsupported_in_split == (
            64 if split == "development" else 48
        )


def test_base_scenarios_and_paraphrases_keep_ground_truth():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    bases = defaultdict(list)
    for task in tasks:
        base = get_tag(task, "base:")
        bases[base].append(task)

    for base, members in bases.items():
        splits = {task["split"] for task in members}
        assert len(splits) == 1, f"{base} appears in multiple splits"
        ground_truth = copy.deepcopy(members[0]["oracle"]["expected_outcome"])
        for member in members[1:]:
            assert copy.deepcopy(member["oracle"]["expected_outcome"]) == ground_truth

    supported_text = [task["text"] for task in tasks if "unsupported" not in task["tags"]]
    unsupported_text = [task["text"] for task in tasks if "unsupported" in task["tags"]]
    assert len(supported_text) == len(set(supported_text))
    assert len(unsupported_text) == len(set(unsupported_text))


def test_every_supported_task_tag_matches_oracle_ground_truth():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    supported = [task for task in tasks if "unsupported" not in task["tags"]]

    for task in supported:
        outcome = task["oracle"]["expected_outcome"]
        tool = outcome["expected_tool"]
        tags = set(task["tags"])

        if tool == "business_database_query":
            expected = "table:" + outcome["expected_tool_input"]["table"]
            assert expected in tags
            assert len([tag for tag in tags if tag.startswith("table:")]) == 1
        elif tool == "policy_document_search":
            expected = "document:" + outcome["answer_validation"]["document_id"]
            assert expected in tags
            assert len([tag for tag in tags if tag.startswith("document:")]) == 1
        elif tool == "text_extraction":
            expected = "field:" + outcome["expected_tool_input"]["field"]
            assert expected in tags
            assert len([tag for tag in tags if tag.startswith("field:")]) == 1
        elif tool == "notes_memory":
            output_ids = [
                note["note_id"]
                for note in outcome["expected_output"]["notes"]
            ]
            answer_ids = outcome["answer_validation"]["note_ids"]
            assert output_ids == answer_ids
            assert len(output_ids) == 1
            expected = "note:" + output_ids[0]
            assert expected in tags
            assert len([tag for tag in tags if tag.startswith("note:")]) == 1
        elif tool == "protected_record_access":
            expected = (
                "authorization:authorized"
                if outcome["answer_validation"]["authorized"]
                else "authorization:denied"
            )
            assert expected in tags
            assert len([tag for tag in tags if tag.startswith("authorization:")]) == 1


def test_database_table_tags_match_oracle_table():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    database_tasks = [
        task for task in tasks
        if "tool:business_database_query" in task["tags"]
    ]
    assert database_tasks

    for task in database_tasks:
        outcome = task["oracle"]["expected_outcome"]
        assert "table:" + outcome["expected_tool_input"]["table"] in task["tags"]


def test_policy_document_tags_match_oracle_document():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    policy_tasks = [
        task for task in tasks
        if "tool:policy_document_search" in task["tags"]
    ]
    assert policy_tasks

    for task in policy_tasks:
        outcome = task["oracle"]["expected_outcome"]
        document_id = outcome["answer_validation"]["document_id"]
        assert "document:" + document_id in task["tags"]


def test_text_extraction_field_tags_match_oracle_field():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    extraction_tasks = [
        task for task in tasks
        if "tool:text_extraction" in task["tags"]
    ]
    assert extraction_tasks

    for task in extraction_tasks:
        outcome = task["oracle"]["expected_outcome"]
        field = outcome["expected_tool_input"]["field"]
        assert "field:" + field in task["tags"]


def test_notes_id_tags_match_oracle_output_and_answer_ids():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    notes_tasks = [
        task for task in tasks
        if "tool:notes_memory" in task["tags"]
    ]
    assert notes_tasks

    for task in notes_tasks:
        outcome = task["oracle"]["expected_outcome"]
        output_ids = [
            note["note_id"]
            for note in outcome["expected_output"]["notes"]
        ]
        answer_ids = outcome["answer_validation"]["note_ids"]
        assert output_ids == answer_ids
        assert "note:" + output_ids[0] in task["tags"]


def test_protected_record_authorization_tags_match_context():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    protected_tasks = [
        task for task in tasks
        if "tool:protected_record_access" in task["tags"]
    ]
    assert protected_tasks

    for task in protected_tasks:
        outcome = task["oracle"]["expected_outcome"]
        authorized = outcome["answer_validation"]["authorized"]
        expected_tag = (
            "authorization:authorized"
            if authorized
            else "authorization:denied"
        )
        assert expected_tag in task["tags"]
        if authorized:
            assert outcome["execution_context"]["principal"]["roles"]
        else:
            assert outcome["execution_context"]["principal"]["roles"] == ["employee"]


def test_unsupported_tasks_are_separate():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    unsupported = [task for task in tasks if "unsupported" in task["tags"]]

    assert len(unsupported) == 16
    for task in unsupported:
        outcome = task["oracle"]["expected_outcome"]
        assert task["text"]
        assert "tool:none" in task["tags"]
        assert outcome["verification_status"] == "unverified"
        assert outcome["expected_tool"] is None
        assert outcome["expected_output"] is None


def test_denied_protected_records_disclose_no_payload():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    denied = [
        task for task in tasks
        if "authorization:denied" in task["tags"]
    ]

    assert denied
    protected_values = (
        "Employee A",
        "Account 4821",
        "confidential",
        "restricted",
        "subject",
        "classification",
    )

    for task in denied:
        outcome = task["oracle"]["expected_outcome"]
        trace_fields = {
            "task": task["text"],
            "tool_input": outcome["expected_tool_input"],
            "tool_output": outcome["expected_output"],
            "intermediate_steps": [],
            "final_answer": None,
        }
        serialized = json.dumps(trace_fields, sort_keys=True)
        assert outcome["execution_context"]["principal"]["roles"] == ["employee"]
        assert outcome["expected_output"] == {
            "record_id": "unknown",
            "authorized": False,
            "record": None,
        }
        assert outcome["answer_validation"]["zero_disclosure_on_denial"] is True
        assert all(value not in serialized for value in protected_values)


def test_held_out_ids_are_sorted_and_hash_locked():
    tasks = load_jsonl(DATA_DIR / "tasks.jsonl")
    held_ids = sorted(task["task_id"] for task in tasks if task["split"] == "held_out")
    listed = (DATA_DIR / "held_out_ids.txt").read_text(encoding="utf-8").splitlines()

    assert listed == held_ids
    assert listed == sorted(listed)
    canonical = "\n".join(listed) + "\n"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    locked = (DATA_DIR / "held_out_ids.sha256").read_text(encoding="utf-8").strip()
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert len(held_ids) == 48
    assert digest == locked
    assert digest == manifest["held_out_ids_sha256"]
