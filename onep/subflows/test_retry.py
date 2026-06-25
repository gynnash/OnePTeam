"""Test failure retry loop using LangGraph. Flow: run tests -> check -> fix or escalate (max N rounds)."""
from __future__ import annotations

from typing import TypedDict, Literal
from pathlib import Path

from langgraph.graph import StateGraph, END


class TestRetryState(TypedDict):
    workspace: str
    test_command: str
    test_output: str
    iteration: int
    max_retries: int
    passed: bool
    status: str


def run_tests(state: TestRetryState) -> TestRetryState:
    import subprocess
    result = subprocess.run(
        state["test_command"], shell=True,
        capture_output=True, text=True, cwd=state["workspace"], timeout=300,
    )
    state["test_output"] = result.stdout + "\n" + result.stderr
    state["passed"] = result.returncode == 0
    return state


def decide_after_test(state: TestRetryState) -> Literal["done", "fix", "escalate"]:
    if state["passed"]:
        return "done"
    if state["iteration"] >= state["max_retries"]:
        return "escalate"
    return "fix"


def prepare_fix(state: TestRetryState) -> TestRetryState:
    state["iteration"] += 1
    state["status"] = "fixing"
    return state


def mark_passed(state: TestRetryState) -> TestRetryState:
    state["status"] = "passed"
    return state


def mark_escalated(state: TestRetryState) -> TestRetryState:
    state["status"] = "escalated"
    return state


def build_test_retry_graph() -> StateGraph:
    builder = StateGraph(TestRetryState)
    builder.add_node("run", run_tests)
    builder.add_node("fix", prepare_fix)
    builder.add_node("mark_passed", mark_passed)
    builder.add_node("mark_escalated", mark_escalated)
    builder.set_entry_point("run")
    builder.add_conditional_edges(
        "run", decide_after_test,
        {"done": "mark_passed", "fix": "fix", "escalate": "mark_escalated"},
    )
    builder.add_edge("fix", "run")
    builder.add_edge("mark_passed", END)
    builder.add_edge("mark_escalated", END)
    return builder.compile()


def run_test_loop(workspace: Path, test_command: str, max_retries: int = 3) -> TestRetryState:
    graph = build_test_retry_graph()
    initial_state: TestRetryState = {
        "workspace": str(workspace),
        "test_command": test_command,
        "test_output": "",
        "iteration": 0,
        "max_retries": max_retries,
        "passed": False,
        "status": "running",
    }
    return graph.invoke(initial_state)
