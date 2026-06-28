# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable) with dev dependencies
pip install -e ".[dev]"

# Run full test suite (175 tests)
pytest tests/ -v

# Run a single test file
pytest tests/test_strategy/test_scanner.py -v

# Run a single test
pytest tests/test_strategy/test_scanner.py::test_walk_files_skips_git_and_cache -v

# Run CLI (after install)
python -m onep.main --help
onep --help
```

No lint or build step is configured. The `onep` package has no external build artifacts.

## Architecture

OnePTeam is a CLI tool that orchestrates AI agents as a virtual software development team. It has 6 main subsystems:

### CLI Layer (`onep/cli/`)

Click commands auto-discovered via `COMMANDS` list export:

| Module | Command | Purpose |
|--------|---------|---------|
| `analyze.py` | `onep analyze` | Brownfield analysis entry point (3-layer pipeline) |
| `optimize_cmd.py` | `onep optimize` | Automated optimize loop with safety gates |
| `export_cmd.py` | `onep export` | Export analysis results as Markdown/JSON |
| `create.py` | `onep create` / `onep run` | Greenfield project creation + pipeline |
| `status.py` | `onep status` / `pause` / `resume` / `approve` / `reject` / `delete` | Pipeline control |
| `show.py` | `onep show` | View project artifacts |
| `strategy_cmd.py` | `onep strategy` | Manage strategy analysis sessions |
| `memory_cmd.py` | `onep memory` | Memory system management |

### Orchestrator Layer (`onep/orchestrator/`)

- `greenfield.py` — Greenfield 6-stage pipeline (PM → Designer → Architect → Developer → Tester → DevOps). Stage prompts + agent mapping.
- `brownfield.py` — Brownfield scan/analyze prompts (SCAN_PROMPT, SCAN_PROMPT_FULL, RECHECK_PROMPT, ANALYZE_PROMPT).
- `runner.py` — Greenfield pipeline runner. Each stage invokes LLM via `_invoke_agent()`, saves output.
- `crew.py` — Crew factory (builds CrewAI Crew objects, used mainly by Greenfield).

### Agent Layer (`onep/agents/`)

8 agents registered via `@register("name")` decorator. All factories accept `workspace` and `source_id` kwargs for tool initialization. Key agent:

- **strategy_architect** — Complex model. Tools: FileReadTool, FileListTool, GrepTool, MemoryTool. Used in Brownfield Layer 2 analysis, plan generation, and workbench dialogue.
- **developer** — Default model for ordinary development; Optimize routes the same tool-enabled persona through the `optimize_developer` complex stage.
- **code_reviewer** — Complex model, tool-free and read-only. Returns structured blocking findings for the Optimize gate.
- **analyzer** — Default model. Tools: FileReadTool, FileListTool, MemoryTool. Used in Layer 1 scanning.

### Strategy Analysis (`onep/strategy/`)

The Brownfield subsystem, now multi-layer with production features:

- `scanner.py` — File walking, token-aware content sub-batching, JSONL parsing. Every file and large-file tail is covered.
- `scan_cache.py` — Hash-based file scan result cache. Skips LLM re-classification for unchanged files.
- `analyzer.py` — JSONL parsing from LLM responses. Streaming parse for Layer 2 output.
- `workbench.py` — Interactive dialogue with slash commands (list, focus, plan, execute, rescan, export, etc.).
- `planner.py` — Optimization plan generation (standard/full versions).
- `persistence.py` — YAML (workbench.yaml) + JSONL (dialogue.jsonl).
- `pipeline_state.py` — State machine for analyze pipeline (INIT→SCANNING→SCAN_DONE→ANALYZING→ANALYZE_DONE→DIALOGUE_ACTIVE→COMPLETED). Persists to YAML checkpoint.
- `optimize_engine.py` — One LLM-led development attempt using the tool loop; it never decides whether tests passed.
- `optimize_coordinator.py` — Up to three develop → real test → read-only review → repair attempts. Commits only after both gates pass.
- `git_session.py` — Clean-repository preflight, same-baseline Plan worktree groups, one-commit rule, integration cherry-pick, and verified rollback.
- `optimize_recorder.py` — Durable run state/events and Plan artifacts outside disposable branches.
- `plan_scheduler.py` — Stable fingerprints, convergence, dependency/risk conflicts, parallel development groups, and deterministic integration order.
- `reporting.py` — Shared Markdown/JSON reports for Analyze, Workbench, and export.
- `retry.py` — LLM call retry with exponential backoff for transient errors.
- `project_context.py` — Auto-generates project overview (tech stack, conventions), injects into all LLM calls.

### Tool Layer (`onep/tools/`)

All tools inherit from `crewai.tools.BaseTool`. Workspace-scoped with path validation:

| Tool | `_run` signature | Used by |
|------|-----------------|---------|
| `FileReadTool` | `path: str` | all agents |
| `FileWriteTool` | `path: str, content: str` | developer, architect, tester |
| `FileListTool` | `path: str = "."` | strategy_architect, developer |
| `EditTool` | `path, old_string, new_string, replace_all=False` | developer, architect |
| `GrepTool` | `pattern, path=".", max_results=30` | developer, architect, tester, strategy_architect |
| `ShellTool` | `command, timeout=120` | developer, tester, devops |
| `LintTool` | `path = "."` | developer |
| `GitTool` | `operation, message="", paths="."` | CLI (create, runner) |
| `DockerTool` | `operation, url=""` | devops |
| `MemoryTool` | `operation, query, title, content` | all agents |

`ShellTool` has a built-in deny-list for destructive commands (rm -rf, sudo, git push --force, etc.).

### LLM Layer (`onep/llm/`)

- `adapters.py` — `LLMAdapter` with three methods:
  - `invoke()` — Non-streaming LLM call
  - `invoke_stream()` — Token-by-token streaming
  - `invoke_with_tools_stream()` — Custom tool-calling loop with streaming. Handles tool call detection, execution, and result feeding. Replaces CrewAI's `kickoff()`.
- `router.py` — Model routing based on stage name. COMPLEX_STAGES get complex_model, others get default_model.
- `cost.py` — Cost estimation + `CostTracker` with budget enforcement.

### Memory System (`onep/memory/`)

SQLite-based persistent memory with hybrid search:

- `schema.py` — memory_entries table + FTS5 virtual table.
- `embeddings.py` — Embedding generation via LiteLLM. NullEmbedder fallback.
- `manager.py` — `MemoryManager` with capture/search/status/clean.
- `search.py` — Hybrid search (cosine + BM25 + MMR + temporal decay).
- `hooks.py` — Fire-and-forget capture points for pipeline lifecycle.
- `context.py` — `MemoryContextBuilder` for injecting relevant memories into LLM context.

### Persistence (`onep/persistence/`)

- `database.py` — SQLite (`~/.onep/meta.db`) for project metadata. CRUD + delete.
- `models.py` — `Project`, `PipelineState`, `StageRun`, `Approval`. `IMPACT_RULES` for deterministic impact classification.
- `state.py` — YAML state file load/save.

## Key Patterns

- **CLI auto-discovery**: Modules in `onep/cli/` export a `COMMANDS` list, auto-registered by `main.py`.
- **Agent registry**: `@register("name")` decorator. `get_agent(name, workspace=..., source_id=...)` creates agent with tools.
- **Tool calling loop**: `invoke_with_tools_stream()` in adapters.py is our own implementation (~150 lines). Handles streaming + tool call detection + execution. Used instead of `crew.kickoff()` for single-agent tasks.
- **Streaming everywhere**: Layer 2 analysis, `/execute`, workbench dialogue all stream tokens in real-time.
- **Checkpoint persistence**: Pipeline state saved to YAML after each state change. Layer 1 results persisted to JSONL incrementally.
- **Token usage display**: Every LLM call prints prompt/completion/total tokens via `display_usage()`.
- **Path validation**: All tools validate paths within workspace via `Path.resolve()` prefix check.

## Configuration

- `~/.onep/config.yaml` — Auto-created. Model routing, pricing, pipeline settings.
- `.env` (project root, gitignored) — API keys. Loaded by `onep/config.py`. Also checked in package project root.
- `pyproject.toml` — Package metadata. Entry point: `onep = "onep.main:cli"`.
- `~/.onep/memory/memory.db` — Memory system database.
- `~/.onep/projects/<name>/workspace/` — Per-project workspace with pipeline_state.yaml, scan_cache.jsonl, project_context.md, etc.
