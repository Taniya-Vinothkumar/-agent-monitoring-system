"""Agent execution and task handling (Person 1)."""
import pytest

from backend.app.agent.executor import MockAgentExecutor
from backend.app.agent.task_handler import ToolError, calculator, extract_expression, plan_task, text_stats
from backend.app.api.schemas import TaskRequest


def test_calculator_basic_and_precedence():
    assert calculator("(12 + 8) * 3 / 4") == {"result": 15}
    assert calculator("2 + 3 * 4") == {"result": 14}
    assert calculator("1 / 3") == {"result": 0.3333333333}


@pytest.mark.parametrize("bad", ["1 / 0", "2 **", "__import__('os')", "abs(1)", "1 +"])
def test_calculator_rejects_bad_input(bad):
    with pytest.raises(ToolError):
        calculator(bad)


def test_text_stats():
    assert text_stats("the quick brown fox") == {"word_count": 4, "char_count": 19, "longest_word": "quick"}
    assert text_stats("")["word_count"] == 0


def test_planner_routes_tasks():
    assert extract_expression("What is (12 + 8) * 3 / 4?") == "(12 + 8) * 3 / 4"
    assert plan_task("What is 2 + 2?").tool == "calculator"
    plan = plan_task("Count the words in: hello big world")
    assert plan.tool == "text_stats" and plan.tool_input == {"text": "hello big world"}


def test_executor_completes_arithmetic_task():
    trace = MockAgentExecutor().run(TaskRequest(task="What is (12 + 8) * 3 / 4?"))
    assert trace.status == "completed"
    assert [s.type for s in trace.steps] == ["plan", "tool_call", "final_answer"]
    assert "15" in trace.final_answer
    assert trace.agent.mode == "mock_rule_based"


def test_executor_records_tool_failure():
    trace = MockAgentExecutor().run(TaskRequest(task="Compute 10 / 0"))
    assert trace.status == "failed" and trace.final_answer is None
    assert trace.steps[-1].status == "error" and "division by zero" in trace.steps[-1].error


def test_fault_injection_changes_the_run():
    wrong = MockAgentExecutor().run(TaskRequest(task="What is 2 + 2?", fault_injection="wrong_tool_result"))
    assert wrong.steps[1].output["result"] == 5
    inconsistent = MockAgentExecutor().run(TaskRequest(task="What is 2 + 2?", fault_injection="inconsistent_answer"))
    assert inconsistent.steps[1].output["result"] == 4 and "5" in inconsistent.final_answer
