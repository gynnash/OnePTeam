# Strategy Analysis System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend OnePTeam with a strategy analysis system that scans codebases for business/algorithm strategies, discovers optimization opportunities via 3-layer LLM analysis, and generates structured optimization plans through an interactive dialogue workbench.

**Architecture:** New `onep/strategy/` package with 6 modules (scanner, analyzer, workbench, planner, persistence, models) plus a Strategy Architect agent. Three-layer LLM pipeline: cheap model scans for strategy-dense files, expensive model does deep analysis, then interactive dialogue drives plan generation. CLI extensions via `onep analyze --mode strategy` and `onep strategy` subcommands.

**Tech Stack:** Python 3.12+, CrewAI (agent framework), Click+Rich (CLI), YAML+JSONL (persistence), existing onep persistence layer

---

## File Map

```
onep/strategy/
├── __init__.py
├── models.py           # StrategyItem, DialogueTurn, ItemStatus dataclasses
├── persistence.py      # workbench.yaml + dialogue.jsonl read/write
├── scanner.py          # Layer 1: parallel file scanning via code analyst agent
├── analyzer.py         # Layer 2: deep strategy analysis via strategy architect
├── workbench.py        # Layer 3: dialogue engine + slash command parser
├── planner.py          # Plan generation (standard/full versions)

onep/agents/
└── strategy_architect.py  # Strategy Architect Agent definition

onep/cli/
├── analyze.py          # onep analyze --mode strategy command
└── strategy_cmd.py     # onep strategy resume/status/export subcommands

onep/orchestrator/
└── brownfield.py       # Brownfield pipeline (strategy mode)

Modified files:
- onep/persistence/models.py     # Add StrategyItem, DialogueTurn, ItemStatus
- onep/orchestrator/crew.py      # Add brownfield mode routing
```

---

### Task 1: Strategy data models

**Files:**
- Create: `onep/strategy/__init__.py`
- Create: `onep/strategy/models.py`
- Create: `tests/test_strategy/__init__.py`
- Create: `tests/test_strategy/test_models.py`

- [ ] **Step 1: Create onep/strategy/__init__.py**

```python
"""Strategy analysis system — scan, analyze, and generate optimization plans."""
```

- [ ] **Step 2: Create onep/strategy/models.py**

```python
"""Data models for strategy analysis: items, dialogue turns, and plan versions."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ItemStatus(str, Enum):
    PENDING = "pending"
    DISCUSSING = "discussing"
    PLAN_DRAFTED = "plan_drafted"
    PLAN_REVIEWED = "plan_reviewed"
    DISCARDED = "discarded"


class PlanVersion(str, Enum):
    NONE = "none"
    STANDARD = "standard"
    FULL = "full"


@dataclass
class StrategyItem:
    """A single optimization direction discovered during analysis."""
    title: str
    file_location: str
    summary: str = ""
    impact: str = "medium"  # high | medium | low
    tags: list[str] = field(default_factory=list)
    status: ItemStatus = ItemStatus.PENDING
    discussion_summary: str = ""
    plan_path: str | None = None
    plan_version: PlanVersion = PlanVersion.NONE
    id: str = field(default_factory=lambda: f"si-{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def start_discussing(self) -> None:
        self.status = ItemStatus.DISCUSSING
        self.touch()

    def draft_plan(self, plan_path: str) -> None:
        self.status = ItemStatus.PLAN_DRAFTED
        self.plan_path = plan_path
        self.plan_version = PlanVersion.STANDARD
        self.touch()

    def review_plan(self) -> None:
        self.status = ItemStatus.PLAN_REVIEWED
        self.touch()

    def expand_plan(self) -> None:
        self.plan_version = PlanVersion.FULL
        self.touch()

    def discard(self) -> None:
        self.status = ItemStatus.DISCARDED
        self.touch()


@dataclass
class DialogueTurn:
    """A single round in the strategy dialogue."""
    role: str  # user | agent | system
    content: str
    item_id: str | None = None
    slash_command: str | None = None
    id: str = field(default_factory=lambda: f"dt-{uuid.uuid4().hex[:8]}")
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class WorkbenchState:
    """Top-level state for a strategy analysis session."""
    project_name: str
    source_path: str  # git URL or local path
    items: list[StrategyItem] = field(default_factory=list)
    dialogue: list[DialogueTurn] = field(default_factory=list)
    current_item_id: str | None = None
    scan_complete: bool = False
    analysis_complete: bool = False
```

- [ ] **Step 3: Create tests/test_strategy/__init__.py**

```python
"""Tests for strategy analysis system."""
```

- [ ] **Step 4: Create tests/test_strategy/test_models.py**

```python
from onep.strategy.models import (
    StrategyItem, DialogueTurn, WorkbenchState,
    ItemStatus, PlanVersion,
)


def test_strategy_item_creation():
    item = StrategyItem(
        title="Cache invalidation strategy",
        file_location="cache.py:30",
        summary="Full refresh instead of incremental",
        impact="high",
        tags=["缓存策略", "性能"],
    )
    assert item.title == "Cache invalidation strategy"
    assert item.status == ItemStatus.PENDING
    assert item.plan_version == PlanVersion.NONE
    assert len(item.id) > 0


def test_strategy_item_lifecycle():
    item = StrategyItem(title="Test", file_location="f.py:1")

    item.start_discussing()
    assert item.status == ItemStatus.DISCUSSING

    item.draft_plan("plans/001-test.md")
    assert item.status == ItemStatus.PLAN_DRAFTED
    assert item.plan_version == PlanVersion.STANDARD

    item.review_plan()
    assert item.status == ItemStatus.PLAN_REVIEWED

    item.expand_plan()
    assert item.plan_version == PlanVersion.FULL

    item.discard()
    assert item.status == ItemStatus.DISCARDED


def test_dialogue_turn_creation():
    dt = DialogueTurn(
        role="user",
        content="展开说说第3个",
        item_id="si-3",
    )
    assert dt.role == "user"
    assert dt.slash_command is None


def test_dialogue_turn_with_slash():
    dt = DialogueTurn(
        role="user",
        content="",
        slash_command="/focus 3",
    )
    assert dt.slash_command == "/focus 3"


def test_workbench_state_defaults():
    wb = WorkbenchState(
        project_name="my-analysis",
        source_path="./repo",
    )
    assert wb.scan_complete is False
    assert wb.analysis_complete is False
    assert wb.items == []
    assert wb.current_item_id is None
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_strategy/test_models.py -v`
Expected: 5 tests pass

- [ ] **Step 6: Commit**

```bash
git add onep/strategy/ tests/test_strategy/
git commit -m "feat: add strategy analysis data models"
```

---

### Task 2: Strategy persistence

**Files:**
- Create: `onep/strategy/persistence.py`
- Create: `tests/test_strategy/test_persistence.py`

- [ ] **Step 1: Create onep/strategy/persistence.py**

```python
"""Persistence for workbench state — YAML metadata + JSONL dialogue log."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from onep.strategy.models import WorkbenchState, StrategyItem, DialogueTurn, ItemStatus, PlanVersion


def _strategy_dir(workspace: Path) -> Path:
    return workspace / ".onep" / "strategy"


def _workbench_path(workspace: Path) -> Path:
    return _strategy_dir(workspace) / "workbench.yaml"


def _dialogue_path(workspace: Path) -> Path:
    return _strategy_dir(workspace) / "dialogue.jsonl"


def _plans_dir(workspace: Path) -> Path:
    return _strategy_dir(workspace) / "plans"


def _serialize_item(item: StrategyItem) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "file_location": item.file_location,
        "summary": item.summary,
        "impact": item.impact,
        "tags": item.tags,
        "status": item.status.value,
        "discussion_summary": item.discussion_summary,
        "plan_path": item.plan_path,
        "plan_version": item.plan_version.value,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _deserialize_item(data: dict) -> StrategyItem:
    return StrategyItem(
        id=data["id"],
        title=data["title"],
        file_location=data["file_location"],
        summary=data.get("summary", ""),
        impact=data.get("impact", "medium"),
        tags=data.get("tags", []),
        status=ItemStatus(data.get("status", "pending")),
        discussion_summary=data.get("discussion_summary", ""),
        plan_path=data.get("plan_path"),
        plan_version=PlanVersion(data.get("plan_version", "none")),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


def save_workbench(workspace: Path, wb: WorkbenchState) -> None:
    _strategy_dir(workspace).mkdir(parents=True, exist_ok=True)
    _plans_dir(workspace).mkdir(parents=True, exist_ok=True)

    raw = {
        "project_name": wb.project_name,
        "source_path": wb.source_path,
        "current_item_id": wb.current_item_id,
        "scan_complete": wb.scan_complete,
        "analysis_complete": wb.analysis_complete,
        "items": [_serialize_item(item) for item in wb.items],
    }
    _workbench_path(workspace).write_text(yaml.dump(raw, default_flow_style=False))


def load_workbench(workspace: Path) -> WorkbenchState | None:
    wb_path = _workbench_path(workspace)
    if not wb_path.exists():
        return None

    raw = yaml.safe_load(wb_path.read_text()) or {}
    items = [_deserialize_item(d) for d in raw.get("items", [])]

    dialogue = []
    dl_path = _dialogue_path(workspace)
    if dl_path.exists():
        for line in dl_path.read_text().strip().split("\n"):
            if line.strip():
                d = json.loads(line)
                dialogue.append(DialogueTurn(
                    id=d.get("id", ""),
                    role=d["role"],
                    content=d.get("content", ""),
                    item_id=d.get("item_id"),
                    slash_command=d.get("slash_command"),
                    created_at=d.get("created_at", ""),
                ))

    return WorkbenchState(
        project_name=raw.get("project_name", ""),
        source_path=raw.get("source_path", ""),
        items=items,
        dialogue=dialogue,
        current_item_id=raw.get("current_item_id"),
        scan_complete=raw.get("scan_complete", False),
        analysis_complete=raw.get("analysis_complete", False),
    )


def append_dialogue(workspace: Path, turn: DialogueTurn) -> None:
    _strategy_dir(workspace).mkdir(parents=True, exist_ok=True)
    dl_path = _dialogue_path(workspace)
    line = json.dumps({
        "id": turn.id,
        "role": turn.role,
        "content": turn.content,
        "item_id": turn.item_id,
        "slash_command": turn.slash_command,
        "created_at": turn.created_at,
    }, ensure_ascii=False)
    with open(dl_path, "a") as f:
        f.write(line + "\n")


def save_plan(workspace: Path, plan_id: str, content: str) -> str:
    _plans_dir(workspace).mkdir(parents=True, exist_ok=True)
    plan_path = _plans_dir(workspace) / f"{plan_id}.md"
    plan_path.write_text(content)
    return str(plan_path)
```

- [ ] **Step 2: Create tests/test_strategy/test_persistence.py**

```python
import tempfile
from pathlib import Path

from onep.strategy.models import (
    WorkbenchState, StrategyItem, DialogueTurn,
)
from onep.strategy.persistence import (
    save_workbench, load_workbench, append_dialogue, save_plan,
)


def test_save_and_load_workbench():
    ws = Path(tempfile.mkdtemp())
    wb = WorkbenchState(project_name="test", source_path="./repo")
    wb.items.append(StrategyItem(title="Test item", file_location="f.py:1", impact="high"))
    wb.items.append(StrategyItem(title="Another", file_location="g.py:10", tags=["缓存"]))
    wb.scan_complete = True

    save_workbench(ws, wb)
    loaded = load_workbench(ws)

    assert loaded is not None
    assert loaded.project_name == "test"
    assert loaded.scan_complete is True
    assert len(loaded.items) == 2
    assert loaded.items[0].title == "Test item"
    assert loaded.items[0].impact == "high"
    assert loaded.items[1].tags == ["缓存"]


def test_load_workbench_returns_none_for_missing():
    ws = Path(tempfile.mkdtemp())
    result = load_workbench(ws)
    assert result is None


def test_append_and_load_dialogue():
    ws = Path(tempfile.mkdtemp())
    append_dialogue(ws, DialogueTurn(role="user", content="hello"))
    append_dialogue(ws, DialogueTurn(role="agent", content="你好！", item_id="si-1"))

    # Load the workbench (which loads dialogue from jsonl)
    wb = WorkbenchState(project_name="test", source_path="./repo")
    save_workbench(ws, wb)
    loaded = load_workbench(ws)
    assert loaded is not None
    assert len(loaded.dialogue) == 2
    assert loaded.dialogue[0].role == "user"
    assert loaded.dialogue[1].item_id == "si-1"


def test_save_plan():
    ws = Path(tempfile.mkdtemp())
    path = save_plan(ws, "001-test", "# Test Plan\n\nContent here.")
    assert path.endswith("001-test.md")
    assert Path(path).exists()
    assert "# Test Plan" in Path(path).read_text()
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_strategy/test_persistence.py -v`
Expected: 4 tests pass

- [ ] **Step 4: Commit**

```bash
git add onep/strategy/persistence.py tests/test_strategy/test_persistence.py
git commit -m "feat: add strategy persistence layer"
```

---

### Task 3: Strategy Architect agent

**Files:**
- Create: `onep/agents/strategy_architect.py`

- [ ] **Step 1: Create onep/agents/strategy_architect.py**

```python
"""Strategy Architect Agent — discovers and analyzes business/algorithm strategy optimizations."""
from crewai import Agent

from onep.agents.registry import register


@register("strategy_architect")
def create_strategy_architect() -> Agent:
    return Agent(
        role="策略架构师",
        goal="深入理解代码中的业务策略和算法策略，发现可优化点，生成结构化的优化Plan",
        backstory=(
            "你是一位资深的策略架构师，专注于分析各种业务策略和算法策略的设计质量。"
            "你擅长：策略意图识别、策略模式对比、量化影响评估、多方案权衡。"
            "你能理解推荐策略、LLM Pipeline策略、缓存策略、风控规则、定价策略等各类策略逻辑。"
            "你通过对话引导用户逐步细化优化方向，最终生成清晰可执行的优化Plan。"
            "你始终基于代码事实进行分析，不凭空假设。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=8,
    )
```

- [ ] **Step 2: Verify agent registers**

Run: `python -c "from onep.agents.registry import clear_registry; clear_registry(); import onep.agents.strategy_architect; from onep.agents.registry import list_agents; print(list_agents())"`
Expected: prints `['strategy_architect']`

- [ ] **Step 3: Commit**

```bash
git add onep/agents/strategy_architect.py
git commit -m "feat: add Strategy Architect agent"
```

---

### Task 4: Layer 1 — Scanner (strategy file detection)

**Files:**
- Create: `onep/strategy/scanner.py`
- Create: `tests/test_strategy/test_scanner.py`

- [ ] **Step 1: Create onep/strategy/scanner.py**

```python
"""
Layer 1: Strategy file scanner.

Walks a codebase, groups files into batches, and uses the code analyst agent
(DeepSeek V4) to classify each file as strategy-relevant or not.
"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass


@dataclass
class ScanResult:
    file_path: str
    is_strategy: bool
    reason: str


def _walk_files(source_path: Path) -> list[Path]:
    """Walk a directory and return all source files, skipping noise."""
    skip_dirs = {
        ".git", "__pycache__", "node_modules", ".venv", "venv",
        "dist", "build", ".next", "target", "vendor", ".idea",
    }
    skip_extensions = {".pyc", ".pyo", ".class", ".o", ".so", ".dll",
                       ".exe", ".bin", ".png", ".jpg", ".svg", ".ico",
                       ".lock", ".min.js", ".min.css", ".map"}

    files = []
    for entry in source_path.rglob("*"):
        if entry.is_file():
            if any(part in skip_dirs for part in entry.parts):
                continue
            if entry.suffix in skip_extensions or entry.name.endswith(tuple(skip_extensions)):
                continue
            files.append(entry)
    return files


def _batch_files(files: list[Path], max_batch_size: int = 20) -> list[list[Path]]:
    batches = []
    for i in range(0, len(files), max_batch_size):
        batches.append(files[i:i + max_batch_size])
    return batches


def _build_scan_prompt(file_paths: list[Path], source_root: Path) -> str:
    """Build prompt for the code analyst to classify a batch of files."""
    relative_paths = [str(p.relative_to(source_root)) for p in file_paths]

    file_list = "\n".join(relative_paths)

    return f"""Analyze the following files and determine whether each one contains business strategy or algorithm strategy logic.

Strategy logic includes:
- Recommendation, ranking, or matching algorithms
- LLM prompt chains, agent workflows, or model routing
- Caching, rate-limiting, or resource allocation strategies
- Business rules, pricing, fraud detection, or risk scoring
- Any non-trivial decision logic that impacts system behavior

NOT strategy logic:
- Pure utility functions (string formatting, date helpers)
- Configuration constants or enums
- Simple CRUD without decision logic
- Boilerplate (middleware, logging setup, routes registration)
- Test files

Files to analyze:
{file_list}

For each file, respond with a JSON object (one per line):
{{"file": "<path>", "is_strategy": true/false, "reason": "<one sentence in Chinese>"}}

Respond with exactly one JSON line per file, no other text."""


def scan_files(source_path: Path, llm_adapter=None) -> list[ScanResult]:
    """
    Walk the source tree, batch files, and classify each as strategy-relevant or not.

    In production, llm_adapter invokes the code analyst (DeepSeek V4).
    In test/MVP, it can be a mock that returns pre-defined results.
    """
    all_files = _walk_files(source_path)
    batches = _batch_files(all_files)

    results: list[ScanResult] = []
    for batch in batches:
        if llm_adapter is not None:
            prompt = _build_scan_prompt(batch, source_path)
            response = llm_adapter.invoke(
                system_prompt="你是一位代码分析师。只输出JSON，每行一个文件的分析结果。",
                user_prompt=prompt,
                stage_name="analyzer",
            )
            # Parse JSONL response
            for line in response.strip().split("\n"):
                line = line.strip()
                if line:
                    import json
                    obj = json.loads(line)
                    results.append(ScanResult(
                        file_path=obj["file"],
                        is_strategy=obj["is_strategy"],
                        reason=obj.get("reason", ""),
                    ))
        else:
            # No LLM available: mark all non-trivial files for manual review
            for f in batch:
                results.append(ScanResult(
                    file_path=str(f.relative_to(source_path)),
                    is_strategy=True,
                    reason="LLM不可用，默认标记为策略文件待人工审查",
                ))

    return results


def get_strategy_files(results: list[ScanResult]) -> list[str]:
    """Filter scan results to only strategy-relevant files."""
    return [r.file_path for r in results if r.is_strategy]
```

- [ ] **Step 2: Create tests/test_strategy/test_scanner.py**

```python
import tempfile
from pathlib import Path

from onep.strategy.scanner import _walk_files, _batch_files, get_strategy_files, ScanResult


def test_walk_files_skips_git_and_cache():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "src").mkdir()
    (tmp / "src" / "main.py").write_text("def foo(): pass")
    (tmp / "src" / "utils.py").write_text("def bar(): pass")
    (tmp / ".git").mkdir()
    (tmp / ".git" / "config").write_text("...")
    (tmp / "__pycache__").mkdir()
    (tmp / "__pycache__" / "main.cpython-313.pyc").write_text("...")

    files = _walk_files(tmp)
    relative = [str(f.relative_to(tmp)) for f in files]
    assert "src/main.py" in relative
    assert "src/utils.py" in relative
    assert ".git/config" not in relative
    assert "__pycache__/main.cpython-313.pyc" not in relative


def test_batch_files():
    files = [Path(f"file_{i}.py") for i in range(25)]
    batches = _batch_files(files, max_batch_size=10)
    assert len(batches) == 3
    assert len(batches[0]) == 10
    assert len(batches[1]) == 10
    assert len(batches[2]) == 5


def test_get_strategy_files():
    results = [
        ScanResult("a.py", True, "contains ranking logic"),
        ScanResult("b.py", False, "pure utility"),
        ScanResult("c.py", True, "prompt chain"),
    ]
    files = get_strategy_files(results)
    assert files == ["a.py", "c.py"]
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_strategy/test_scanner.py -v`
Expected: 3 tests pass

- [ ] **Step 4: Commit**

```bash
git add onep/strategy/scanner.py tests/test_strategy/test_scanner.py
git commit -m "feat: add Layer 1 strategy file scanner"
```

---

### Task 5: Layer 2 — Strategy Analyzer

**Files:**
- Create: `onep/strategy/analyzer.py`
- Create: `tests/test_strategy/test_analyzer.py`

- [ ] **Step 1: Create onep/strategy/analyzer.py**

```python
"""
Layer 2: Deep strategy analyzer.

Takes the list of strategy-dense files from Layer 1 and calls the
Strategy Architect agent (GPT 5.5) to deeply understand the strategy logic
and discover optimization opportunities.
"""
from __future__ import annotations

import json
from pathlib import Path

from onep.strategy.models import StrategyItem


def _build_analysis_prompt(strategy_files: list[str], source_root: Path) -> str:
    file_list = "\n".join(f"- {f}" for f in strategy_files)

    return f"""请分析以下文件中的策略逻辑，发现可优化点。

策略密集文件列表：
{file_list}

项目根目录: {source_root}

对于每个发现的优化点，请输出一条JSON（一行），包含以下字段：
- title: 优化方向标题（简洁明了，10字以内）
- file_location: 主文件位置（如 "cache.py:30"）
- tags: 策略类型标签数组（如 ["缓存策略", "性能"]）
- impact: 影响评估（"high" / "medium" / "low"）
- summary: 问题摘要（2-3句描述当前策略的问题和优化方向）

注意：
- 只输出确实存在优化空间的发现，不要为每个文件都生成条目
- 如果多个文件涉及同一个策略问题，合并为一个条目
- 影响评估要基于实际分析，不要全部标 high
- 按影响程度从高到低排序输出

输出格式（每行一个JSON对象）：
{{"title": "...", "file_location": "...", "tags": [...], "impact": "high", "summary": "..."}}"""


def _parse_analysis_response(response: str) -> list[StrategyItem]:
    items = []
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            items.append(StrategyItem(
                title=obj["title"],
                file_location=obj["file_location"],
                tags=obj.get("tags", []),
                impact=obj.get("impact", "medium"),
                summary=obj.get("summary", ""),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return items


def analyze_strategies(
    strategy_files: list[str],
    source_root: Path,
    llm_adapter=None,
) -> list[StrategyItem]:
    """
    Run Layer 2 deep analysis on strategy-dense files.

    Returns a list of StrategyItem objects, sorted by impact.
    """
    if not strategy_files:
        return []

    if llm_adapter is not None:
        prompt = _build_analysis_prompt(strategy_files, source_root)
        response = llm_adapter.invoke(
            system_prompt=(
                "你是一位策略架构师。只输出JSON，每行一个优化发现，"
                "按影响程度从高到低排序。"
            ),
            user_prompt=prompt,
            stage_name="strategy_architect",
        )
        items = _parse_analysis_response(response)
    else:
        # No LLM: return a placeholder item
        items = [
            StrategyItem(
                title="LLM不可用，策略分析待执行",
                file_location="N/A",
                summary="请配置API密钥后重新运行分析。",
                tags=["系统"],
                impact="high",
            )
        ]

    # Sort by impact: high > medium > low
    impact_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: impact_order.get(x.impact, 2))

    return items
```

- [ ] **Step 2: Create tests/test_strategy/test_analyzer.py**

```python
import tempfile
from pathlib import Path

from onep.strategy.analyzer import (
    _build_analysis_prompt, _parse_analysis_response, analyze_strategies,
)
from onep.strategy.models import StrategyItem


def test_build_analysis_prompt_includes_files():
    prompt = _build_analysis_prompt(
        ["src/ranker.py", "src/cache.py"],
        Path("/project"),
    )
    assert "src/ranker.py" in prompt
    assert "src/cache.py" in prompt
    assert "/project" in prompt


def test_parse_analysis_response():
    response = """{"title": "缓存优化", "file_location": "cache.py:30", "tags": ["缓存"], "impact": "high", "summary": "全量刷新"}
{"title": "日志策略", "file_location": "log.py:10", "tags": ["可观测性"], "impact": "low", "summary": "级别不统一"}"""

    items = _parse_analysis_response(response)
    assert len(items) == 2
    assert items[0].title == "缓存优化"
    assert items[0].impact == "high"
    assert items[0].tags == ["缓存"]


def test_parse_analysis_response_skips_invalid_lines():
    response = """{"title": "ok", "file_location": "f.py:1", "tags": [], "impact": "low", "summary": "x"}
invalid json here
{"title": "also ok", "file_location": "g.py:2", "tags": [], "impact": "medium", "summary": "y"}"""

    items = _parse_analysis_response(response)
    assert len(items) == 2


def test_analyze_strategies_empty_input():
    items = analyze_strategies([], Path("."))
    assert items == []


def test_analyze_strategies_no_llm():
    items = analyze_strategies(
        ["test.py"],
        Path("."),
        llm_adapter=None,
    )
    assert len(items) == 1
    assert items[0].title == "LLM不可用，策略分析待执行"
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_strategy/test_analyzer.py -v`
Expected: 5 tests pass

- [ ] **Step 4: Commit**

```bash
git add onep/strategy/analyzer.py tests/test_strategy/test_analyzer.py
git commit -m "feat: add Layer 2 strategy deep analyzer"
```

---

### Task 6: Plan Generator

**Files:**
- Create: `onep/strategy/planner.py`
- Create: `tests/test_strategy/test_planner.py`

- [ ] **Step 1: Create onep/strategy/planner.py**

```python
"""
Plan generator — produces standard and full optimization plans.

Standard plan: problem description, optimization direction, implementation
approach, risk assessment, reference solutions.

Full plan: standard content + pseudocode/architecture changes, data comparison,
priority ranking, and dependency analysis.
"""
from __future__ import annotations

from pathlib import Path

from onep.strategy.models import StrategyItem


STANDARD_PLAN_TEMPLATE = """# 优化 Plan: {title}

## 基本信息

- **文件位置**: {file_location}
- **策略类型**: {tags}
- **影响评估**: {impact}
- **版本**: 标准版
- **生成时间**: {timestamp}

## 问题描述

{problem_description}

## 优化方向

{optimization_direction}

## 实现思路

{implementation_approach}

## 风险评估

{risk_assessment}

## 参考方案

{reference_solutions}
"""

FULL_PLAN_APPENDIX = """

---

## 完整版附加内容

## 伪代码 / 架构变更

{pseudocode}

## 数据对比

{data_comparison}

## 优先级与依赖

{priority_and_dependencies}
"""


def _build_standard_prompt(item: StrategyItem) -> str:
    return f"""请为以下策略优化方向生成标准版优化Plan。

优化方向: {item.title}
文件位置: {item.file_location}
当前问题: {item.summary}
策略标签: {', '.join(item.tags)}
影响评估: {item.impact}

请按以下结构输出完整的标准版Plan（中文撰写）：

1. 问题描述 — 详细描述当前策略的行为、适用场景和存在的缺陷（200-300字）
2. 优化方向 — 建议的新策略方向，说明核心改进点（200-300字）
3. 实现思路 — 关键技术方案和实现步骤，列出3-5个关键步骤（200-300字）
4. 风险评估 — 实施风险分析、回滚方案、兼容性考虑（150-200字）
5. 参考方案 — 业界类似实践或参考资料，至少2个参考（150-200字）

输出格式: 直接输出Markdown格式的完整Plan，不要用JSON包裹。"""


def _build_full_prompt(item: StrategyItem, standard_plan: str) -> str:
    return f"""以下是已审核通过的标准版优化Plan：

{standard_plan}

请在此基础上补充以下完整版内容：

1. 伪代码 / 架构变更 — 关键代码变更的伪代码或架构草图（标记变更点）
2. 数据对比 — 优化前后的量化对比预估（性能指标、资源消耗等）
3. 优先级与依赖 — 该Plan的实施优先级排序理由，以及与其他优化项的依赖关系

追加在标准版Plan的末尾，用分隔线分隔。"""


def generate_standard_plan(
    item: StrategyItem,
    workspace: Path,
    llm_adapter=None,
    plan_index: int = 1,
) -> str | None:
    """
    Generate a standard optimization plan for the given item.

    Returns the plan file path, or None if generation failed.
    """
    if llm_adapter is None:
        return None

    prompt = _build_standard_prompt(item)
    response = llm_adapter.invoke(
        system_prompt="你是一位策略架构师。请按照用户要求的格式输出完整的优化Plan。",
        user_prompt=prompt,
        stage_name="strategy_architect",
    )

    from onep.strategy.persistence import save_plan
    plan_id = f"{plan_index:03d}-{item.title.replace(' ', '-').replace('/', '-')[:50]}"
    plan_path = save_plan(workspace / ".onep", plan_id, response)

    item.draft_plan(plan_path)
    return plan_path


def generate_full_plan(
    item: StrategyItem,
    standard_plan_content: str,
    workspace: Path,
    llm_adapter=None,
) -> str | None:
    """
    Expand a reviewed standard plan into a full plan.

    Returns the updated plan file path, or None if generation failed.
    """
    if llm_adapter is None:
        return None

    prompt = _build_full_prompt(item, standard_plan_content)
    response = llm_adapter.invoke(
        system_prompt="你是一位策略架构师。请在标准版Plan的基础上补充完整版内容。",
        user_prompt=prompt,
        stage_name="strategy_architect",
    )

    full_content = standard_plan_content + "\n" + response

    from onep.strategy.persistence import save_plan
    plan_id = item.plan_path.split("/")[-1].replace(".md", "") if item.plan_path else "full-plan"
    plan_path = save_plan(workspace / ".onep", plan_id + "-full", full_content)

    item.expand_plan()
    item.plan_path = plan_path
    return plan_path
```

- [ ] **Step 2: Create tests/test_strategy/test_planner.py**

```python
import tempfile
from pathlib import Path

from onep.strategy.models import StrategyItem
from onep.strategy.planner import (
    _build_standard_prompt,
    _build_full_prompt,
    generate_standard_plan,
    generate_full_plan,
    STANDARD_PLAN_TEMPLATE,
    FULL_PLAN_APPENDIX,
)


def test_standard_prompt_includes_item_fields():
    item = StrategyItem(
        title="缓存优化",
        file_location="cache.py:30",
        summary="全量刷新问题",
        tags=["缓存策略"],
        impact="high",
    )
    prompt = _build_standard_prompt(item)
    assert "缓存优化" in prompt
    assert "cache.py:30" in prompt
    assert "全量刷新问题" in prompt
    assert "缓存策略" in prompt
    assert "high" in prompt


def test_full_prompt_includes_standard_plan():
    standard = "# Plan: test\n\n问题描述内容..."
    prompt = _build_full_prompt(
        StrategyItem(title="t", file_location="f:1"),
        standard,
    )
    assert "问题描述内容" in prompt
    assert "伪代码" in prompt


def test_standard_plan_template_has_all_sections():
    content = STANDARD_PLAN_TEMPLATE.format(
        title="T",
        file_location="f:1",
        tags="t1, t2",
        impact="high",
        timestamp="2026-01-01",
        problem_description="p",
        optimization_direction="o",
        implementation_approach="i",
        risk_assessment="r",
        reference_solutions="ref",
    )
    assert "## 基本信息" in content
    assert "## 问题描述" in content
    assert "## 优化方向" in content
    assert "## 实现思路" in content
    assert "## 风险评估" in content
    assert "## 参考方案" in content


def test_full_plan_appendix_has_all_sections():
    content = FULL_PLAN_APPENDIX.format(
        pseudocode="pseudo",
        data_comparison="data",
        priority_and_dependencies="prio",
    )
    assert "## 伪代码 / 架构变更" in content
    assert "## 数据对比" in content
    assert "## 优先级与依赖" in content


def test_generate_standard_plan_no_llm():
    ws = Path(tempfile.mkdtemp())
    (ws / ".onep").mkdir(parents=True, exist_ok=True)
    item = StrategyItem(title="Test", file_location="f:1")
    result = generate_standard_plan(item, ws, llm_adapter=None)
    assert result is None


def test_generate_full_plan_no_llm():
    ws = Path(tempfile.mkdtemp())
    (ws / ".onep").mkdir(parents=True, exist_ok=True)
    item = StrategyItem(title="Test", file_location="f:1")
    result = generate_full_plan(item, "# standard", ws, llm_adapter=None)
    assert result is None
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_strategy/test_planner.py -v`
Expected: 6 tests pass

- [ ] **Step 4: Commit**

```bash
git add onep/strategy/planner.py tests/test_strategy/test_planner.py
git commit -m "feat: add plan generator (standard and full versions)"
```

---

### Task 7: Layer 3 — Workbench (dialogue engine)

**Files:**
- Create: `onep/strategy/workbench.py`
- Create: `tests/test_strategy/test_workbench.py`

- [ ] **Step 1: Create onep/strategy/workbench.py**

```python
"""
Layer 3: Interactive dialogue workbench.

Manages the conversation loop, slash command parsing, context routing,
and multi-item state management.
"""
from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from onep.strategy.models import (
    WorkbenchState, StrategyItem, DialogueTurn, ItemStatus, PlanVersion,
)
from onep.strategy.persistence import (
    save_workbench, load_workbench, append_dialogue,
)
from onep.strategy.planner import generate_standard_plan, generate_full_plan

console = Console()

SLASH_COMMANDS = {
    "list": "list",
    "focus": "focus",
    "search": "search",
    "plan": "plan",
    "expand": "expand",
    "compare": "compare",
    "merge": "merge",
    "discard": "discard",
    "save": "save",
    "status": "status",
    "exit": "exit",
}


def parse_input(user_input: str) -> tuple[str | None, str | None, str]:
    """
    Parse user input.

    Returns (slash_command, args, message).
    - If input is a slash command: returns (command, args, "")
    - If input is natural language: returns (None, None, input)
    """
    text = user_input.strip()
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0][1:]
        args = parts[1] if len(parts) > 1 else ""
        if cmd in SLASH_COMMANDS:
            return cmd, args, ""
        return None, None, text  # Unknown slash command, treat as text
    return None, None, text


def handle_slash_command(
    cmd: str,
    args: str,
    wb: WorkbenchState,
    workspace: Path,
    llm_adapter=None,
) -> WorkbenchState:
    """Execute a slash command against the workbench state."""

    if cmd == "list":
        _cmd_list(wb)

    elif cmd == "focus":
        item_id = _resolve_item_id(args, wb)
        if item_id:
            wb.current_item_id = item_id
            item = _find_item(wb, item_id)
            console.print(f"[green]已切换到: [{item_id}] {item.title if item else '?'}[/green]")
        else:
            console.print(f"[red]未找到方向: {args}[/red]")

    elif cmd == "search":
        keyword = args.lower()
        found = [item for item in wb.items
                 if keyword in item.title.lower() or keyword in " ".join(item.tags).lower()]
        if found:
            console.print(f"[bold]搜索 '{keyword}' 结果:[/bold]")
            for item in found:
                _print_item(item)
        else:
            console.print(f"[yellow]未找到匹配 '{keyword}' 的方向[/yellow]")

    elif cmd == "plan":
        _cmd_generate_plan(args, wb, workspace, llm_adapter, version="standard")

    elif cmd == "expand":
        _cmd_generate_plan(args, wb, workspace, llm_adapter, version="full")

    elif cmd == "compare":
        ids = args.split()
        if len(ids) >= 2:
            _cmd_compare(ids[0], ids[1], wb)
        else:
            console.print("[red]用法: /compare <n> <m>[/red]")

    elif cmd == "merge":
        ids = args.split()
        if len(ids) >= 2:
            _cmd_merge(ids[0], ids[1], wb)
        else:
            console.print("[red]用法: /merge <n> <m>[/red]")

    elif cmd == "discard":
        item_id = _resolve_item_id(args, wb)
        if item_id:
            item = _find_item(wb, item_id)
            if item:
                item.discard()
                console.print(f"[yellow]已忽略: [{item_id}] {item.title}[/yellow]")

    elif cmd == "save":
        save_workbench(workspace, wb)
        console.print("[green]工作台已保存。[/green]")

    elif cmd == "status":
        _cmd_status(wb)

    elif cmd == "exit":
        save_workbench(workspace, wb)
        console.print(f"[green]工作台已保存。恢复会话: onep strategy resume {wb.project_name}[/green]")

    return wb


def _resolve_item_id(args: str, wb: WorkbenchState) -> str | None:
    """Resolve various ID formats: '3', 'si-3', or exact id."""
    args = args.strip()
    if args.startswith("si-"):
        return args if _find_item(wb, args) else None
    if args.isdigit():
        idx = int(args) - 1
        active = [item for item in wb.items if item.status != ItemStatus.DISCARDED]
        if 0 <= idx < len(active):
            return active[idx].id
    return None


def _find_item(wb: WorkbenchState, item_id: str) -> StrategyItem | None:
    for item in wb.items:
        if item.id == item_id:
            return item
    return None


def _print_item(item: StrategyItem) -> None:
    impact_color = {"high": "red", "medium": "yellow", "low": "dim"}
    color = impact_color.get(item.impact, "white")
    status_icon = {
        ItemStatus.PENDING: "○",
        ItemStatus.DISCUSSING: "●",
        ItemStatus.PLAN_DRAFTED: "📋",
        ItemStatus.PLAN_REVIEWED: "✅",
        ItemStatus.DISCARDED: "✗",
    }
    icon = status_icon.get(item.status, "?")
    tags_str = ", ".join(item.tags) if item.tags else ""
    console.print(
        f"  [{icon}] [{item.id}] [{color}]{item.title}[/{color}] — {item.file_location}"
        + (f" [{tags_str}]" if tags_str else "")
    )


def _cmd_list(wb: WorkbenchState) -> None:
    active = [item for item in wb.items if item.status != ItemStatus.DISCARDED]
    discarded = [item for item in wb.items if item.status == ItemStatus.DISCARDED]

    console.print(f"\n[bold]优化方向 ({len(active)} 个活跃)[/bold]")
    for item in active:
        _print_item(item)

    if discarded:
        console.print(f"\n[dim]已忽略 ({len(discarded)} 个)[/dim]")


def _cmd_status(wb: WorkbenchState) -> None:
    total = len(wb.items)
    active = len([i for i in wb.items if i.status != ItemStatus.DISCARDED])
    drafted = len([i for i in wb.items if i.status == ItemStatus.PLAN_DRAFTED])
    reviewed = len([i for i in wb.items if i.status == ItemStatus.PLAN_REVIEWED])
    discarded = len([i for i in wb.items if i.status == ItemStatus.DISCARDED])

    table = Table(title=f"分析进度: {wb.project_name}")
    table.add_column("指标", style="cyan")
    table.add_column("数量")
    table.add_row("源路径", wb.source_path)
    table.add_row("优化点总数", str(total))
    table.add_row("活跃中", str(active))
    table.add_row("Plan 已生成", str(drafted))
    table.add_row("Plan 已审核", str(reviewed))
    table.add_row("已忽略", str(discarded))
    table.add_row("扫描完成", "✓" if wb.scan_complete else "○")
    table.add_row("分析完成", "✓" if wb.analysis_complete else "○")
    console.print(table)


def _cmd_generate_plan(
    args: str,
    wb: WorkbenchState,
    workspace: Path,
    llm_adapter=None,
    version: str = "standard",
) -> None:
    item_id = _resolve_item_id(args, wb)
    if not item_id:
        console.print(f"[red]未找到方向: {args}[/red]")
        return

    item = _find_item(wb, item_id)
    if not item:
        return

    if version == "standard":
        active = [i for i in wb.items if i.status != ItemStatus.DISCARDED]
        plan_index = active.index(item) + 1 if item in active else 1
        path = generate_standard_plan(item, workspace, llm_adapter, plan_index)
        if path:
            console.print(f"[green][{item.id}] Plan 已生成: {path}[/green]")
        else:
            console.print("[yellow]Plan 生成需要 LLM 连接（当前不可用）。[/yellow]")
    elif version == "full":
        if not item.plan_path or item.plan_version != PlanVersion.STANDARD:
            console.print("[red]请先生成标准版 Plan，审核通过后再生成完整版。[/red]")
            return
        plan_content = Path(item.plan_path).read_text() if item.plan_path else ""
        path = generate_full_plan(item, plan_content, workspace, llm_adapter)
        if path:
            console.print(f"[green][{item.id}] 完整版 Plan 已生成: {path}[/green]")
        else:
            console.print("[yellow]完整版 Plan 生成需要 LLM 连接（当前不可用）。[/yellow]")


def _cmd_compare(id_a: str, id_b: str, wb: WorkbenchState) -> None:
    item_a = _find_item(wb, _resolve_item_id(id_a, wb) or id_a)
    item_b = _find_item(wb, _resolve_item_id(id_b, wb) or id_b)

    if not item_a or not item_b:
        console.print("[red]至少一个方向未找到。[/red]")
        return

    table = Table(title=f"对比: [{item_a.id}] vs [{item_b.id}]")
    table.add_column("维度")
    table.add_column(item_a.title)
    table.add_column(item_b.title)
    table.add_row("影响", item_a.impact, item_b.impact)
    table.add_row("标签", ", ".join(item_a.tags), ", ".join(item_b.tags))
    table.add_row("文件", item_a.file_location, item_b.file_location)
    table.add_row("摘要", item_a.summary[:100], item_b.summary[:100])
    console.print(table)


def _cmd_merge(id_a: str, id_b: str, wb: WorkbenchState) -> None:
    item_a = _find_item(wb, _resolve_item_id(id_a, wb) or id_a)
    item_b = _find_item(wb, _resolve_item_id(id_b, wb) or id_b)

    if not item_a or not item_b:
        console.print("[red]至少一个方向未找到。[/red]")
        return

    merged = StrategyItem(
        title=f"{item_a.title} + {item_b.title}",
        file_location=f"{item_a.file_location}, {item_b.file_location}",
        summary=f"[合并自 {item_a.id}] {item_a.summary}\n[合并自 {item_b.id}] {item_b.summary}",
        impact=_higher_impact(item_a.impact, item_b.impact),
        tags=list(set(item_a.tags + item_b.tags)),
    )
    item_a.discard()
    item_b.discard()
    wb.items.append(merged)
    console.print(f"[green]已合并为: [{merged.id}] {merged.title}[/green]")


def _higher_impact(a: str, b: str) -> str:
    order = {"high": 3, "medium": 2, "low": 1}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def run_dialogue_loop(
    workspace: Path,
    wb: WorkbenchState,
    llm_adapter=None,
) -> WorkbenchState:
    """
    Run the interactive dialogue loop.

    Reads user input from stdin, dispatches slash commands or routes to
    the Strategy Architect for natural language responses.
    Returns the final workbench state on exit.
    """
    console.print(Panel.fit(
        f"[bold green]策略分析对话模式[/bold green]\n"
        f"项目: {wb.project_name}\n"
        f"发现 {len(wb.items)} 个优化方向\n\n"
        f"输入自然语言与Agent讨论，或使用 / 命令操作",
        title="Strategy Workbench",
    ))
    console.print("输入 [bold]/help[/bold] 查看所有命令，[bold]/exit[/bold] 退出\n")

    while True:
        try:
            user_input = console.input("[bold cyan]💬 You:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            save_workbench(workspace, wb)
            console.print("\n[green]工作台已保存。[/green]")
            break

        if not user_input:
            continue

        cmd, args, message = parse_input(user_input)

        if cmd:
            if cmd == "exit":
                handle_slash_command(cmd, args, wb, workspace, llm_adapter)
                break
            else:
                handle_slash_command(cmd, args, wb, workspace, llm_adapter)

            append_dialogue(workspace, DialogueTurn(
                role="user",
                content=message or f"/{cmd} {args}".strip(),
                item_id=wb.current_item_id,
                slash_command=f"/{cmd} {args}".strip() if cmd else None,
            ))
        else:
            # Natural language — route to strategy architect
            append_dialogue(workspace, DialogueTurn(
                role="user",
                content=message,
                item_id=wb.current_item_id,
            ))

            if llm_adapter is not None:
                context = _build_dialogue_context(wb, message)
                response = llm_adapter.invoke(
                    system_prompt=(
                        "你是一位策略架构师，正在与用户讨论代码策略优化。"
                        "根据用户的问题提供有帮助的深入分析。"
                        "回答要具体，引用代码中的实际策略逻辑。"
                        "用中文回复。"
                    ),
                    user_prompt=context,
                    stage_name="strategy_architect",
                )
                console.print(f"\n[bold green]🧠 Strategy Architect:[/bold green] {response}\n")
                append_dialogue(workspace, DialogueTurn(
                    role="agent",
                    content=response,
                    item_id=wb.current_item_id,
                ))
            else:
                console.print(
                    "\n[yellow]LLM 不可用（请配置 API 密钥）。"
                    "Slash 命令仍然可用。[/yellow]\n"
                )

    return wb


def _build_dialogue_context(wb: WorkbenchState, user_message: str) -> str:
    """Build dialogue context for the LLM."""
    current_item = _find_item(wb, wb.current_item_id) if wb.current_item_id else None

    context_parts = [f"项目: {wb.project_name}"]
    context_parts.append(f"源路径: {wb.source_path}")

    if current_item:
        context_parts.append(f"\n当前讨论方向: [{current_item.id}] {current_item.title}")
        context_parts.append(f"文件位置: {current_item.file_location}")
        context_parts.append(f"问题摘要: {current_item.summary}")
        context_parts.append(f"标签: {', '.join(current_item.tags)}")
        context_parts.append(f"影响: {current_item.impact}")

    # Include recent dialogue history (last 10 turns)
    recent = wb.dialogue[-10:] if wb.dialogue else []
    if recent:
        context_parts.append("\n最近对话:")
        for turn in recent:
            role_label = "用户" if turn.role == "user" else "Agent"
            context_parts.append(f"[{role_label}]: {turn.content[:200]}")

    context_parts.append(f"\n用户消息: {user_message}")
    return "\n".join(context_parts)
```

- [ ] **Step 2: Create tests/test_strategy/test_workbench.py**

```python
import tempfile
from pathlib import Path

from onep.strategy.models import (
    WorkbenchState, StrategyItem, ItemStatus,
)
from onep.strategy.workbench import (
    parse_input, handle_slash_command, _resolve_item_id, _find_item,
    _higher_impact,
)


def test_parse_slash_command():
    cmd, args, msg = parse_input("/focus 3")
    assert cmd == "focus"
    assert args == "3"
    assert msg == ""


def test_parse_natural_language():
    cmd, args, msg = parse_input("展开说说第3个")
    assert cmd is None
    assert args is None
    assert msg == "展开说说第3个"


def test_parse_unknown_slash():
    cmd, args, msg = parse_input("/unknown_command test")
    assert cmd is None
    assert args is None
    assert msg == "/unknown_command test"  # treated as text


def test_resolve_item_id_numeric():
    wb = WorkbenchState(project_name="test", source_path="./repo")
    item = StrategyItem(title="Test", file_location="f:1")
    wb.items.append(item)
    result = _resolve_item_id("1", wb)
    assert result == item.id


def test_resolve_item_id_si_format():
    wb = WorkbenchState(project_name="test", source_path="./repo")
    item = StrategyItem(title="Test", file_location="f:1")
    wb.items.append(item)
    result = _resolve_item_id(item.id, wb)
    assert result == item.id


def test_resolve_item_id_skips_discarded():
    wb = WorkbenchState(project_name="test", source_path="./repo")
    d1 = StrategyItem(title="Discarded", file_location="f:1")
    d1.discard()
    wb.items.append(d1)
    a1 = StrategyItem(title="Active", file_location="g:1")
    wb.items.append(a1)
    result = _resolve_item_id("1", wb)
    assert result == a1.id


def test_higher_impact():
    assert _higher_impact("high", "low") == "high"
    assert _higher_impact("low", "medium") == "medium"
    assert _higher_impact("medium", "medium") == "medium"


def test_handle_slash_list(tmp_path):
    wb = WorkbenchState(project_name="test", source_path="./repo")
    wb.items.append(StrategyItem(title="A", file_location="a:1"))
    result = handle_slash_command("list", "", wb, tmp_path)
    assert result is wb  # returns same workbench


def test_handle_slash_discard(tmp_path):
    wb = WorkbenchState(project_name="test", source_path="./repo")
    item = StrategyItem(title="Remove Me", file_location="r:1")
    wb.items.append(item)
    handle_slash_command("discard", "1", wb, tmp_path)
    assert item.status == ItemStatus.DISCARDED
```

- [ ] **Step 3: Run tests**

Run: `python -m pytest tests/test_strategy/test_workbench.py -v`
Expected: 9 tests pass

- [ ] **Step 4: Commit**

```bash
git add onep/strategy/workbench.py tests/test_strategy/test_workbench.py
git commit -m "feat: add Layer 3 dialogue workbench engine"
```

---

### Task 8: CLI commands — analyze and strategy

**Files:**
- Create: `onep/cli/analyze.py`
- Create: `onep/cli/strategy_cmd.py`

- [ ] **Step 1: Create onep/cli/analyze.py**

```python
"""onep analyze — analyze existing codebases."""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
import subprocess
import tempfile

import click
from rich.console import Console

from onep.config import load_config
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode
from onep.strategy.models import WorkbenchState
from onep.strategy.scanner import scan_files, get_strategy_files
from onep.strategy.analyzer import analyze_strategies
from onep.strategy.persistence import save_workbench
from onep.strategy.workbench import run_dialogue_loop

console = Console()


@click.command()
@click.argument("source", type=str)
@click.option("--mode", "-m", type=click.Choice(["code", "strategy"]), default="strategy",
              help="Analysis mode")
@click.option("--name", "-n", default=None, help="Project name")
def analyze_cmd(source: str, mode: str, name: str | None):
    """Analyze a codebase for strategy optimizations.

    SOURCE can be a local path or a git repository URL.

    \b
    Examples:
        onep analyze ./my-repo --mode strategy
        onep analyze https://github.com/user/repo --mode strategy --name my-analysis
    """
    config = load_config()
    init_db()

    # Determine source path (clone if git URL)
    source_path = _resolve_source(source)

    # Generate project name
    if name is None:
        clean = re.sub(r'[^\w一-鿿]', '', Path(source).name)[:20]
        name = clean or f"analysis-{uuid.uuid4().hex[:6]}"

    # Set up workspace
    project_root = Path(os.path.expanduser(config.project.root_dir))
    projects_dir = project_root / "projects" / name
    workspace = projects_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    # Create project record
    project = Project(
        name=name,
        mode=ProjectMode.BROWNFIELD,
        workspace_path=str(workspace),
    )
    insert_project(project)

    console.print(f"[bold]Source:[/bold] {source_path}")
    console.print(f"[bold]Workspace:[/bold] {workspace}")

    if mode == "strategy":
        _run_strategy_mode(source_path, workspace, name)
    else:
        console.print(f"[yellow]Mode '{mode}' not yet implemented.[/yellow]")


def _resolve_source(source: str) -> Path:
    """Resolve source to a local path. Clones if it's a git URL."""
    if source.startswith(("http://", "https://", "git@", "ssh://")):
        tmpdir = Path(tempfile.mkdtemp(prefix="onep-clone-"))
        console.print(f"[dim]Cloning {source}...[/dim]")
        subprocess.run(
            ["git", "clone", "--depth", "1", source, str(tmpdir)],
            check=True, capture_output=True,
        )
        return tmpdir
    return Path(source).resolve()


def _run_strategy_mode(source_path: Path, workspace: Path, project_name: str) -> None:
    """Execute the strategy analysis pipeline."""
    console.print("\n[bold cyan]=== Layer 1: 快速扫描 ===[/bold cyan]")

    # Layer 1: Scan
    results = scan_files(source_path, llm_adapter=None)
    strategy_files = get_strategy_files(results)
    console.print(f"扫描完成: {len(results)} 个文件, {len(strategy_files)} 个策略密集文件")

    # Layer 2: Analyze
    console.print("\n[bold cyan]=== Layer 2: 深度分析 ===[/bold cyan]")
    items = analyze_strategies(strategy_files, source_path, llm_adapter=None)
    console.print(f"分析完成: 发现 {len(items)} 个优化方向")

    # Initialize workbench
    wb = WorkbenchState(
        project_name=project_name,
        source_path=str(source_path),
        items=items,
        scan_complete=True,
        analysis_complete=True,
    )

    # Print discovered items
    for i, item in enumerate(items, 1):
        impact_color = {"high": "red", "medium": "yellow", "low": "dim"}
        color = impact_color.get(item.impact, "white")
        tags_str = f" [{', '.join(item.tags)}]" if item.tags else ""
        console.print(
            f"  [{i}] [{color}]{item.title}[/{color}] — {item.file_location}{tags_str} — 影响: {item.impact}"
        )

    # Save initial state
    save_workbench(workspace, wb)

    # Layer 3: Dialogue
    console.print(f"\n[bold cyan]=== Layer 3: 交互式对话 ===[/bold cyan]")
    console.print(f"发现 {len(items)} 个优化方向。输入自然语言与策略架构师讨论。\n")

    # Check if LLM is available
    llm = None
    try:
        from onep.llm.adapters import get_llm
        llm = get_llm()
        console.print("[dim]LLM 连接可用。[/dim]\n")
    except Exception:
        console.print("[yellow]LLM 未配置。Slash 命令可用，但自然语言对话需要 API 密钥。[/yellow]\n")

    wb = run_dialogue_loop(workspace, wb, llm_adapter=llm)

    console.print(f"\n[bold green]分析会话结束。[/bold green]")
    console.print(f"恢复: [bold cyan]onep strategy resume {project_name}[/bold cyan]")


COMMANDS = [analyze_cmd]
```

- [ ] **Step 2: Create onep/cli/strategy_cmd.py**

```python
"""onep strategy — manage strategy analysis sessions."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from onep.config import load_config
from onep.persistence.database import init_db, list_projects
from onep.strategy.models import ItemStatus
from onep.strategy.persistence import load_workbench
from onep.strategy.workbench import run_dialogue_loop

console = Console()


@click.group()
def strategy_group():
    """Manage strategy analysis sessions."""
    pass


@strategy_group.command()
@click.argument("project_name", type=str)
def resume(project_name: str):
    """Resume a previous strategy analysis session."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return

    workspace = Path(project.workspace_path)
    wb = load_workbench(workspace)
    if wb is None:
        console.print(f"[red]No strategy session found for '{project_name}'.[/red]")
        return

    console.print(f"[green]恢复会话: {project_name}[/green]")
    console.print(f"优化方向: {len(wb.items)} 个")

    llm = None
    try:
        from onep.llm.adapters import get_llm
        llm = get_llm()
    except Exception:
        pass

    run_dialogue_loop(workspace, wb, llm_adapter=llm)


@strategy_group.command()
@click.argument("project_name", type=str)
def status(project_name: str):
    """Show analysis progress for a strategy session."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return

    workspace = Path(project.workspace_path)
    wb = load_workbench(workspace)
    if wb is None:
        console.print(f"[red]No strategy session found for '{project_name}'.[/red]")
        return

    total = len(wb.items)
    active = len([i for i in wb.items if i.status != ItemStatus.DISCARDED])
    drafted = len([i for i in wb.items if i.status == ItemStatus.PLAN_DRAFTED])
    reviewed = len([i for i in wb.items if i.status == ItemStatus.PLAN_REVIEWED])
    discarded = len([i for i in wb.items if i.status == ItemStatus.DISCARDED])

    table = Table(title=f"策略分析: {project_name}")
    table.add_column("指标", style="cyan")
    table.add_column("数值")
    table.add_row("源路径", wb.source_path)
    table.add_row("优化点总数", str(total))
    table.add_row("活跃", str(active))
    table.add_row("Plan 已生成", str(drafted))
    table.add_row("Plan 已审核", str(reviewed))
    table.add_row("已忽略", str(discarded))
    table.add_row("扫描完成", "✓" if wb.scan_complete else "○")
    console.print(table)


@strategy_group.command()
@click.argument("project_name", type=str)
@click.option("--format", "-f", "fmt", type=click.Choice(["md", "json"]), default="md",
              help="Export format")
@click.option("--items", "-i", default=None, help="Comma-separated item numbers to export")
def export(project_name: str, fmt: str, items: str | None):
    """Export analysis results."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return

    workspace = Path(project.workspace_path)
    wb = load_workbench(workspace)
    if wb is None:
        console.print(f"[red]No strategy session found for '{project_name}'.[/red]")
        return

    # Filter items
    active = [i for i in wb.items if i.status != ItemStatus.DISCARDED]
    if items:
        indices = [int(x.strip()) - 1 for x in items.split(",")]
        selected = [active[i] for i in indices if 0 <= i < len(active)]
    else:
        selected = active

    if fmt == "md":
        output = _export_markdown(selected, wb)
    else:
        import json
        output = json.dumps([{
            "id": i.id, "title": i.title, "file_location": i.file_location,
            "tags": i.tags, "impact": i.impact, "summary": i.summary,
            "status": i.status.value, "plan_path": i.plan_path,
        } for i in selected], ensure_ascii=False, indent=2)

    console.print(output)


def _export_markdown(items, wb) -> str:
    lines = [f"# 策略分析报告: {wb.project_name}\n"]
    lines.append(f"源路径: {wb.source_path}\n")
    lines.append(f"分析时间: {items[0].created_at if items else 'N/A'}\n\n---\n")

    for item in items:
        impact_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        emoji = impact_emoji.get(item.impact, "⚪")
        lines.append(f"## {emoji} {item.title}\n")
        lines.append(f"- **文件位置**: {item.file_location}")
        lines.append(f"- **标签**: {', '.join(item.tags) if item.tags else '无'}")
        lines.append(f"- **影响**: {item.impact}")
        lines.append(f"- **状态**: {item.status.value}")
        lines.append(f"\n{item.summary}\n")
        if item.plan_path:
            lines.append(f"📋 Plan: {item.plan_path}\n")
        lines.append("---\n")

    return "\n".join(lines)


COMMANDS = [strategy_group]
```

- [ ] **Step 3: Update onep/main.py** — verify `register_commands` discovers new modules

Run: `python -m onep.main --help`
Expected: shows `analyze` and `strategy` in command list

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_strategy/ -v`
Expected: all strategy tests pass

- [ ] **Step 5: Commit**

```bash
git add onep/cli/analyze.py onep/cli/strategy_cmd.py
git commit -m "feat: add CLI commands for strategy analysis"
```

---

### Task 9: Brownfield orchestrator + integration

**Files:**
- Create: `onep/orchestrator/brownfield.py`
- Modify: `onep/orchestrator/crew.py`
- Create: `tests/test_strategy/test_integration.py`

- [ ] **Step 1: Create onep/orchestrator/brownfield.py**

```python
"""Brownfield pipeline — analyze existing codebases."""
from __future__ import annotations

from crewai import Task

from onep.agents.registry import get_agent
from onep.persistence.models import Project, PipelineState


BROWNFIELD_STAGES = [
    {"name": "analyzer", "agent": "strategy_architect", "description": "策略分析"},
]


def build_brownfield_tasks(project: Project, state: PipelineState) -> list[Task]:
    """Build CrewAI Task list for the Brownfield pipeline."""
    tasks = []
    for stage in BROWNFIELD_STAGES:
        task = Task(
            description=f"Execute strategy analysis for project {project.name}",
            expected_output=f"Stage {stage['name']} completed.",
            agent=get_agent(stage["agent"]),
        )
        tasks.append(task)
    return tasks
```

- [ ] **Step 2: Update onep/orchestrator/crew.py**

Read the file first, replace the `ValueError` path in `create_crew`:

```python
else:
    from onep.orchestrator.brownfield import build_brownfield_tasks
    tasks = build_brownfield_tasks(project, state)
```

- [ ] **Step 3: Create tests/test_strategy/test_integration.py**

```python
"""Integration tests: verify all strategy components wire together."""
import tempfile
from pathlib import Path

from onep.strategy.models import (
    StrategyItem, DialogueTurn, WorkbenchState,
    ItemStatus, PlanVersion,
)
from onep.strategy.persistence import (
    save_workbench, load_workbench, append_dialogue, save_plan,
)
from onep.strategy.scanner import _walk_files, _batch_files, get_strategy_files, ScanResult
from onep.strategy.analyzer import _build_analysis_prompt, _parse_analysis_response
from onep.strategy.planner import _build_standard_prompt, _build_full_prompt
from onep.strategy.workbench import parse_input, _resolve_item_id, _higher_impact


def test_full_data_roundtrip():
    """Create workbench, save, load, verify integrity."""
    ws = Path(tempfile.mkdtemp())

    wb = WorkbenchState(project_name="integration", source_path="./repo")
    wb.items.append(StrategyItem(
        title="Full roundtrip test",
        file_location="main.py:42",
        summary="Test persistence",
        impact="high",
        tags=["测试"],
    ))
    wb.scan_complete = True
    wb.analysis_complete = True

    save_workbench(ws, wb)
    loaded = load_workbench(ws)

    assert loaded is not None
    assert loaded.project_name == "integration"
    assert len(loaded.items) == 1
    assert loaded.items[0].title == "Full roundtrip test"
    assert loaded.items[0].impact == "high"
    assert loaded.scan_complete is True


def test_dialogue_roundtrip():
    """Append dialogue, verify it loads back."""
    ws = Path(tempfile.mkdtemp())
    wb = WorkbenchState(project_name="dialogue-test", source_path="./repo")
    save_workbench(ws, wb)

    append_dialogue(ws, DialogueTurn(role="user", content="第一条消息"))
    append_dialogue(ws, DialogueTurn(role="agent", content="第一条回复", item_id="si-1"))
    append_dialogue(ws, DialogueTurn(role="user", content="/focus 1", slash_command="/focus 1"))

    loaded = load_workbench(ws)
    assert loaded is not None
    assert len(loaded.dialogue) == 3
    assert loaded.dialogue[0].content == "第一条消息"
    assert loaded.dialogue[2].slash_command == "/focus 1"


def test_slash_command_full_set():
    """Verify all 11 slash commands parse correctly."""
    commands = {
        "/list": "list",
        "/focus 3": "focus",
        "/search 缓存": "search",
        "/plan 1": "plan",
        "/expand 1": "expand",
        "/compare 1 4": "compare",
        "/merge 2 5": "merge",
        "/discard 8": "discard",
        "/save": "save",
        "/status": "status",
        "/exit": "exit",
    }
    for user_input, expected_cmd in commands.items():
        cmd, args, msg = parse_input(user_input)
        assert cmd == expected_cmd, f"Failed for {user_input}"


def test_plan_generation_flow():
    """Verify plan templates produce valid output."""
    from onep.strategy.planner import STANDARD_PLAN_TEMPLATE, FULL_PLAN_APPENDIX

    standard = STANDARD_PLAN_TEMPLATE.format(
        title="Test Plan",
        file_location="test.py:1",
        tags="测试, 性能",
        impact="high",
        timestamp="2026-01-01",
        problem_description="问题",
        optimization_direction="方向",
        implementation_approach="方案",
        risk_assessment="风险",
        reference_solutions="参考",
    )
    assert "Test Plan" in standard
    assert "## 问题描述" in standard
    assert "## 风险评估" in standard

    full = FULL_PLAN_APPENDIX.format(
        pseudocode="pseudo",
        data_comparison="data",
        priority_and_dependencies="deps",
    )
    assert "## 伪代码 / 架构变更" in full
    assert "## 数据对比" in full
    assert "## 优先级与依赖" in full
```

- [ ] **Step 4: Run all strategy tests**

Run: `python -m pytest tests/test_strategy/ -v`
Expected: all ~30 tests pass

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass (51 + strategy tests)

- [ ] **Step 6: Commit**

```bash
git add onep/orchestrator/brownfield.py onep/orchestrator/crew.py tests/test_strategy/test_integration.py
git commit -m "feat: add Brownfield orchestrator and strategy integration tests"
```
