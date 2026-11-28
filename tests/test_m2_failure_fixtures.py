import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "benchmarks" / "m2"

CANONICAL_CATEGORIES = {
    "wrong_tool",
    "wrong_calculation",
    "skipped_step",
    "invented_fact",
    "safety",
}


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_failure_fixtures_are_separate_and_link_clean_tasks():
    task_ids = {
        task["task_id"]
        for task in load_jsonl(DATA_DIR / "tasks.jsonl")
    }
    fixtures = load_jsonl(DATA_DIR / "failure_fixtures.jsonl")

    assert fixtures
    assert len({fixture["fixture_id"] for fixture in fixtures}) == len(fixtures)
    assert all(fixture["source_task_id"] in task_ids for fixture in fixtures)
    assert all(fixture["source_task_id"].startswith("M2-") for fixture in fixtures)


def test_failure_mappings_preserve_raw_and_unresolved_status():
    fixtures = load_jsonl(DATA_DIR / "failure_fixtures.jsonl")

    for fixture in fixtures:
        assert fixture["raw_mutation_type"]
        assert fixture["mapping_status"] in {"confirmed", "provisional", "unresolved"}

        if fixture["mapping_status"] == "unresolved":
            assert fixture["canonical_category"] is None
            assert fixture["expected_verification"]["category_is_assignable"] is False

    mappings = {fixture["raw_mutation_type"]: fixture for fixture in fixtures}
    assert mappings["wrong_arguments"]["mapping_status"] == "provisional"
    assert mappings["inconsistent_answer"]["mapping_status"] == "provisional"
    assert mappings["incomplete_answer"]["mapping_status"] == "unresolved"
    assert mappings["unauthorized_record_disclosure"]["mapping_status"] == "unresolved"

    assert mappings["wrong_arguments"]["canonical_category"] is None
    assert mappings["inconsistent_answer"]["canonical_category"] is None
    assert mappings["incomplete_answer"]["canonical_category"] is None
    assert mappings["unauthorized_record_disclosure"]["canonical_category"] is None


def test_five_canonical_categories_remain_unchanged():
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["failure_categories"]) == CANONICAL_CATEGORIES
