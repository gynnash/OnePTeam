"""Developer Agent - implements code based on architecture design."""
from crewai import Agent

from onep.agents.registry import register
from onep.tools.filesystem import FileReadTool, FileWriteTool, FileListTool
from onep.tools.shell import ShellTool
from onep.tools.lint import LintTool
from onep.tools.grep import GrepTool
from onep.tools.edit import EditTool
from onep.tools.memory import MemoryTool


_PROFILES = {
    "greenfield": {
        "goal": "Implement the approved architecture as a complete runnable project.",
        "backstory": (
            "You build new applications from approved product and architecture documents. "
            "Create only the components required by those documents and verify the result."
        ),
    },
    "brownfield": {
        "goal": "Implement the approved optimization as a minimal, verified patch.",
        "backstory": (
            "You work in an existing repository. Reuse its conventions and abstractions, "
            "avoid unrelated dependencies and refactors, and keep changes within Plan scope."
        ),
    },
    "repair": {
        "goal": "Repair the current patch using the supplied gate evidence.",
        "backstory": (
            "Preserve changes that already satisfy the Plan. Diagnose the structured failure, "
            "make the smallest corrective edit, and stop when the required gates pass."
        ),
    },
}


@register("developer")
def create_developer(
    workspace: str = "", source_id: str = "", mode: str = "greenfield"
) -> Agent:
    if mode not in _PROFILES:
        raise ValueError(f"Unknown developer mode: {mode}")
    profile = _PROFILES[mode]
    tools = [MemoryTool(default_source_id=source_id)]
    if workspace:
        tools = [
            FileReadTool(workspace=workspace),
            FileWriteTool(workspace=workspace),
            FileListTool(workspace=workspace),
            ShellTool(workspace=workspace),
            LintTool(workspace=workspace),
            GrepTool(workspace=workspace),
            EditTool(workspace=workspace),
            MemoryTool(default_source_id=source_id),
        ]

    return Agent(
        role="研发工程师",
        goal=profile["goal"],
        backstory=profile["backstory"],
        tools=tools,
        verbose=True,
        allow_delegation=False,
        max_iter=10,
    )
