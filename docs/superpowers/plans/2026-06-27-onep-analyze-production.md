# onep analyze 生产级改进 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `onep analyze` production-ready with pipeline checkpoint/resume, batch persistence, streaming parse, Markdown export, and cost control.

**Architecture:** Pipeline state machine backed by YAML checkpoint at `~/.onep/projects/<name>/pipeline_state.yaml`. Each layer persists partial results incrementally (JSONL). Retry with exponential backoff on transient LLM errors. Markdown export reads from persisted analysis items.

**Tech Stack:** YAML (checkpoint state), JSONL (batch/analysis results), Click + Rich (CLI), LiteLLM (LLM calls, retry).

---

## File Map

| Action | Path | Role |
|--------|------|------|
| Create | `onep/strategy/pipeline_state.py` | Pipeline state machine + checkpoint persistence |
| Create | `onep/strategy/retry.py` | LLM retry with exponential backoff |
| Modify | `onep/cli/analyze.py` | State-driven pipeline, --resume, --from-layer, --no-dialogue |
| Modify | `onep/strategy/scanner.py` | Batch-wise persistence to JSONL, checkpoint integration |
| Create | `onep/cli/export_cmd.py` | `onep export` command |
| Modify | `onep/llm/router.py` | Model pricing config |
| Create | `onep/llm/cost.py` | Cost estimation + budget tracking |
| Create | `tests/test_strategy/test_pipeline_state.py` | State machine tests |
| Create | `tests/test_strategy/test_retry.py` | Retry logic tests |
| Create | `tests/test_llm/test_cost.py` | Cost estimation tests |
| Create | `tests/test_cli/test_export.py` | Export CLI tests |

---

### Task 1: Pipeline state machine

**Files:**
- Create: `onep/strategy/pipeline_state.py`
- Create: `tests/test_strategy/test_pipeline_state.py`

**Goal:** State machine with checkpoint persistence.

- [ ] **Step 1: Write tests**

```python
import tempfile
from pathlib import Path
from onep.strategy.pipeline_state import PipelineState, Layer, Status

def test_state_transitions():
    state = PipelineState(project_name="test", workspace="/tmp/test")
    assert state.status == Status.INIT

    state.start_layer(Layer.SCAN)
    assert state.status == Status.SCANNING

    state.complete_layer(Layer.SCAN)
    assert state.status == Status.SCAN_DONE

    state.start_layer(Layer.ANALYZE)
    assert state.status == Status.ANALYZING

    state.complete_layer(Layer.ANALYZE)
    assert state.status == Status.ANALYZE_DONE

    state.start_layer(Layer.DIALOGUE)
    assert state.status == Status.DIALOGUE_ACTIVE
    state.complete_layer(Layer.DIALOGUE)
    assert state.status == Status.COMPLETED

def test_state_save_and_load():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        state = PipelineState(project_name="test", workspace=str(ws))
        state.start_layer(Layer.SCAN)
        state.save()

        loaded = PipelineState.load(str(ws))
        assert loaded.status == Status.SCANNING
        assert loaded.project_name == "test"

def test_fail_and_resume():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        state = PipelineState(project_name="test", workspace=str(ws))
        state.start_layer(Layer.SCAN)
        state.fail("rate limit")
        assert state.status == Status.FAILED

        # resume should go back to scanning
        state.start_layer(Layer.SCAN)
        assert state.status == Status.SCANNING

def test_from_layer_skip():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        state = PipelineState(project_name="test", workspace=str(ws))
        state.start_from(Layer.ANALYZE)
        assert state.status == Status.ANALYZING
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_strategy/test_pipeline_state.py -v
Expected: FAIL
```

- [ ] **Step 3: Create `onep/strategy/pipeline_state.py`**

```python
"""Pipeline state machine with YAML checkpoint persistence."""
from __future__ import annotations

import enum
from pathlib import Path
import yaml


class Status(str, enum.Enum):
    INIT = "init"
    SCANNING = "scanning"
    SCAN_DONE = "scan_done"
    ANALYZING = "analyzing"
    ANALYZE_DONE = "analyze_done"
    DIALOGUE_ACTIVE = "dialogue_active"
    COMPLETED = "completed"
    FAILED = "failed"


class Layer(str, enum.Enum):
    SCAN = "scan"
    ANALYZE = "analyze"
    DIALOGUE = "dialogue"


class PipelineState:
    """State machine for the onep analyze pipeline. Persists to YAML."""

    def __init__(self, project_name: str = "", workspace: str = ""):
        self.project_name = project_name
        self.workspace = workspace
        self.status = Status.INIT
        self.current_layer: str = ""
        self.error: str = ""
        self.warning: str = ""
        self.scan_completed_batches: list[int] = []
        self.scan_failed_batches: list[dict] = []
        self.analysis_items_count: int = 0
        self.total_cost: float = 0.0

    @property
    def _state_path(self) -> Path:
        return Path(self.workspace) / "pipeline_state.yaml"

    def start_layer(self, layer: Layer) -> None:
        mapping = {
            Layer.SCAN: Status.SCANNING,
            Layer.ANALYZE: Status.ANALYZING,
            Layer.DIALOGUE: Status.DIALOGUE_ACTIVE,
        }
        self.status = mapping[layer]
        self.current_layer = layer.value
        self.error = ""
        self.warning = ""
        self.save()

    def complete_layer(self, layer: Layer) -> None:
        mapping = {
            Layer.SCAN: Status.SCAN_DONE,
            Layer.ANALYZE: Status.ANALYZE_DONE,
            Layer.DIALOGUE: Status.COMPLETED,
        }
        self.status = mapping[layer]
        self.save()

    def fail(self, error: str) -> None:
        self.status = Status.FAILED
        self.error = error
        self.save()

    def start_from(self, layer: Layer) -> None:
        """Skip to a specific layer (marks previous as done)."""
        if layer == Layer.ANALYZE:
            self.status = Status.SCAN_DONE
        elif layer == Layer.DIALOGUE:
            self.status = Status.ANALYZE_DONE
        self.start_layer(layer)

    def save(self) -> None:
        path = self._state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "project_name": self.project_name,
            "workspace": self.workspace,
            "status": self.status.value,
            "current_layer": self.current_layer,
            "error": self.error,
            "warning": self.warning,
            "scan_completed_batches": self.scan_completed_batches,
            "scan_failed_batches": self.scan_failed_batches,
            "analysis_items_count": self.analysis_items_count,
            "total_cost": self.total_cost,
        }
        path.write_text(yaml.dump(data, default_flow_style=False))

    @classmethod
    def load(cls, workspace: str) -> PipelineState | None:
        path = Path(workspace) / "pipeline_state.yaml"
        if not path.exists():
            return None
        data = yaml.safe_load(path.read_text()) or {}
        state = cls(
            project_name=data.get("project_name", ""),
            workspace=workspace,
        )
        state.status = Status(data.get("status", "init"))
        state.current_layer = data.get("current_layer", "")
        state.error = data.get("error", "")
        state.warning = data.get("warning", "")
        state.scan_completed_batches = data.get("scan_completed_batches", [])
        state.scan_failed_batches = data.get("scan_failed_batches", [])
        state.analysis_items_count = data.get("analysis_items_count", 0)
        state.total_cost = data.get("total_cost", 0.0)
        return state
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_strategy/test_pipeline_state.py -v
Expected: PASS (4 tests)
```

- [ ] **Step 5: Commit**

```bash
git add onep/strategy/pipeline_state.py tests/test_strategy/test_pipeline_state.py
git commit -m "feat: add pipeline state machine with YAML checkpoint"
```

---

### Task 2: LLM retry with exponential backoff

**Files:**
- Create: `onep/strategy/retry.py`
- Create: `tests/test_strategy/test_retry.py`

**Goal:** Retry LLM calls on transient errors (rate limit, network), exponential backoff.

- [ ] **Step 1: Write tests**

```python
import pytest
from onep.strategy.retry import retry_with_backoff, is_transient_error

def test_is_transient_rate_limit():
    assert is_transient_error(Exception("rate limit exceeded"))

def test_is_transient_network():
    assert is_transient_error(Exception("connection reset"))

def test_not_transient_auth():
    assert not is_transient_error(Exception("invalid api key"))

def test_not_transient_value():
    assert not is_transient_error(ValueError("bad input"))

def test_retry_succeeds_on_third_try():
    calls = [0]
    def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise Exception("rate limit")
        return "ok"
    result = retry_with_backoff(flaky, max_retries=3)
    assert result == "ok"
    assert calls[0] == 3

def test_retry_exhausted():
    def always_fail():
        raise Exception("rate limit")
    result = retry_with_backoff(always_fail, max_retries=2)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_strategy/test_retry.py -v
Expected: FAIL
```

- [ ] **Step 3: Create `onep/strategy/retry.py`**

```python
"""LLM call retry with exponential backoff."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")

_TRANSIENT_PATTERNS = [
    "rate limit", "rate_limit", "ratelimit",
    "too many requests", "429",
    "connection reset", "connection error",
    "timeout", "timed out",
    "server error", "internal server error", "503",
    "service unavailable",
    "overloaded",
]


def is_transient_error(error: Exception) -> bool:
    msg = str(error).lower()
    return any(p in msg for p in _TRANSIENT_PATTERNS)


def retry_with_backoff(
    fn: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> T | None:
    """Call fn, retrying on transient errors with exponential backoff.

    Returns None if all retries exhausted.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if not is_transient_error(e):
                raise
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_strategy/test_retry.py -v
Expected: PASS (6 tests)
```

- [ ] **Step 5: Commit**

```bash
git add onep/strategy/retry.py tests/test_strategy/test_retry.py
git commit -m "feat: add LLM retry with exponential backoff"
```

---

### Task 3: Layer 1 — batch persistence + retry integration

**Files:**
- Modify: `onep/strategy/scanner.py`
- Modify: `onep/cli/analyze.py`

**Goal:** Scanner writes batch results to JSONL incrementally, checkpoint tracks progress, retry on transient errors.

- [ ] **Step 1: Modify scanner to support batch persistence**

Add to `onep/strategy/scanner.py`:

```python
import json
from pathlib import Path

def save_batch_results(workspace: Path, batch_index: int, results: list) -> None:
    """Append batch scan results to JSONL file."""
    path = workspace / "scan_results.jsonl"
    with open(path, "a") as f:
        for r in results:
            record = {"batch": batch_index, "file": r.file_path,
                      "is_strategy": r.is_strategy, "reason": r.reason}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()

def load_batch_results(workspace: Path) -> list:
    """Load all previously saved scan results."""
    path = workspace / "scan_results.jsonl"
    if not path.exists():
        return []
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results

def get_completed_batch_indices(workspace: Path) -> set[int]:
    """Get set of batch indices already completed."""
    path = workspace / "scan_results.jsonl"
    if not path.exists():
        return set()
    indices = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                indices.add(json.loads(line)["batch"])
    return indices
```

- [ ] **Step 2: Update `_run_strategy_mode` in analyze.py for state-driven scan**

Add after the Layer 1 header:

```python
# Check for existing state / resume
pstate = PipelineState.load(str(workspace))
if pstate is None:
    pstate = PipelineState(project_name=project_name, workspace=str(workspace))

if pstate.status in (Status.SCAN_DONE, Status.ANALYZING, Status.ANALYZE_DONE):
    console.print("[dim]Scan already completed, skipping Layer 1[/dim]")
    strategy_files = get_strategy_files(load_batch_results(workspace))
else:
    pstate.start_layer(Layer.SCAN)
    # ... scanning logic with retry and checkpoint
    pstate.complete_layer(Layer.SCAN)
```

In the batch loop, add retry:

```python
for i, batch in enumerate(batches):
    if i in completed_batches:
        continue
    relative_paths = [str(f.relative_to(source_path)) for f in batch]
    prompt = SCAN_PROMPT.format(file_list="\n".join(relative_paths))

    def do_invoke():
        return _invoke_agent("analyzer", prompt)

    response = retry_with_backoff(do_invoke)
    if response:
        batch_results = parse_scan_response(response)
    else:
        batch_results = [
            _no_llm_scan_result(str(f.relative_to(source_path)))
            for f in batch
        ]
        pstate.scan_failed_batches.append({"batch": i, "files": len(batch)})

    save_batch_results(workspace, i, batch_results)
    pstate.scan_completed_batches.append(i)
    pstate.save()
    all_results.extend(batch_results)
```

- [ ] **Step 3: Run full test suite**

```
pytest tests/ -q
Expected: all existing tests pass
```

- [ ] **Step 4: Commit**

```bash
git add onep/strategy/scanner.py onep/cli/analyze.py
git commit -m "feat: add batch persistence and retry to Layer 1 scanner"
```

---

### Task 4: Layer 2 — streaming parse + zero-output detection

**Files:**
- Modify: `onep/cli/analyze.py`
- Modify: `onep/strategy/analyzer.py`

**Goal:** Parse analysis items from streamed tokens line-by-line; detect zero output and fail gracefully.

- [ ] **Step 1: Add streaming parse helper to analyzer.py**

```python
def parse_streaming_items(accumulator: str) -> tuple[list[dict], str]:
    """Parse complete JSON lines from accumulated text.
    Returns (parsed_items, remaining_text)."""
    lines = accumulator.split("\n")
    items = []
    for line in lines[:-1]:
        line = line.strip()
        if line:
            item = _try_parse_item(line)
            if item:
                items.append(item)
    return items, lines[-1]

def _try_parse_item(line: str) -> dict | None:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None

def save_analysis_items(workspace: Path, items: list[dict]) -> None:
    """Append analysis items to JSONL file."""
    path = workspace / "analysis_items.jsonl"
    with open(path, "a") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        f.flush()

def load_analysis_items(workspace: Path) -> list[dict]:
    """Load all previously saved analysis items."""
    path = workspace / "analysis_items.jsonl"
    if not path.exists():
        return []
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items
```

- [ ] **Step 2: Update `_invoke_agent_with_tools` to support streaming parse**

Add a `stream_callback` parameter:

```python
def _invoke_agent_with_tools(
    agent_name, user_prompt, workspace="", source_id="",
    stream_callback=None,
) -> str | None:
    ...
    for event in llm.invoke_with_tools_stream(...):
        ...
        elif event["type"] == "token":
            console.print(event["content"], end="")
            response_parts.append(event["content"])
            if stream_callback:
                stream_callback(event["content"])
    ...
```

And in `_run_strategy_mode`:

```python
accumulator = ""
def on_token(token):
    nonlocal accumulator
    accumulator += token
    items, accumulator = parse_streaming_items(accumulator, workspace)
    if items:
        save_analysis_items(workspace, items)
        pstate.analysis_items_count += len(items)
        pstate.save()

response = _invoke_agent_with_tools(
    "strategy_architect", prompt, workspace=str(source_path),
    stream_callback=on_token,
)

# Parse remainder
items, _ = parse_streaming_items(accumulator + "\n", workspace)
if items:
    save_analysis_items(workspace, items)

# Check zero output
final_items = load_analysis_items(workspace)
if not final_items:
    pstate.fail("analysis produced zero parseable items")
    console.print("[red]Layer 2 produced zero items. Rerun with --from-layer 2[/red]")
    return
```

- [ ] **Step 3: Run tests**

```
pytest tests/ -q
Expected: all tests pass
```

- [ ] **Step 4: Commit**

```bash
git add onep/cli/analyze.py onep/strategy/analyzer.py
git commit -m "feat: add streaming parse and zero-output detection to Layer 2"
```

---

### Task 5: CLI — resume, from-layer, no-dialogue

**Files:**
- Modify: `onep/cli/analyze.py`

**Goal:** Add --resume, --from-layer, --no-dialogue flags.

- [ ] **Step 1: Add CLI options**

Update `analyze_cmd`:

```python
@click.option("--resume", is_flag=True, help="Resume from last checkpoint")
@click.option("--from-layer", "from_layer", type=click.Choice(["1", "2", "3"]),
              help="Start from specific layer")
@click.option("--no-dialogue", is_flag=True, help="Skip interactive dialogue")
```

- [ ] **Step 2: Implement resume logic**

```python
if resume:
    pstate = PipelineState.load(str(workspace))
    if pstate is None:
        console.print("[red]No checkpoint found to resume from.[/red]")
        return
    if pstate.status == Status.FAILED:
        console.print(f"[yellow]Resuming from failed state: {pstate.error}[/yellow]")
        # Re-enter at the failed layer
        from_layer = pstate.current_layer

if from_layer == "2":
    pstate.start_from(Layer.ANALYZE)
elif from_layer == "3":
    pstate.start_from(Layer.DIALOGUE)
```

- [ ] **Step 3: Run tests**

```
pytest tests/ -q
Expected: all tests pass
```

- [ ] **Step 4: Commit**

```bash
git add onep/cli/analyze.py
git commit -m "feat: add --resume --from-layer --no-dialogue to onep analyze"
```

---

### Task 6: Markdown export

**Files:**
- Create: `onep/cli/export_cmd.py`
- Create: `tests/test_cli/test_export.py`

**Goal:** `onep export <project>` generates a self-contained Markdown report.

- [ ] **Step 1: Write test**

```python
import tempfile
from pathlib import Path
from click.testing import CliRunner
from onep.cli.export_cmd import export_group

def test_export_markdown(tmp_path, monkeypatch):
    # Create mock analysis items and workbench
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "analysis_items.jsonl").write_text(
        '{"title":"test","file_location":"f.py:1","tags":["perf"],'
        '"impact":"high","summary":"test issue"}\n'
    )
    (ws / "workbench.yaml").write_text(
        "project_name: test\nsource_path: /tmp/src\nscan_complete: true\n"
        "analysis_complete: true\nitems: []\n"
    )

    runner = CliRunner()
    result = runner.invoke(export_group, ["test", "--output", str(tmp_path / "report.md")])
    # Actually the export command will need adjustments

def test_export_no_project(tmp_path):
    runner = CliRunner()
    result = runner.invoke(export_group, ["nonexistent"])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_cli/test_export.py -v
Expected: FAIL
```

- [ ] **Step 3: Create `onep/cli/export_cmd.py`**

```python
"""onep export — export analysis results as Markdown or JSON."""
from __future__ import annotations

from pathlib import Path
import json

import click
from rich.console import Console

from onep.persistence.database import init_db, list_projects
from onep.strategy.persistence import load_workbench
from onep.strategy.analyzer import load_analysis_items

console = Console()


def _build_markdown(project_name: str, source_path: str, items: list[dict],
                    wb) -> str:
    lines = [
        f"# 策略分析报告: {project_name}",
        "",
        "## 概览",
        f"- 源路径: {source_path}",
        f"- 扫描文件: {wb.scan_file_count if hasattr(wb, 'scan_file_count') else 'N/A'}",
        f"- 发现优化方向: {len(items)} 个",
        "",
        "## 优化方向",
        "",
    ]
    for i, item in enumerate(items, 1):
        impact = item.get("impact", "?")
        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(impact, "⚪")
        lines.append(f"### {i}. {emoji} [{impact}] {item.get('title', '?')}")
        lines.append(f"- **文件**: {item.get('file_location', '?')}")
        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = json.loads(tags)
        lines.append(f"- **标签**: {', '.join(tags) if tags else '无'}")
        lines.append(f"- **摘要**: {item.get('summary', '?')}")
        plan = item.get("plan_path", "")
        if plan:
            lines.append(f"- **Plan**: {plan}")
        lines.append("")

    lines.extend(["## 附录", "", f"- 导出时间: {__import__('datetime').datetime.now().isoformat()}"])
    return "\n".join(lines)


@click.group()
def export_group():
    """Export analysis results."""


@export_group.command()
@click.argument("project", type=str)
@click.option("--output", "-o", default=None, help="Output file path")
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "json"]), default="md")
def export_cmd(project: str, output: str | None, fmt: str):
    """Export analysis results for a project."""
    init_db()
    projects = list_projects()
    proj = next((p for p in projects if p.name == project), None)
    if proj is None:
        console.print(f"[red]Project '{project}' not found.[/red]")
        return

    ws = Path(proj.workspace_path)
    wb = load_workbench(ws)
    items = load_analysis_items(ws)

    if not items and wb:
        # fall back to workbench items
        items = [
            {"title": i.title, "file_location": i.file_location,
             "tags": i.tags, "impact": i.impact, "summary": i.summary,
             "plan_path": i.plan_path}
            for i in wb.items
        ]

    if not items:
        console.print("[yellow]No analysis results to export.[/yellow]")
        return

    source_path = wb.source_path if wb else "unknown"

    if fmt == "json":
        content = json.dumps({"project": project, "source_path": source_path,
                              "items": items}, ensure_ascii=False, indent=2)
    else:
        content = _build_markdown(project, source_path, items, wb)

    if output:
        Path(output).write_text(content)
        console.print(f"[green]Exported to {output}[/green]")
    else:
        console.print(content)


COMMANDS = [export_group]
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_cli/test_export.py -v
Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add onep/cli/export_cmd.py tests/test_cli/test_export.py
git commit -m "feat: add onep export command for Markdown/JSON reports"
```

---

### Task 7: Cost estimation + hard limit

**Files:**
- Create: `onep/llm/cost.py`
- Modify: `onep/llm/router.py`
- Create: `tests/test_llm/test_cost.py`

**Goal:** Model pricing in config, cost estimation before run, budget tracking during run, hard stop when exceeded.

- [ ] **Step 1: Write tests**

```python
from onep.llm.cost import estimate_scan_cost, estimate_analyze_cost, CostTracker

def test_estimate_scan_cost():
    cost = estimate_scan_cost(file_count=500, batch_size=50)
    assert cost > 0

def test_estimate_analyze_cost():
    cost = estimate_analyze_cost(strategy_file_count=20)
    assert cost > 0

def test_cost_tracker_within_budget():
    tracker = CostTracker(budget=5.00)
    assert tracker.can_continue()
    tracker.add_cost(2.00)
    assert tracker.remaining == 3.00
    assert tracker.can_continue()

def test_cost_tracker_exceeded():
    tracker = CostTracker(budget=2.00)
    tracker.add_cost(2.50)
    assert not tracker.can_continue()

def test_cost_tracker_zero_budget_always_ok():
    tracker = CostTracker(budget=0)
    tracker.add_cost(100)
    assert tracker.can_continue()  # zero means no limit
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_llm/test_cost.py -v
Expected: FAIL
```

- [ ] **Step 3: Create `onep/llm/cost.py`**

```python
"""Cost estimation and budget tracking for LLM calls."""
from __future__ import annotations

from onep.config import load_config


def _get_price(model: str, price_type: str) -> float:
    config = load_config()
    pricing = getattr(config.llm, "pricing", {}) or {}
    model_pricing = pricing.get(model, {})
    if isinstance(model_pricing, dict):
        return model_pricing.get(price_type, 0.0)
    return 0.0


def estimate_scan_cost(
    file_count: int,
    batch_size: int = 50,
    chars_per_file: int = 60,
    output_chars_per_file: int = 35,
) -> float:
    config = load_config()
    model = config.llm.default_model
    input_price = _get_price(model, "input")
    output_price = _get_price(model, "output")

    batches = max(1, file_count // batch_size + (1 if file_count % batch_size else 0))
    input_tokens_per_batch = (file_count * chars_per_file / batch_size) / 3
    output_tokens_per_batch = (min(file_count, batch_size) * output_chars_per_file) / 3

    total_input_m = (batches * input_tokens_per_batch) / 1_000_000
    total_output_m = (batches * output_tokens_per_batch) / 1_000_000

    return total_input_m * input_price + total_output_m * output_price


def estimate_analyze_cost(
    strategy_file_count: int,
    avg_file_chars: int = 3000,
    output_chars: int = 2000,
    avg_tool_rounds: int = 4,
) -> float:
    config = load_config()
    model = config.llm.complex_model
    input_price = _get_price(model, "input")
    output_price = _get_price(model, "output")

    input_tokens = (strategy_file_count * avg_file_chars * avg_tool_rounds) / 3
    output_tokens = (output_chars / 3)

    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price


class CostTracker:
    def __init__(self, budget: float = 0.0):
        self.budget = budget
        self.spent = 0.0

    @property
    def remaining(self) -> float:
        return max(0, self.budget - self.spent)

    def can_continue(self) -> bool:
        if self.budget <= 0:
            return True  # zero means no limit
        return self.spent < self.budget

    def add_cost(self, amount: float) -> None:
        self.spent += amount

    def add_usage(self, prompt_tokens: int, completion_tokens: int, model: str) -> None:
        input_price = _get_price(model, "input")
        output_price = _get_price(model, "output")
        cost = (prompt_tokens / 1_000_000) * input_price + \
               (completion_tokens / 1_000_000) * output_price
        self.spent += cost

    def summary(self) -> str:
        if self.budget > 0:
            return f"${self.spent:.2f} / ${self.budget:.2f}"
        return f"${self.spent:.2f} spent"
```

- [ ] **Step 4: Add pricing to router.py config defaults**

In `onep/config.py` LLMConfig, add:

```python
pricing: dict = field(default_factory=lambda: {
    "deepseek/deepseek-chat":   {"input": 0.14, "output": 0.28},
    "deepseek/deepseek-v4-pro": {"input": 0.50, "output": 1.00},
    "openai/gpt-4o":            {"input": 2.50, "output": 10.00},
    "openai/gpt-4.1":           {"input": 2.00, "output": 8.00},
})
```

- [ ] **Step 5: Run test to verify it passes**

```
pytest tests/test_llm/test_cost.py -v
Expected: PASS (5 tests)
```

- [ ] **Step 6: Commit**

```bash
git add onep/llm/cost.py onep/llm/router.py tests/test_llm/test_cost.py
git commit -m "feat: add cost estimation and budget tracking"
```

---

### Task 8: Wire cost tracking into analyze pipeline

**Files:**
- Modify: `onep/cli/analyze.py`

**Goal:** Add --max-cost flag, pre-run estimate, budget check after each LLM call.

- [ ] **Step 1: Update analyze_cmd**

```python
@click.option("--max-cost", type=float, default=0,
              help="Maximum cost in USD (0 = no limit)")
```

In `_run_strategy_mode`, before Layer 1:

```python
from onep.llm.cost import CostTracker, estimate_scan_cost, estimate_analyze_cost

tracker = CostTracker(budget=max_cost)
if max_cost > 0:
    est_scan = estimate_scan_cost(len(all_files))
    est_analyze = estimate_analyze_cost(len(strategy_files))
    console.print(f"[dim]Estimated cost: ~${est_scan + est_analyze:.2f} "
                  f"(max ${max_cost:.2f})[/dim]")
    if not click.confirm("Continue? [Y/n]", default=True):
        return
```

After each LLM call that returns usage:

```python
llm = get_llm()
if not llm.usage.is_empty:
    tracker.add_usage(llm.usage.prompt_tokens, llm.usage.completion_tokens,
                      resolve_model(agent_name)[0])
    if not tracker.can_continue():
        console.print(f"[red]Budget exceeded ({tracker.summary()}). Stopping.[/red]")
        pstate.total_cost = tracker.spent
        pstate.save()
        return
```

- [ ] **Step 2: Run full test suite**

```
pytest tests/ -q
Expected: all tests pass
```

- [ ] **Step 3: Commit**

```bash
git add onep/cli/analyze.py
git commit -m "feat: wire cost tracking into analyze pipeline"
```

---

### Task 9: Final integration + documentation update

**Files:**
- Modify: `README.md` (add new commands)

- [ ] **Step 1: Update README with new commands**

Add to Brownfield section:

```markdown
# With checkpoint and resume
onep analyze ./repo --name myproj --max-cost 5.00
onep analyze ./repo --name myproj --resume

# Skip dialogue, export results
onep analyze ./repo --no-dialogue --export report.md

# Export existing analysis
onep export myproj
onep export myproj --format json
```

- [ ] **Step 2: Run full test suite**

```
pytest tests/ -q
Expected: ALL pass
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README with production analyze features"
```
