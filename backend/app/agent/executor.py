"""Agent execution (Person 1).

STATUS: MOCK. This is a deterministic, rule-based stand-in for a real agent
(no LLM). What is real is the plumbing: every step is recorded through
TraceRecorder, and the tools it calls (task_handler.TOOLS) do real work.
Replace `MockAgentExecutor.run` with a real agent later; keep the signature
(TaskRequest -> ExecutionTrace) and nothing else in the system changes.

`fault_injection` is TEST-ONLY. It corrupts the run on purpose so the
reviewer has real errors to detect:
  wrong_tool_result    the tool's recorded output is off by one
  inconsistent_answer  the final answer states a number different from the tool's
"""
from backend.app.agent.task_handler import TOOLS, plan_task
from backend.app.api.schemas import AgentInfo, ExecutionTrace, TaskRequest
from backend.app.monitoring.trace_recorder import TraceRecorder

AGENT = AgentInfo(name="mock-rule-based-agent", version="0.1.0", mode="mock_rule_based")


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.10g}"


class MockAgentExecutor:
    def run(self, request: TaskRequest) -> ExecutionTrace:
        recorder = TraceRecorder(request.task, AGENT, request.fault_injection)

        with recorder.step("plan", "rule_based_planner", {"task": request.task}) as step:
            plan = plan_task(request.task)
            step.output = plan.to_dict()

        try:
            with recorder.step("tool_call", plan.tool, plan.tool_input) as step:
                result = TOOLS[plan.tool](**plan.tool_input)

                if request.fault_injection == "wrong_tool_result":
                    if plan.kind == "arithmetic":
                        result["result"] += 1
                    elif plan.kind == "text_stats":
                        result["word_count"] += 1

                step.output = result
        except Exception:
            return recorder.finalize(final_answer=None)

        if plan.kind == "arithmetic":
            stated = result["result"]
            if request.fault_injection == "inconsistent_answer":
                stated += 1
            answer = (
                f"The result of {plan.tool_input['expression']} is "
                f"{_format_number(stated)}."
            )
        elif plan.kind == "text_stats":
            stated = result["word_count"]
            if request.fault_injection == "inconsistent_answer":
                stated += 1
            answer = f"The text contains {_format_number(stated)} words."
        elif plan.kind == "factual_qa":
            answer = result["answer"].strip()
            sources = result.get("sources", [])
            if sources:
                source_lines = [
                    f"- {source['title']}: {source['url']}"
                    for source in sources
                ]
                answer += "\n\nSources:\n" + "\n".join(source_lines)

            status = result.get("verification_status", "unverified")
            if status != "verified":
                answer += (
                    "\n\nVerification status: "
                    f"{status}. This answer has not been independently verified."
                )
        else:
            raise ValueError(f"Unsupported task kind: {plan.kind}")

        with recorder.step("final_answer", "compose_answer", {"tool_result": result}) as step:
            step.output = {"text": answer}

        return recorder.finalize(final_answer=answer)
