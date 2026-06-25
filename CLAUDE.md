# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable) with dev dependencies
pip install -e ".[dev]"

# Run full test suite (90 tests)
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

OnePTeam is a CLI tool that orchestrates AI agents as a virtual software development team. It has a 5-layer architecture:

**Top to bottom:**

- **CLI layer** (`onep/cli/`) — Click commands auto-discovered via `COMMANDS` list export. Each module exports a list of `click.Command` objects, registered by `onep/main.py` via `register_commands()`.
- **Orchestrator layer** (`onep/orchestrator/`) — Two pipeline modes: Greenfield (6-stage sequential build from requirements) and Brownfield (strategy analysis of existing code). Both defined via stage lists + prompt templates, compiled into `crewai.Crew` objects with `Process.sequential`. The actual execution engine is in `runner.py` (manual stage loop, not CrewAI's `kickoff`).
- **Agent layer** (`onep/agents/`) — Each agent is a `crewai.Agent` factory function registered via `@register("name")` decorator. The registry maps names to factories. Agent persona (role/goal/backstory) is injected at runtime as the LLM system prompt via `_build_agent_system_prompt()` in `analyze.py`.
- **Tool layer** (`onep/tools/`) — Abstract `BaseTool` with workspace-scoped wrappers for filesystem, git (GitPython), shell (subprocess), Docker Compose, and lint (ruff).
- **Persistence layer** (`onep/persistence/`) — SQLite (`~/.onep/meta.db`) for project metadata, YAML (`.onep/state.yaml`) for pipeline runtime state. Git repos are the primary data store for project artifacts.

**Strategy analysis subsystem** (`onep/strategy/`) follows a 3-layer pipeline:
1. `scanner.py` — Filesystem walking, batching, JSONL response parsing (no LLM calls)
2. `analyzer.py` — StrategyItem parsing from LLM JSON responses (no LLM calls)
3. `workbench.py` — Interactive dialogue loop with 11 slash commands, plus plan generation via `planner.py`
4. `persistence.py` — YAML (workbench.yaml) + JSONL (dialogue.jsonl append-only log)

Prompt templates for strategy stages live in `onep/orchestrator/brownfield.py` (`SCAN_PROMPT`, `ANALYZE_PROMPT`), colocated with Greenfield prompts for consistency.

**LLM integration** (`onep/llm/`) — LiteLLM adapter with model routing. API keys: env vars (e.g., `DEEPSEEK_API_KEY`) take priority over `~/.onep/config.yaml`. `.env` is auto-loaded from project root on import via `python-dotenv`.

**Subflows** (`onep/subflows/`) — LangGraph state machines for code review loops and test retry loops. Not yet integrated into the runner.

## Key Patterns

- **Decorator-based registry**: Agents use `@register("name")` to self-register. CLI modules export a `COMMANDS` list for auto-discovery.
- **Enum-backed state machines**: `ItemStatus`, `StageStatus`, `ProjectStatus` enforce valid transitions. Dataclass methods like `start()`, `complete()`, `discard()` bundle state + timestamp updates.
- **LLM-optional fallbacks**: All LLM-dependent functions accept `llm_adapter=None` and return graceful fallback values. Scanner marks all files as strategy-relevant; analyzer returns a placeholder item; workbench still allows slash commands.
- **YAML + JSONL persistence**: Structured state in YAML for random access; dialogue history in JSONL for append-only streaming writes.
- **Path validation**: `FileSystemTool._validate_path()` prevents traversal outside workspace via `Path.resolve()` prefix check.

## Configuration

- `~/.onep/config.yaml` — Auto-created on first run. Holds model routing and pipeline settings.
- `.env` (project root, gitignored) — API keys via env vars. Loaded by `onep/config.py` on import.
- `pyproject.toml` — Package metadata. Entry point: `onep = "onep.main:cli"`.
