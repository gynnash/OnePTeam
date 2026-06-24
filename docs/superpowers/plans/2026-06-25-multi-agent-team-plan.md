# OnePTeam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the OnePTeam CLI tool that orchestrates a multi-agent software development team (PM → Designer → Architect → Developer → Tester → DevOps) to build full-stack web apps from natural language requirements.

**Architecture:** Five-layer system — CLI (Click+Rich), CrewAI orchestrator for top-level pipeline, LangGraph for complex sub-flows (code review loop, test retry), tool layer for safe filesystem/Git/Docker operations, and persistence via Git repos + SQLite. MVP delivers Greenfield mode only.

**Tech Stack:** Python 3.12+, CrewAI, LangGraph, Click, Rich, GitPython, Docker SDK, SQLite, pytest

**MVP Scope:** `onep create "一个支持登录的记事本应用"` — run the full Greenfield pipeline end-to-end with a minimal Notes app. Test Agent does basic smoke tests. DevOps Agent deploys single Docker container.

---

## File Map

```
onep/
├── __init__.py
├── main.py                      # CLI entry, Click app with plugin loading
├── config.py                    # Global config from ~/.onep/config.yaml
├── cli/
│   ├── __init__.py
│   ├── create.py                # onep create
│   ├── status.py                # onep status / pause / resume / approve / reject
│   └── show.py                  # onep show <artifact>
├── orchestrator/
│   ├── __init__.py
│   ├── crew.py                  # Crew factory, mode dispatch
│   └── greenfield.py            # Greenfield 6-stage pipeline
├── agents/
│   ├── __init__.py
│   ├── registry.py              # Agent registry (name -> Agent factory)
│   ├── pm.py                    # Product Manager
│   ├── designer.py              # UI/UX Designer
│   ├── architect.py             # Architect
│   ├── developer.py             # Developer
│   ├── tester.py                # Tester
│   └── devops.py                # DevOps
├── subflows/
│   ├── __init__.py
│   ├── code_review.py           # Code review loop (LangGraph)
│   └── test_retry.py            # Test failure retry loop (LangGraph)
├── tools/
│   ├── __init__.py
│   ├── base.py                  # BaseTool abstract class
│   ├── filesystem.py            # File read/write within workspace
│   ├── git.py                   # Git operations (GitPython)
│   ├── shell.py                 # Safe shell execution
│   ├── docker.py                # Docker Compose operations
│   └── lint.py                  # Basic lint/format check
├── persistence/
│   ├── __init__.py
│   ├── database.py              # SQLite operations
│   ├── state.py                 # state.yaml read/write
│   └── models.py                # Dataclass models
└── llm/
    ├── __init__.py
    ├── router.py                # Model router (task -> model)
    └── adapters.py              # DeepSeek + OpenAI adapters via LiteLLM
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `onep/__init__.py`
- Create: `onep/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create pyproject.toml with dependencies**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "onep"
version = "0.1.0"
description = "Multi-Agent Full-Stack Software Development Team"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "rich>=13.0",
    "crewai>=0.80",
    "langgraph>=0.2",
    "langchain>=0.3",
    "gitpython>=3.1",
    "pyyaml>=6.0",
    "docker>=7.0",
    "litellm>=1.50",
]

[project.scripts]
onep = "onep.main:cli"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
]
```

- [ ] **Step 2: Create onep/__init__.py**

```python
"""OnePTeam - Multi-Agent Full-Stack Software Development Team."""
__version__ = "0.1.0"
```

- [ ] **Step 3: Create onep/config.py**

```python
"""Global configuration loaded from ~/.onep/config.yaml."""
from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field

import yaml


DEFAULT_CONFIG_YAML = """\
# OnePTeam configuration
llm:
  default_model: deepseek/deepseek-chat
  default_provider: deepseek
  complex_model: openai/gpt-5.5
  complex_provider: openai
  models:
    deepseek:
      api_key: ""
      api_base: https://api.deepseek.com/v1
    openai:
      api_key: ""
      api_base: https://api.openai.com/v1

project:
  root_dir: ~/.onep

pipeline:
  auto_approve: false
  max_retries: 3
  test_timeout: 300
"""


@dataclass
class LLMConfig:
    default_model: str = "deepseek/deepseek-chat"
    default_provider: str = "deepseek"
    complex_model: str = "openai/gpt-5.5"
    complex_provider: str = "openai"
    models: dict = field(default_factory=dict)


@dataclass
class ProjectConfig:
    root_dir: str = "~/.onep"


@dataclass
class PipelineConfig:
    auto_approve: bool = False
    max_retries: int = 3
    test_timeout: int = 300


@dataclass
class Config:
    llm: LLMConfig = field(default_factory=LLMConfig)
    project: ProjectConfig = field(default_factory=ProjectConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)


def _config_dir() -> Path:
    return Path(os.path.expanduser("~/.onep"))


def _config_path() -> Path:
    return _config_dir() / "config.yaml"


def _ensure_config() -> None:
    config_dir = _config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = _config_path()
    if not config_file.exists():
        config_file.write_text(DEFAULT_CONFIG_YAML)


def load_config() -> Config:
    """Load config from ~/.onep/config.yaml, creating default if absent."""
    _ensure_config()
    raw = yaml.safe_load(_config_path().read_text()) or {}

    llm_raw = raw.get("llm", {})
    llm = LLMConfig(
        default_model=llm_raw.get("default_model", "deepseek/deepseek-chat"),
        default_provider=llm_raw.get("default_provider", "deepseek"),
        complex_model=llm_raw.get("complex_model", "openai/gpt-5.5"),
        complex_provider=llm_raw.get("complex_provider", "openai"),
        models=llm_raw.get("models", {}),
    )

    project_raw = raw.get("project", {})
    project = ProjectConfig(root_dir=project_raw.get("root_dir", "~/.onep"))

    pipeline_raw = raw.get("pipeline", {})
    pipeline = PipelineConfig(
        auto_approve=pipeline_raw.get("auto_approve", False),
        max_retries=pipeline_raw.get("max_retries", 3),
        test_timeout=pipeline_raw.get("test_timeout", 300),
    )

    return Config(llm=llm, project=project, pipeline=pipeline)


def save_config(config: Config) -> None:
    """Save config back to disk."""
    _ensure_config()
    raw = {
        "llm": {
            "default_model": config.llm.default_model,
            "default_provider": config.llm.default_provider,
            "complex_model": config.llm.complex_model,
            "complex_provider": config.llm.complex_provider,
            "models": config.llm.models,
        },
        "project": {"root_dir": config.project.root_dir},
        "pipeline": {
            "auto_approve": config.pipeline.auto_approve,
            "max_retries": config.pipeline.max_retries,
            "test_timeout": config.pipeline.test_timeout,
        },
    }
    _config_path().write_text(yaml.dump(raw, default_flow_style=False))
```

- [ ] **Step 4: Create tests/__init__.py**

```python
"""Tests for OnePTeam."""
```

- [ ] **Step 5: Create tests/test_config.py**

```python
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml

from onep.config import (
    Config,
    LLMConfig,
    ProjectConfig,
    PipelineConfig,
    load_config,
    save_config,
    _config_dir,
    _config_path,
)


def test_llm_config_defaults():
    cfg = LLMConfig()
    assert cfg.default_model == "deepseek/deepseek-chat"
    assert cfg.complex_model == "openai/gpt-5.5"


def test_config_default_values():
    cfg = Config()
    assert cfg.llm.default_model == "deepseek/deepseek-chat"
    assert cfg.pipeline.max_retries == 3
    assert cfg.pipeline.auto_approve is False


@mock.patch("onep.config._config_path")
@mock.patch("onep.config._config_dir")
def test_load_config_creates_default(mock_dir, mock_path):
    tmp = Path(tempfile.mkdtemp())
    mock_dir.return_value = tmp
    mock_path.return_value = tmp / "config.yaml"

    config = load_config()
    assert config.llm.default_model == "deepseek/deepseek-chat"
    assert (tmp / "config.yaml").exists()


@mock.patch("onep.config._config_path")
@mock.patch("onep.config._config_dir")
def test_load_config_reads_existing(mock_dir, mock_path):
    tmp = Path(tempfile.mkdtemp())
    mock_dir.return_value = tmp
    cfg_file = tmp / "config.yaml"
    cfg_file.write_text(yaml.dump({
        "llm": {"default_model": "openai/gpt-4o"},
        "pipeline": {"max_retries": 5},
    }))
    mock_path.return_value = cfg_file

    config = load_config()
    assert config.llm.default_model == "openai/gpt-4o"
    assert config.pipeline.max_retries == 5


@mock.patch("onep.config._config_path")
@mock.patch("onep.config._config_dir")
def test_save_config_persists(mock_dir, mock_path):
    tmp = Path(tempfile.mkdtemp())
    mock_dir.return_value = tmp
    cfg_file = tmp / "config.yaml"
    mock_path.return_value = cfg_file

    config = Config()
    config.pipeline.max_retries = 10
    save_config(config)

    reloaded = yaml.safe_load(cfg_file.read_text())
    assert reloaded["pipeline"]["max_retries"] == 10
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_config.py -v`
Expected: 5 tests pass

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml onep/__init__.py onep/config.py tests/__init__.py tests/test_config.py
git commit -m "feat: project scaffolding with config system"
```

---

### Task 2: Persistence layer — data models

**Files:**
- Create: `onep/persistence/__init__.py`
- Create: `onep/persistence/models.py`
- Create: `tests/test_persistence/__init__.py`
- Create: `tests/test_persistence/test_models.py`

- [ ] **Step 1: Create onep/persistence/__init__.py**

```python
"""Persistence layer - SQLite database, state files, and data models."""
```

- [ ] **Step 2: Create onep/persistence/models.py**

```python
"""Dataclass models for projects, stages, and pipeline state."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ProjectMode(str, Enum):
    GREENFIELD = "greenfield"
    BROWNFIELD = "brownfield"


class ProjectStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageRun:
    """Record of a single pipeline stage execution."""
    project_id: str
    stage_name: str
    agent_name: str
    status: StageStatus = StageStatus.PENDING
    model_used: str = ""
    token_count: int = 0
    output_files: list[str] = field(default_factory=list)
    error_message: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = ""
    finished_at: str = ""

    def start(self) -> None:
        self.status = StageStatus.IN_PROGRESS
        self.started_at = datetime.now(timezone.utc).isoformat()

    def complete(self, output_files: list[str], token_count: int = 0) -> None:
        self.status = StageStatus.COMPLETED
        self.output_files = output_files
        self.token_count = token_count
        self.finished_at = datetime.now(timezone.utc).isoformat()

    def fail(self, error: str) -> None:
        self.status = StageStatus.FAILED
        self.error_message = error
        self.finished_at = datetime.now(timezone.utc).isoformat()


@dataclass
class Approval:
    """Record of a user approval/rejection."""
    stage_run_id: str
    decision: str  # 'approved' | 'rejected'
    feedback: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Project:
    """A managed software project."""
    name: str
    mode: ProjectMode
    workspace_path: str
    status: ProjectStatus = ProjectStatus.RUNNING
    current_stage: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat()


@dataclass
class PipelineState:
    """Runtime pipeline state mirrored in state.yaml."""
    mode: str = "greenfield"
    current_stage: str = ""
    stages_completed: list[str] = field(default_factory=list)
    pending_approval: bool = False
    langgraph_checkpoint_id: str = ""
    retry_attempts: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
```

- [ ] **Step 3: Create tests/test_persistence/__init__.py**

```python
"""Tests for persistence layer."""
```

- [ ] **Step 4: Create tests/test_persistence/test_models.py**

```python
from onep.persistence.models import (
    Project,
    ProjectMode,
    ProjectStatus,
    StageRun,
    StageStatus,
    Approval,
    PipelineState,
)


def test_project_creation():
    p = Project(
        name="test-app",
        mode=ProjectMode.GREENFIELD,
        workspace_path="/tmp/test-app",
    )
    assert p.name == "test-app"
    assert p.mode == ProjectMode.GREENFIELD
    assert p.status == ProjectStatus.RUNNING
    assert len(p.id) == 32


def test_stage_run_lifecycle():
    sr = StageRun(
        project_id="proj-1",
        stage_name="pm",
        agent_name="Product Manager",
    )
    assert sr.status == StageStatus.PENDING

    sr.start()
    assert sr.status == StageStatus.IN_PROGRESS
    assert sr.started_at != ""

    sr.complete(output_files=["docs/PRD.md"], token_count=1500)
    assert sr.status == StageStatus.COMPLETED
    assert sr.output_files == ["docs/PRD.md"]
    assert sr.token_count == 1500
    assert sr.finished_at != ""


def test_stage_run_fail():
    sr = StageRun(project_id="p1", stage_name="test", agent_name="Tester")
    sr.fail("connection timeout")
    assert sr.status == StageStatus.FAILED
    assert sr.error_message == "connection timeout"


def test_approval_creation():
    a = Approval(stage_run_id="sr-1", decision="approved", feedback="LGTM")
    assert a.decision == "approved"
    assert a.feedback == "LGTM"


def test_pipeline_state_defaults():
    ps = PipelineState()
    assert ps.mode == "greenfield"
    assert ps.stages_completed == []
    assert ps.pending_approval is False
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_persistence/test_models.py -v`
Expected: 5 tests pass

- [ ] **Step 6: Commit**

```bash
git add onep/persistence/ tests/test_persistence/
git commit -m "feat: add persistence data models"
```

---

### Task 3: Persistence layer — database and state

**Files:**
- Create: `onep/persistence/database.py`
- Create: `onep/persistence/state.py`
- Create: `tests/test_persistence/test_database.py`
- Create: `tests/test_persistence/test_state.py`

- [ ] **Step 1: Create onep/persistence/database.py**

```python
"""SQLite database operations for project metadata."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from onep.config import _config_dir
from onep.persistence.models import (
    Project,
    ProjectMode,
    ProjectStatus,
    StageRun,
    StageStatus,
    Approval,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    current_stage TEXT NOT NULL DEFAULT '',
    workspace_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stage_runs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL,
    model_used TEXT NOT NULL DEFAULT '',
    token_count INTEGER NOT NULL DEFAULT 0,
    output_files TEXT NOT NULL DEFAULT '[]',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    stage_run_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    feedback TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (stage_run_id) REFERENCES stage_runs(id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
"""


def _db_path() -> Path:
    return _config_dir() / "meta.db"


def _connect() -> sqlite3.Connection:
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = _connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def insert_project(project: Project) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO projects (id, name, mode, status, current_stage, workspace_path, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project.id, project.name, project.mode.value, project.status.value,
         project.current_stage, project.workspace_path, project.created_at, project.updated_at),
    )
    conn.commit()
    conn.close()


def update_project(project: Project) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE projects SET status=?, current_stage=?, updated_at=? WHERE id=?",
        (project.status.value, project.current_stage, project.updated_at, project.id),
    )
    conn.commit()
    conn.close()


def get_project(project_id: str) -> Optional[Project]:
    conn = _connect()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return Project(
        id=row["id"], name=row["name"],
        mode=ProjectMode(row["mode"]), status=ProjectStatus(row["status"]),
        current_stage=row["current_stage"], workspace_path=row["workspace_path"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def list_projects() -> list[Project]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [
        Project(
            id=r["id"], name=r["name"], mode=ProjectMode(r["mode"]),
            status=ProjectStatus(r["status"]), current_stage=r["current_stage"],
            workspace_path=r["workspace_path"], created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]


def insert_stage_run(sr: StageRun) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO stage_runs (id, project_id, stage_name, agent_name, status, model_used, token_count, output_files, error_message, started_at, finished_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (sr.id, sr.project_id, sr.stage_name, sr.agent_name, sr.status.value,
         sr.model_used, sr.token_count, json.dumps(sr.output_files),
         sr.error_message, sr.started_at, sr.finished_at),
    )
    conn.commit()
    conn.close()


def update_stage_run(sr: StageRun) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE stage_runs SET status=?, token_count=?, output_files=?, error_message=?, finished_at=? WHERE id=?",
        (sr.status.value, sr.token_count, json.dumps(sr.output_files),
         sr.error_message, sr.finished_at, sr.id),
    )
    conn.commit()
    conn.close()


def insert_approval(approval: Approval) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO approvals (id, stage_run_id, decision, feedback, created_at) VALUES (?, ?, ?, ?, ?)",
        (approval.id, approval.stage_run_id, approval.decision, approval.feedback, approval.created_at),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 2: Create onep/persistence/state.py**

```python
"""Runtime pipeline state stored in project/.onep/state.yaml."""
from __future__ import annotations

from pathlib import Path
import yaml

from onep.persistence.models import PipelineState


def state_path(workspace: Path) -> Path:
    return workspace / ".onep" / "state.yaml"


def load_state(workspace: Path) -> PipelineState:
    sp = state_path(workspace)
    if not sp.exists():
        return PipelineState()
    raw = yaml.safe_load(sp.read_text()) or {}
    return PipelineState(
        mode=raw.get("mode", "greenfield"),
        current_stage=raw.get("current_stage", ""),
        stages_completed=raw.get("stages_completed", []),
        pending_approval=raw.get("pending_approval", False),
        langgraph_checkpoint_id=raw.get("langgraph_checkpoint_id", ""),
        retry_attempts=raw.get("retry_attempts", {}),
        artifacts=raw.get("artifacts", {}),
    )


def save_state(workspace: Path, state: PipelineState) -> None:
    sp = state_path(workspace)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(yaml.dump({
        "mode": state.mode,
        "current_stage": state.current_stage,
        "stages_completed": state.stages_completed,
        "pending_approval": state.pending_approval,
        "langgraph_checkpoint_id": state.langgraph_checkpoint_id,
        "retry_attempts": state.retry_attempts,
        "artifacts": state.artifacts,
    }, default_flow_style=False))
```

- [ ] **Step 3: Create tests/test_persistence/test_database.py**

```python
import tempfile
from pathlib import Path
from unittest import mock

from onep.config import _config_dir
from onep.persistence.database import init_db, insert_project, get_project, list_projects
from onep.persistence.models import Project, ProjectMode, ProjectStatus


@mock.patch("onep.persistence.database._config_dir")
def test_insert_and_get_project(mock_config_dir):
    tmp = Path(tempfile.mkdtemp())
    mock_config_dir.return_value = tmp
    init_db()

    p = Project(
        name="test-app",
        mode=ProjectMode.GREENFIELD,
        workspace_path="/tmp/ws",
    )
    insert_project(p)

    loaded = get_project(p.id)
    assert loaded is not None
    assert loaded.name == "test-app"
    assert loaded.mode == ProjectMode.GREENFIELD


@mock.patch("onep.persistence.database._config_dir")
def test_list_projects(mock_config_dir):
    tmp = Path(tempfile.mkdtemp())
    mock_config_dir.return_value = tmp
    init_db()

    insert_project(Project(name="a", mode=ProjectMode.GREENFIELD, workspace_path="/tmp/a"))
    insert_project(Project(name="b", mode=ProjectMode.BROWNFIELD, workspace_path="/tmp/b"))

    projects = list_projects()
    assert len(projects) == 2
```

- [ ] **Step 4: Create tests/test_persistence/test_state.py**

```python
import tempfile
from pathlib import Path

from onep.persistence.state import load_state, save_state
from onep.persistence.models import PipelineState


def test_save_and_load_state():
    workspace = Path(tempfile.mkdtemp())
    state = PipelineState(
        mode="greenfield",
        current_stage="architect",
        stages_completed=["pm", "designer"],
        artifacts={"prd": "docs/PRD.md"},
    )
    save_state(workspace, state)

    loaded = load_state(workspace)
    assert loaded.mode == "greenfield"
    assert loaded.current_stage == "architect"
    assert loaded.stages_completed == ["pm", "designer"]
    assert loaded.artifacts["prd"] == "docs/PRD.md"


def test_load_state_returns_default_for_missing():
    workspace = Path(tempfile.mkdtemp())
    state = load_state(workspace)
    assert state.mode == "greenfield"
    assert state.stages_completed == []
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_persistence/ -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add onep/persistence/database.py onep/persistence/state.py tests/test_persistence/test_database.py tests/test_persistence/test_state.py
git commit -m "feat: add SQLite database and state file persistence"
```

---

### Task 4: LLM adapter layer

**Files:**
- Create: `onep/llm/__init__.py`
- Create: `onep/llm/router.py`
- Create: `onep/llm/adapters.py`
- Create: `tests/test_llm/__init__.py`
- Create: `tests/test_llm/test_router.py`

- [ ] **Step 1: Create onep/llm/__init__.py**

```python
"""LLM adapter layer - model routing and provider adapters via LiteLLM."""
```

- [ ] **Step 2: Create onep/llm/router.py**

```python
"""Route tasks to the appropriate LLM model based on complexity."""
from __future__ import annotations

from enum import Enum

from onep.config import load_config, LLMConfig


class TaskComplexity(str, Enum):
    LIGHT = "light"
    STANDARD = "standard"
    COMPLEX = "complex"


# Which stages use complex reasoning
COMPLEX_STAGES = {"pm", "designer", "architect", "analyzer"}
STANDARD_STAGES = {"developer", "tester", "devops"}


def resolve_model(stage_name: str, task_complexity: TaskComplexity = TaskComplexity.STANDARD) -> tuple[str, str]:
    """
    Return (model_name, provider) for a given stage and complexity.

    Mapping:
      - PM, Designer, Architect, Analyzer stages → GPT 5.5 (complex)
      - Developer, Tester, DevOps → DeepSeek V4 (standard)
      - Explicit TaskComplexity.LIGHT can override to DeepSeek for any stage
    """
    config = load_config()
    llm = config.llm

    if task_complexity == TaskComplexity.COMPLEX or stage_name in COMPLEX_STAGES:
        return llm.complex_model, llm.complex_provider

    return llm.default_model, llm.default_provider


def get_api_key(provider: str) -> str:
    """Get API key for a given provider from config."""
    config = load_config()
    provider_cfg = config.llm.models.get(provider, {})
    return provider_cfg.get("api_key", "") or ""


def get_api_base(provider: str) -> str:
    """Get API base URL for a given provider from config."""
    config = load_config()
    provider_cfg = config.llm.models.get(provider, {})
    return provider_cfg.get("api_base", "") or ""
```

- [ ] **Step 3: Create onep/llm/adapters.py**

```python
"""LLM invocation via LiteLLM, abstracting provider differences."""
from __future__ import annotations

from litellm import completion

from onep.llm.router import resolve_model, get_api_key, get_api_base


class LLMAdapter:
    """Unified interface for calling LLMs through LiteLLM."""

    def invoke(self, system_prompt: str, user_prompt: str, stage_name: str) -> str:
        """
        Send a prompt to the appropriate model for this stage.

        Returns the model's text response.
        """
        model_name, provider = resolve_model(stage_name)
        api_key = get_api_key(provider)
        api_base = get_api_base(provider)

        kwargs = {"model": model_name, "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]}
        if api_key:
            kwargs["api_key"] = api_key
        if api_base:
            kwargs["api_base"] = api_base

        response = completion(**kwargs)
        return response.choices[0].message.content


# Singleton
_adapter: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LLMAdapter()
    return _adapter
```

- [ ] **Step 4: Create tests/test_llm/__init__.py**

```python
"""Tests for LLM layer."""
```

- [ ] **Step 5: Create tests/test_llm/test_router.py**

```python
from unittest import mock
import yaml

from onep.llm.router import resolve_model, get_api_key, get_api_base, TaskComplexity


SAMPLE_CONFIG = {
    "llm": {
        "default_model": "deepseek/deepseek-chat",
        "default_provider": "deepseek",
        "complex_model": "openai/gpt-5.5",
        "complex_provider": "openai",
        "models": {
            "deepseek": {"api_key": "sk-ds-test", "api_base": "https://api.deepseek.com/v1"},
            "openai": {"api_key": "sk-oai-test", "api_base": "https://api.openai.com/v1"},
        },
    },
    "project": {"root_dir": "~/.onep"},
    "pipeline": {"auto_approve": False, "max_retries": 3, "test_timeout": 300},
}


@mock.patch("onep.llm.router.load_config")
def test_complex_stage_gets_gpt(mock_load):
    from onep.config import Config, LLMConfig
    mock_load.return_value = Config(
        llm=LLMConfig(
            default_model="deepseek/deepseek-chat",
            complex_model="openai/gpt-5.5",
            complex_provider="openai",
            default_provider="deepseek",
        )
    )
    model, provider = resolve_model("architect")
    assert model == "openai/gpt-5.5"
    assert provider == "openai"


@mock.patch("onep.llm.router.load_config")
def test_standard_stage_gets_deepseek(mock_load):
    from onep.config import Config, LLMConfig
    mock_load.return_value = Config(
        llm=LLMConfig(
            default_model="deepseek/deepseek-chat",
            complex_model="openai/gpt-5.5",
            complex_provider="openai",
            default_provider="deepseek",
        )
    )
    model, provider = resolve_model("developer")
    assert model == "deepseek/deepseek-chat"
    assert provider == "deepseek"
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_llm/test_router.py -v`
Expected: 2 tests pass

- [ ] **Step 7: Commit**

```bash
git add onep/llm/ tests/test_llm/
git commit -m "feat: add LLM router and adapter layer"
```

---

### Task 5: Tool layer — base and filesystem

**Files:**
- Create: `onep/tools/__init__.py`
- Create: `onep/tools/base.py`
- Create: `onep/tools/filesystem.py`
- Create: `tests/test_tools/__init__.py`
- Create: `tests/test_tools/test_filesystem.py`

- [ ] **Step 1: Create onep/tools/__init__.py**

```python
"""Tool layer - safe wrappers around filesystem, Git, shell, and Docker operations."""
```

- [ ] **Step 2: Create onep/tools/base.py**

```python
"""Abstract base class for all tools."""
from __future__ import annotations

from abc import ABC
from typing import Any


class BaseTool(ABC):
    """All tools inherit from this. Provides a common interface."""

    name: str = ""
    description: str = ""

    def run(self, **kwargs: Any) -> str:
        raise NotImplementedError
```

- [ ] **Step 3: Create onep/tools/filesystem.py**

```python
"""Safe filesystem operations scoped to the workspace directory."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from onep.tools.base import BaseTool


class FileSystemTool(BaseTool):
    name = "filesystem"
    description = "Read and write files within the workspace."

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def _validate_path(self, path: str | Path) -> Path:
        """Ensure the path is within the workspace."""
        full = (self.workspace / path).resolve()
        if not str(full).startswith(str(self.workspace)):
            raise ValueError(f"Path {path} is outside workspace")
        return full

    def read(self, path: str) -> str:
        full = self._validate_path(path)
        if not full.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return full.read_text()

    def write(self, path: str, content: str) -> str:
        full = self._validate_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        return str(full.relative_to(self.workspace))

    def mkdir(self, path: str) -> str:
        full = self._validate_path(path)
        full.mkdir(parents=True, exist_ok=True)
        return str(full.relative_to(self.workspace))

    def exists(self, path: str) -> bool:
        full = self._validate_path(path)
        return full.exists()

    def list_dir(self, path: str = ".") -> list[str]:
        full = self._validate_path(path)
        return [str(p.relative_to(self.workspace)) for p in full.iterdir()]

    def run(self, **kwargs):
        operation = kwargs.get("operation", "read")
        if operation == "read":
            return self.read(kwargs["path"])
        elif operation == "write":
            return self.write(kwargs["path"], kwargs["content"])
        elif operation == "mkdir":
            return self.mkdir(kwargs["path"])
        elif operation == "exists":
            return str(self.exists(kwargs["path"]))
        elif operation == "list":
            return "\n".join(self.list_dir(kwargs.get("path", ".")))
        raise ValueError(f"Unknown operation: {operation}")
```

- [ ] **Step 4: Create tests/test_tools/__init__.py**

```python
"""Tests for tool layer."""
```

- [ ] **Step 5: Create tests/test_tools/test_filesystem.py**

```python
import tempfile
from pathlib import Path

import pytest

from onep.tools.filesystem import FileSystemTool


@pytest.fixture
def fs_tool():
    tmp = Path(tempfile.mkdtemp())
    return FileSystemTool(workspace=tmp)


def test_write_and_read(fs_tool):
    fs_tool.write("test.txt", "hello world")
    content = fs_tool.read("test.txt")
    assert content == "hello world"


def test_path_traversal_blocked(fs_tool):
    with pytest.raises(ValueError):
        fs_tool.write("../outside.txt", "escape")


def test_mkdir(fs_tool):
    fs_tool.mkdir("src/components")
    assert fs_tool.exists("src/components")


def test_list_dir(fs_tool):
    fs_tool.write("a.txt", "a")
    fs_tool.write("b.txt", "b")
    files = fs_tool.list_dir(".")
    assert "a.txt" in files
    assert "b.txt" in files
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_tools/test_filesystem.py -v`
Expected: 4 tests pass

- [ ] **Step 7: Commit**

```bash
git add onep/tools/__init__.py onep/tools/base.py onep/tools/filesystem.py tests/test_tools/
git commit -m "feat: add tool layer with filesystem operations"
```

---

### Task 6: Tool layer — Git, Shell, Docker, Lint

**Files:**
- Create: `onep/tools/git.py`
- Create: `onep/tools/shell.py`
- Create: `onep/tools/docker.py`
- Create: `onep/tools/lint.py`
- Create: `tests/test_tools/test_git.py`
- Create: `tests/test_tools/test_shell.py`

- [ ] **Step 1: Create onep/tools/git.py**

```python
"""Git operations via GitPython."""
from __future__ import annotations

from pathlib import Path
import git

from onep.tools.base import BaseTool


class GitTool(BaseTool):
    name = "git"
    description = "Git operations scoped to a workspace."

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def _repo(self) -> git.Repo:
        return git.Repo(str(self.workspace))

    def init(self) -> str:
        repo = git.Repo.init(str(self.workspace))
        return str(repo.working_dir)

    def add(self, paths: list[str]) -> str:
        repo = self._repo()
        repo.index.add(paths)
        return f"Staged: {paths}"

    def commit(self, message: str) -> str:
        repo = self._repo()
        commit = repo.index.commit(message)
        return f"Commit: {commit.hexsha[:8]} - {message}"

    def status(self) -> str:
        repo = self._repo()
        return repo.git.status()

    def log(self, max_count: int = 10) -> str:
        repo = self._repo()
        commits = list(repo.iter_commits(max_count=max_count))
        return "\n".join(f"{c.hexsha[:8]} {c.message.split(chr(10))[0]}" for c in commits)

    def run(self, **kwargs):
        operation = kwargs.get("operation", "status")
        if operation == "init":
            return self.init()
        elif operation == "add":
            return self.add(kwargs.get("paths", ["."]))
        elif operation == "commit":
            return self.commit(kwargs["message"])
        elif operation == "status":
            return self.status()
        elif operation == "log":
            return self.log()
        raise ValueError(f"Unknown operation: {operation}")
```

- [ ] **Step 2: Create onep/tools/shell.py**

```python
"""Safe shell command execution with timeout."""
from __future__ import annotations

import subprocess
import os

from onep.tools.base import BaseTool


class ShellTool(BaseTool):
    name = "shell"
    description = "Execute shell commands within the workspace."

    def __init__(self, workspace: str, timeout: int = 300):
        self.workspace = workspace
        self.timeout = timeout

    def run(self, **kwargs):
        command = kwargs["command"]
        timeout = kwargs.get("timeout", self.timeout)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workspace,
                env={**os.environ},
            )
            output = result.stdout
            if result.stderr:
                output += "\n[stderr]\n" + result.stderr
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s: {command}"
```

- [ ] **Step 3: Create onep/tools/docker.py**

```python
"""Docker Compose operations."""
from __future__ import annotations

import subprocess
from pathlib import Path

from onep.tools.base import BaseTool


class DockerTool(BaseTool):
    name = "docker"
    description = "Docker and Docker Compose operations."

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def compose_up(self) -> str:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "--build"],
            capture_output=True, text=True, cwd=str(self.workspace), timeout=120,
        )
        return result.stdout + result.stderr

    def compose_down(self) -> str:
        result = subprocess.run(
            ["docker", "compose", "down"],
            capture_output=True, text=True, cwd=str(self.workspace), timeout=60,
        )
        return result.stdout + result.stderr

    def compose_ps(self) -> str:
        result = subprocess.run(
            ["docker", "compose", "ps"],
            capture_output=True, text=True, cwd=str(self.workspace), timeout=30,
        )
        return result.stdout

    def health_check(self, url: str, retries: int = 10) -> str:
        import time
        import urllib.request
        import urllib.error

        for i in range(retries):
            try:
                urllib.request.urlopen(url, timeout=5)
                return f"Healthy: {url} (attempt {i + 1})"
            except urllib.error.URLError:
                time.sleep(2)
        return f"Unhealthy: {url} after {retries} attempts"

    def run(self, **kwargs):
        operation = kwargs.get("operation", "up")
        if operation == "up":
            return self.compose_up()
        elif operation == "down":
            return self.compose_down()
        elif operation == "ps":
            return self.compose_ps()
        elif operation == "health":
            return self.health_check(kwargs["url"])
        raise ValueError(f"Unknown operation: {operation}")
```

- [ ] **Step 4: Create onep/tools/lint.py**

```python
"""Basic code quality checks."""
from __future__ import annotations

import subprocess
from pathlib import Path

from onep.tools.base import BaseTool


class LintTool(BaseTool):
    name = "lint"
    description = "Run linting and basic code quality checks."

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def check_python(self, path: str = ".") -> str:
        """Run ruff or flake8 on Python files."""
        try:
            result = subprocess.run(
                ["ruff", "check", path, "--output-format=text"],
                capture_output=True, text=True, cwd=str(self.workspace), timeout=60,
            )
            if result.returncode == 0:
                return "No issues found.\n" + result.stdout
            return result.stdout + "\n" + result.stderr
        except FileNotFoundError:
            return "Lint skipped: ruff not installed."

    def run(self, **kwargs):
        language = kwargs.get("language", "python")
        path = kwargs.get("path", ".")
        if language == "python":
            return self.check_python(path)
        return f"Lint not supported for: {language}"
```

- [ ] **Step 5: Create tests/test_tools/test_git.py**

```python
import tempfile
from pathlib import Path

from onep.tools.git import GitTool


def test_git_init_and_status():
    tmp = Path(tempfile.mkdtemp())
    tool = GitTool(workspace=tmp)
    result = tool.init()
    assert "git" in result.lower() or tmp.name in result

    status = tool.status()
    assert "No commits yet" in status or "On branch" in status


def test_git_add_and_commit():
    tmp = Path(tempfile.mkdtemp())
    tool = GitTool(workspace=tmp)
    tool.init()

    (tmp / "test.txt").write_text("hello")
    tool.add(["test.txt"])
    result = tool.commit("initial commit")
    assert "initial commit" in result

    log = tool.log(max_count=1)
    assert "initial commit" in log
```

- [ ] **Step 6: Create tests/test_tools/test_shell.py**

```python
import tempfile
from pathlib import Path

from onep.tools.shell import ShellTool


def test_shell_echo():
    tmp = Path(tempfile.mkdtemp())
    tool = ShellTool(workspace=str(tmp))
    result = tool.run(command="echo hello")
    assert "hello" in result


def test_shell_directory_scoped():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "subdir").mkdir()
    tool = ShellTool(workspace=str(tmp))
    result = tool.run(command="pwd")
    assert str(tmp) in result
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_tools/ -v`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add onep/tools/git.py onep/tools/shell.py onep/tools/docker.py onep/tools/lint.py tests/test_tools/test_git.py tests/test_tools/test_shell.py
git commit -m "feat: add Git, shell, Docker, and lint tools"
```

---

### Task 7: Agent registry and base definitions

**Files:**
- Create: `onep/agents/__init__.py`
- Create: `onep/agents/registry.py`
- Create: `tests/test_agents/__init__.py`
- Create: `tests/test_agents/test_registry.py`

- [ ] **Step 1: Create onep/agents/__init__.py**

```python
"""Agent definitions - each agent is a CrewAI Agent with role, goal, backstory, and tools."""
```

- [ ] **Step 2: Create onep/agents/registry.py**

```python
"""Agent registry maps agent names to CrewAI Agent factories."""
from __future__ import annotations

from typing import Callable

from crewai import Agent

AgentFactory = Callable[[], Agent]

_registry: dict[str, AgentFactory] = {}


def register(name: str) -> Callable[[AgentFactory], AgentFactory]:
    """Decorator to register an agent factory."""
    def decorator(fn: AgentFactory) -> AgentFactory:
        _registry[name] = fn
        return fn
    return decorator


def get_agent(name: str) -> Agent:
    """Get a CrewAI Agent instance by name."""
    factory = _registry.get(name)
    if factory is None:
        raise KeyError(f"Agent '{name}' not registered. Available: {list(_registry.keys())}")
    return factory()


def list_agents() -> list[str]:
    """Return names of all registered agents."""
    return list(_registry.keys())


def clear_registry() -> None:
    """Clear the registry (for testing)."""
    _registry.clear()
```

- [ ] **Step 3: Create tests/test_agents/__init__.py**

```python
"""Tests for agent layer."""
```

- [ ] **Step 4: Create tests/test_agents/test_registry.py**

```python
import pytest
from crewai import Agent

from onep.agents.registry import register, get_agent, list_agents, clear_registry


def test_register_and_get_agent():
    clear_registry()

    @register("test_agent")
    def make_test_agent():
        return Agent(
            role="Test Role",
            goal="Test Goal",
            backstory="Test backstory",
        )

    agent = get_agent("test_agent")
    assert agent.role == "Test Role"
    assert agent.goal == "Test Goal"
    assert "test_agent" in list_agents()


def test_get_unregistered_raises():
    clear_registry()
    with pytest.raises(KeyError, match="unknown_agent"):
        get_agent("unknown_agent")


def test_list_agents():
    clear_registry()

    @register("a")
    def make_a():
        return Agent(role="A", goal="A", backstory="A")

    @register("b")
    def make_b():
        return Agent(role="B", goal="B", backstory="B")

    agents = list_agents()
    assert "a" in agents
    assert "b" in agents
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_agents/test_registry.py -v`
Expected: 3 tests pass

- [ ] **Step 6: Commit**

```bash
git add onep/agents/__init__.py onep/agents/registry.py tests/test_agents/
git commit -m "feat: add agent registry"
```

---

### Task 8: PM and Designer agents

**Files:**
- Create: `onep/agents/pm.py`
- Create: `onep/agents/designer.py`

The remaining agents follow the same pattern. Since the MVP focuses on Greenfield, we need PM, Designer, Architect, Developer, Tester, and DevOps. The Analyzer (Brownfield) can be deferred.

- [ ] **Step 1: Create onep/agents/pm.py**

```python
"""Product Manager Agent - analyzes requirements and produces PRD."""
from crewai import Agent

from onep.agents.registry import register


@register("pm")
def create_pm() -> Agent:
    return Agent(
        role="产品经理",
        goal="将用户需求转化为结构化产品需求文档 (PRD)，包含用户故事、功能规格和验收标准",
        backstory=(
            "你是一位经验丰富的产品经理，专注于将模糊的用户需求转化为清晰可执行的产品规格。"
            "你擅长用户故事分解、功能边界定义和验收标准编写。"
            "你始终用中文撰写文档，确保内容结构化、可量化、无歧义。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
```

- [ ] **Step 2: Create onep/agents/designer.py**

```python
"""UI/UX Designer Agent - designs pages, interactions, and components."""
from crewai import Agent

from onep.agents.registry import register


@register("designer")
def create_designer() -> Agent:
    return Agent(
        role="UI/UX 设计师",
        goal="基于产品需求设计页面布局、交互流程、组件选型和视觉规范",
        backstory=(
            "你是一位资深 UI/UX 设计师，擅长将 PRD 转化为具体的界面设计方案。"
            "你关注用户体验、视觉层次、交互逻辑和组件复用。"
            "你为 Web 和移动端设计，遵循现代设计系统规范（间距、颜色、排版）。"
            "你使用中文撰写设计文档。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
```

- [ ] **Step 3: Commit**

```bash
git add onep/agents/pm.py onep/agents/designer.py
git commit -m "feat: add PM and UI/UX Designer agents"
```

---

### Task 9: Architect, Developer, Tester, DevOps agents

**Files:**
- Create: `onep/agents/architect.py`
- Create: `onep/agents/developer.py`
- Create: `onep/agents/tester.py`
- Create: `onep/agents/devops.py`

- [ ] **Step 1: Create onep/agents/architect.py**

```python
"""Architect Agent - designs system architecture, data models, and API contracts."""
from crewai import Agent

from onep.agents.registry import register


@register("architect")
def create_architect() -> Agent:
    return Agent(
        role="架构师",
        goal="基于 PRD 和 UI 设计稿，设计系统架构、数据模型、API 契约和技术选型",
        backstory=(
            "你是一位经验丰富的系统架构师，专注于全栈应用架构设计。"
            "你精通 Python 后端（FastAPI）、React 前端和 React Native 移动端架构。"
            "你设计 RESTful API、数据库 Schema (SQL/NoSQL)、组件树和中间件策略。"
            "你输出结构化的 ARCHITECTURE.md、Mermaid 架构图和 API 文档。"
            "你始终考虑可扩展性、安全性和性能。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
```

- [ ] **Step 2: Create onep/agents/developer.py**

```python
"""Developer Agent - implements code based on architecture design."""
from crewai import Agent

from onep.agents.registry import register


@register("developer")
def create_developer() -> Agent:
    return Agent(
        role="研发工程师",
        goal="按照架构设计实现完整可运行的代码，包括后端 API、前端页面和 Docker 配置",
        backstory=(
            "你是一位全栈研发工程师，熟练掌握 Python (FastAPI/SQLAlchemy)、"
            "TypeScript (React/Vite) 和 React Native。你编写清晰、可维护的代码，"
            "遵循最佳实践：类型标注、错误处理、RESTful 设计、组件化开发。"
            "代码标识符和注释使用英文。你同时编写 Dockerfile 和 docker-compose.yml "
            "以确保应用可容器化运行。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=10,
    )
```

- [ ] **Step 3: Create onep/agents/tester.py**

```python
"""Tester Agent - writes and runs tests, validates functionality."""
from crewai import Agent

from onep.agents.registry import register


@register("tester")
def create_tester() -> Agent:
    return Agent(
        role="测试工程师",
        goal="编写并运行测试用例，验证功能正确性和代码质量",
        backstory=(
            "你是一位测试工程师，负责确保软件质量。你为后端编写 pytest 测试，"
            "为前端编写 vitest + React Testing Library 测试。"
            "你关注功能正确性、边界条件、API 契约和集成场景。"
            "MVP 阶段聚焦基础冒烟测试和关键路径验证。"
            "你每次运行测试后输出 TEST_REPORT.md。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
```

- [ ] **Step 4: Create onep/agents/devops.py**

```python
"""DevOps Agent - containerizes and deploys the application."""
from crewai import Agent

from onep.agents.registry import register


@register("devops")
def create_devops() -> Agent:
    return Agent(
        role="DevOps 工程师",
        goal="将应用容器化部署到 Docker，验证运行状态，输出访问地址",
        backstory=(
            "你是一位 DevOps 工程师，负责将开发完成的代码部署为可运行的服务。"
            "你使用 Docker 和 Docker Compose 进行容器编排。"
            "你检查端口占用、环境变量配置、服务健康状态。"
            "部署完成后输出 DEPLOY_LOG.md 和访问地址。"
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=5,
    )
```

- [ ] **Step 5: Commit**

```bash
git add onep/agents/architect.py onep/agents/developer.py onep/agents/tester.py onep/agents/devops.py
git commit -m "feat: add Architect, Developer, Tester, and DevOps agents"
```

---

### Task 10: LangGraph subflows — code review and test retry

**Files:**
- Create: `onep/subflows/__init__.py`
- Create: `onep/subflows/code_review.py`
- Create: `onep/subflows/test_retry.py`
- Create: `tests/test_subflows/__init__.py`
- Create: `tests/test_subflows/test_code_review.py`
- Create: `tests/test_subflows/test_test_retry.py`

- [ ] **Step 1: Create onep/subflows/__init__.py**

```python
"""LangGraph sub-flows for complex branching logic."""
```

- [ ] **Step 2: Create onep/subflows/code_review.py**

```python
"""
Code review loop using LangGraph.

Flow: generate code -> self-review -> lint check -> fix issues or pass.
Runs up to 3 iterations before requiring human intervention.
"""
from __future__ import annotations

from typing import TypedDict, Literal
from pathlib import Path

from langgraph.graph import StateGraph, END


class CodeReviewState(TypedDict):
    workspace: str
    code_files: list[str]
    review_notes: str
    lint_output: str
    iteration: int
    passed: bool
    status: str  # 'reviewing', 'fixing', 'passed', 'failed'


def lint_code(state: CodeReviewState) -> CodeReviewState:
    from onep.tools.lint import LintTool
    ws = Path(state["workspace"])
    tool = LintTool(workspace=ws)
    output = tool.check_python()
    state["lint_output"] = output
    state["passed"] = "No issues found" in output
    return state


def decide_next(state: CodeReviewState) -> Literal["fix_issues", "done"]:
    if state["passed"]:
        state["status"] = "passed"
        return "done"
    if state["iteration"] >= 3:
        state["status"] = "failed"
        return "done"
    state["iteration"] += 1
    state["status"] = "fixing"
    return "fix_issues"


def fix_issues(state: CodeReviewState) -> CodeReviewState:
    state["status"] = "reviewing"
    return state


def build_code_review_graph() -> StateGraph:
    builder = StateGraph(CodeReviewState)
    builder.add_node("lint", lint_code)
    builder.add_node("fix", fix_issues)
    builder.set_entry_point("lint")
    builder.add_conditional_edges("lint", decide_next, {"fix_issues": "fix", "done": END})
    builder.add_edge("fix", "lint")
    return builder.compile()


def run_code_review(workspace: Path) -> CodeReviewState:
    graph = build_code_review_graph()
    initial_state: CodeReviewState = {
        "workspace": str(workspace),
        "code_files": [],
        "review_notes": "",
        "lint_output": "",
        "iteration": 0,
        "passed": False,
        "status": "reviewing",
    }
    return graph.invoke(initial_state)
```

- [ ] **Step 3: Create onep/subflows/test_retry.py**

```python
"""
Test failure retry loop using LangGraph.

Flow: run tests -> check results -> fix or escalate -> retry (max 3 rounds).
"""
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
    status: str  # 'running', 'analyzing', 'fixing', 'passed', 'escalated'


def run_tests(state: TestRetryState) -> TestRetryState:
    import subprocess
    result = subprocess.run(
        state["test_command"], shell=True,
        capture_output=True, text=True, cwd=state["workspace"], timeout=300,
    )
    state["test_output"] = result.stdout + "\n" + result.stderr
    state["passed"] = result.returncode == 0
    state["status"] = "analyzing"
    return state


def decide_after_test(state: TestRetryState) -> Literal["done", "fix", "escalate"]:
    if state["passed"]:
        state["status"] = "passed"
        return "done"
    if state["iteration"] >= state["max_retries"]:
        state["status"] = "escalated"
        return "escalate"
    state["iteration"] += 1
    state["status"] = "fixing"
    return "fix"


def prepare_fix(state: TestRetryState) -> TestRetryState:
    state["status"] = "running"
    return state


def build_test_retry_graph() -> StateGraph:
    builder = StateGraph(TestRetryState)
    builder.add_node("run", run_tests)
    builder.add_node("fix", prepare_fix)
    builder.set_entry_point("run")
    builder.add_conditional_edges(
        "run", decide_after_test,
        {"done": END, "fix": "fix", "escalate": END},
    )
    builder.add_edge("fix", "run")
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
```

- [ ] **Step 4: Create tests/test_subflows/__init__.py**

```python
"""Tests for LangGraph subflows."""
```

- [ ] **Step 5: Create tests/test_subflows/test_code_review.py**

```python
import tempfile
from pathlib import Path

from onep.subflows.code_review import build_code_review_graph, run_code_review


def test_code_review_graph_passes_on_clean_code():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "main.py").write_text("def hello():\n    return 'world'\n")

    result = run_code_review(tmp)
    # Should complete (passed or failed, not hang)
    assert result["status"] in ("passed", "failed")


def test_graph_compiles():
    graph = build_code_review_graph()
    assert graph is not None
```

- [ ] **Step 6: Create tests/test_subflows/test_test_retry.py**

```python
import tempfile
from pathlib import Path

from onep.subflows.test_retry import build_test_retry_graph, run_test_loop


def test_test_loop_passes_on_successful_command():
    tmp = Path(tempfile.mkdtemp())
    result = run_test_loop(tmp, test_command="echo all good && exit 0")
    assert result["passed"] is True
    assert result["status"] == "passed"


def test_test_loop_escalates_after_max_retries():
    tmp = Path(tempfile.mkdtemp())
    result = run_test_loop(
        tmp, test_command="echo fail && exit 1", max_retries=2,
    )
    assert result["passed"] is False
    assert result["status"] == "escalated"


def test_graph_compiles():
    graph = build_test_retry_graph()
    assert graph is not None
```

- [ ] **Step 7: Run tests**

Run: `python -m pytest tests/test_subflows/ -v`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add onep/subflows/ tests/test_subflows/
git commit -m "feat: add LangGraph code review and test retry subflows"
```

---

### Task 11: CrewAI orchestrator — Greenfield pipeline

**Files:**
- Create: `onep/orchestrator/__init__.py`
- Create: `onep/orchestrator/crew.py`
- Create: `onep/orchestrator/greenfield.py`
- Create: `tests/test_orchestrator/__init__.py`
- Create: `tests/test_orchestrator/test_greenfield.py`

- [ ] **Step 1: Create onep/orchestrator/__init__.py**

```python
"""CrewAI orchestration layer — pipeline definitions and crew factory."""
```

- [ ] **Step 2: Create onep/orchestrator/crew.py**

```python
"""Crew factory that builds a CrewAI Crew from pipeline definitions."""
from __future__ import annotations

from pathlib import Path

from crewai import Crew, Process, Task

from onep.agents.registry import get_agent
from onep.persistence.models import Project, PipelineState


def create_crew(project: Project, state: PipelineState) -> Crew:
    """Build a Crew based on project mode."""
    if project.mode.value == "greenfield":
        from onep.orchestrator.greenfield import build_greenfield_tasks
        tasks = build_greenfield_tasks(project, state)
    else:
        raise ValueError(f"Unsupported pipeline mode: {project.mode}")

    agents = [get_agent(t.agent_name) for t in tasks if hasattr(t, 'agent_name')]

    return Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )
```

- [ ] **Step 3: Create onep/orchestrator/greenfield.py**

```python
"""Greenfield pipeline: PM → Designer → Architect → Developer → Tester → DevOps."""
from __future__ import annotations

from pathlib import Path

from crewai import Task

from onep.agents.registry import get_agent
from onep.persistence.models import Project, PipelineState


GREENFIELD_STAGES = [
    {"name": "pm", "agent": "pm", "description": "分析需求并生成 PRD"},
    {"name": "designer", "agent": "designer", "description": "设计 UI/UX 并生成设计文档"},
    {"name": "architect", "agent": "architect", "description": "设计系统架构、数据模型和 API"},
    {"name": "developer", "agent": "developer", "description": "实现后端、前端代码和 Docker 配置"},
    {"name": "tester", "agent": "tester", "description": "编写并运行测试"},
    {"name": "devops", "agent": "devops", "description": "Docker 部署和健康检查"},
]

STAGE_PROMPTS = {
    "pm": """\
你是一位产品经理。请根据以下用户需求，输出一份结构化的产品需求文档 (PRD)。

用户需求：{requirement}

请按以下结构输出 PRD 并保存为 docs/PRD.md：
1. 产品概述
2. 目标用户
3. 用户故事（至少3个）
4. 功能规格（核心功能列表，标注优先级 P0/P1/P2）
5. 验收标准（每个功能的可测量标准）
6. 非功能需求（性能、安全、兼容性）

使用中文撰写。""",

    "designer": """\
你是一位 UI/UX 设计师。请基于以下 PRD 设计用户界面和交互流程。

PRD 文档：docs/PRD.md 的内容如下：
{prd_content}

请输出设计文档并保存为 docs/DESIGN.md，包含：
1. 信息架构（页面层级关系图，用文本描述）
2. 页面清单和每个页面的布局说明
3. 核心交互流程（关键用户路径）
4. 组件清单（可复用组件列表及用途）
5. 视觉规范（颜色方案、排版层级、间距系统）

为 Web (React) 和 Mobile (React Native) 分别设计适配方案。
使用中文撰写。""",

    "architect": """\
你是一位系统架构师。请基于 PRD 和 UI 设计设计技术架构。

PRD: docs/PRD.md
UI 设计: docs/DESIGN.md

项目工作区: {workspace}

请输出架构文档 docs/ARCHITECTURE.md，并创建实际的项目代码结构：
1. 系统架构总览（文本描述各层职责）
2. 技术栈确认（FastAPI + SQLAlchemy + React + Vite）
3. 数据库 Schema 设计（建表 SQL 或 SQLAlchemy 模型定义）
4. REST API 设计（端点列表、请求/响应格式）
5. React 组件树（页面→组件层级关系）
6. 项目目录结构

使用中文撰写文档，代码标识符使用英文。""",

    "developer": """\
你是一位全栈研发工程师。请根据架构设计实现完整的应用代码。

工作区: {workspace}
架构设计: docs/ARCHITECTURE.md

请完成以下工作：
1. 创建后端项目结构 (backend/)，实现 FastAPI 应用
2. 创建前端项目结构 (frontend/)，实现 React + Vite 应用
3. 编写 Dockerfile 和 docker-compose.yml
4. 确保应用可以本地运行

代码标识符和注释使用英文。使用 git 管理版本，每完成一个模块后提交。
后端使用 FastAPI + SQLAlchemy + Pydantic。
前端使用 React + TypeScript + Vite + TailwindCSS。""",

    "tester": """\
你是一位测试工程师。请为项目编写并运行测试。

工作区: {workspace}

请完成以下工作：
1. 为后端 API 编写 pytest 测试 (backend/tests/)
2. 为前端组件编写 vitest 测试 (frontend/src/__tests__/)
3. 运行测试并收集结果
4. 输出 TEST_REPORT.md（测试概览、通过/失败列表、覆盖率）

MVP 阶段聚焦基础冒烟测试和关键 API 端点验证。""",

    "devops": """\
你是一位 DevOps 工程师。请部署应用。

工作区: {workspace}

请完成以下工作：
1. 检查 docker-compose.yml 配置是否正确
2. 运行 docker compose up -d --build
3. 等待服务启动并进行健康检查
4. 输出 DEPLOY_LOG.md 和访问地址

确认以下服务正常运行：
- 后端 API (默认 http://localhost:8000)
- 前端应用 (默认 http://localhost:5173)
- 数据库 (如果使用)""",
}


def build_greenfield_tasks(project: Project, state: PipelineState) -> list[Task]:
    """Build CrewAI Task list for the Greenfield pipeline."""
    workspace = Path(project.workspace_path)
    requirement = getattr(project, 'requirement', '')

    prd_path = workspace / "docs" / "PRD.md"
    prd_content = prd_path.read_text() if prd_path.exists() else ""

    tasks = []
    for i, stage in enumerate(GREENFIELD_STAGES):
        prompt = STAGE_PROMPTS[stage["name"]].format(
            requirement=requirement,
            prd_content=prd_content,
            workspace=str(workspace),
        )

        task = Task(
            description=prompt,
            expected_output=f"Stage {stage['name']} completed. Output saved to workspace.",
            agent=get_agent(stage["agent"]),
        )
        tasks.append(task)

    return tasks


def get_greenfield_stages() -> list[dict]:
    """Return the list of Greenfield stages (for status display)."""
    return GREENFIELD_STAGES
```

- [ ] **Step 4: Create tests/test_orchestrator/__init__.py**

```python
"""Tests for orchestrator layer."""
```

- [ ] **Step 5: Create tests/test_orchestrator/test_greenfield.py**

```python
import tempfile
from pathlib import Path

from onep.orchestrator.greenfield import (
    GREENFIELD_STAGES,
    get_greenfield_stages,
    STAGE_PROMPTS,
)


def test_greenfield_has_six_stages():
    assert len(GREENFIELD_STAGES) == 6
    stage_names = [s["name"] for s in GREENFIELD_STAGES]
    assert stage_names == ["pm", "designer", "architect", "developer", "tester", "devops"]


def test_all_stages_have_prompts():
    for stage in GREENFIELD_STAGES:
        assert stage["name"] in STAGE_PROMPTS, f"Missing prompt for {stage['name']}"


def test_prompts_contain_workspace_placeholder():
    for name, prompt in STAGE_PROMPTS.items():
        if name == "pm":
            assert "{requirement}" in prompt
        else:
            assert "{workspace}" in prompt or "{prd_content}" in prompt
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_orchestrator/test_greenfield.py -v`
Expected: 3 tests pass

- [ ] **Step 7: Commit**

```bash
git add onep/orchestrator/ tests/test_orchestrator/
git commit -m "feat: add CrewAI orchestrator with Greenfield pipeline"
```

---

### Task 12: CLI — main entry and create command

**Files:**
- Create: `onep/cli/__init__.py`
- Create: `onep/cli/create.py`
- Create: `onep/main.py`
- Create: `tests/test_cli/__init__.py`
- Create: `tests/test_cli/test_create.py`

- [ ] **Step 1: Create onep/cli/__init__.py**

```python
"""CLI command modules. Each file exports a COMMANDS list, auto-discovered by main.py."""
from __future__ import annotations

from typing import TYPE_CHECKING
import importlib
import pkgutil

if TYPE_CHECKING:
    import click


def register_commands(cli: "click.Group") -> None:
    """Auto-discover all command modules and register their exported commands."""
    package = __package__  # "onep.cli"
    for _, module_name, _ in pkgutil.iter_modules([__path__[0]]):
        mod = importlib.import_module(f".{module_name}", package)
        if hasattr(mod, "COMMANDS"):
            for cmd in mod.COMMANDS:
                cli.add_command(cmd)
```

- [ ] **Step 2: Create onep/cli/create.py**

```python
"""onep create and onep run — create and execute projects."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from onep.config import load_config
from onep.persistence.database import init_db, insert_project, update_project
from onep.persistence.models import Project, ProjectMode, PipelineState
from onep.persistence.state import save_state, load_state
from onep.orchestrator.greenfield import GREENFIELD_STAGES
from onep.tools.git import GitTool

console = Console()


@click.command()
@click.argument("requirement", type=str)
@click.option("--name", "-n", default=None, help="Project name")
def create_cmd(requirement: str, name: str | None):
    """Create a new project from a natural language requirement.

    \b
    Example:
        onep create "做一个支持登录的记事本应用"
        onep create "build a todo app with user auth" --name todo-app
    """
    config = load_config()
    init_db()

    if name is None:
        import re
        clean = re.sub(r'[^\w一-鿿]', '', requirement)[:20]
        name = clean or f"project-{uuid.uuid4().hex[:6]}"

    project_root = Path(os.path.expanduser(config.project.root_dir))
    projects_dir = project_root / "projects" / name
    workspace = projects_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    git = GitTool(workspace=workspace)
    git.init()
    (workspace / "docs").mkdir(exist_ok=True)
    (workspace / "README.md").write_text(f"# {name}\n\n{requirement}\n")
    git.add(["README.md"])
    git.commit("chore: initial commit from onep create")

    project = Project(
        name=name,
        mode=ProjectMode.GREENFIELD,
        workspace_path=str(workspace),
    )
    project.requirement = requirement  # type: ignore[attr-defined]
    insert_project(project)

    state = PipelineState(mode="greenfield")
    save_state(workspace, state)

    console.print(Panel.fit(
        f"[bold green]Project '{name}' created![/bold green]\n"
        f"Workspace: {workspace}\n"
        f"Mode: Greenfield (6 stages)\n\n"
        f"Run [bold cyan]onep run {name}[/bold cyan] to start the pipeline.",
        title="OnePTeam",
    ))

    console.print("\n[bold]Pipeline stages:[/bold]")
    for i, stage in enumerate(GREENFIELD_STAGES, 1):
        console.print(f"  {i}. {stage['agent']} — {stage['description']}")


@click.command()
@click.argument("project_name", type=str)
@click.option("--stage", "-s", default=None, help="Stage to resume from")
def run_cmd(project_name: str, stage: str | None):
    """Run the pipeline for a project."""
    from onep.orchestrator.runner import run_pipeline
    success = run_pipeline(project_name, start_from=stage)
    if success:
        console.print("[bold green]Pipeline completed![/bold green]")
    else:
        console.print("[yellow]Pipeline paused or failed. Check: onep status[/yellow]")


COMMANDS = [create_cmd, run_cmd]
```

- [ ] **Step 3: Create onep/main.py**

```python
"""OnePTeam CLI entry point."""
from __future__ import annotations

import click

from onep.cli import register_commands


@click.group()
@click.version_option(version="0.1.0", prog_name="onep")
def cli():
    """OnePTeam — Multi-Agent Full-Stack Software Development Team.

    Build software from natural language requirements using AI agents.
    """
    pass


# Auto-discover and register CLI command modules
register_commands(cli)


if __name__ == "__main__":
    cli()
```

- [ ] **Step 4: Create tests/test_cli/__init__.py**

```python
"""Tests for CLI layer."""
```

- [ ] **Step 5: Create tests/test_cli/test_create.py**

```python
from click.testing import CliTester
import click
from click.testing import CliRunner

from onep.main import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "OnePTeam" in result.output


def test_create_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["create", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_cli/test_create.py -v`
Expected: 2 tests pass

- [ ] **Step 7: Commit**

```bash
git add onep/cli/__init__.py onep/cli/create.py onep/main.py tests/test_cli/
git commit -m "feat: add CLI entry point and create command"
```

---

### Task 13: CLI — status and show commands

**Files:**
- Create: `onep/cli/status.py`
- Create: `onep/cli/show.py`
- Create: `tests/test_cli/test_status.py`

- [ ] **Step 1: Create onep/cli/status.py**

```python
"""onep status, pause, resume, approve, reject — pipeline control commands."""
from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from onep.persistence.database import init_db, list_projects, update_project

console = Console()


@click.command()
def status_cmd():
    """Show pipeline progress for all projects."""
    init_db()
    projects = list_projects()

    if not projects:
        console.print("[yellow]No projects found. Create one with: onep create <requirement>[/yellow]")
        return

    for project in projects:
        state_symbol = {"running": "[cyan]▶[/cyan]", "paused": "[yellow]⏸[/yellow]",
                        "completed": "[green]✓[/green]", "failed": "[red]✗[/red]"}
        symbol = state_symbol.get(project.status.value, "?")

        console.print(Panel(
            f"{symbol} [bold]{project.name}[/bold] ({project.mode.value})\n"
            f"  Status: {project.status.value} | Stage: {project.current_stage or 'not started'}",
            title=f"Project {project.id[:8]}",
        ))


@click.command()
@click.argument("project_name", type=str)
def pause_cmd(project_name: str):
    """Pause a running pipeline."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return
    from onep.persistence.models import ProjectStatus
    project.status = ProjectStatus.PAUSED
    project.touch()
    update_project(project)
    console.print(f"[yellow]Project '{project_name}' paused.[/yellow]")


@click.command()
@click.argument("project_name", type=str)
def resume_cmd(project_name: str):
    """Resume a paused pipeline."""
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return
    from onep.persistence.models import ProjectStatus
    project.status = ProjectStatus.RUNNING
    project.touch()
    update_project(project)
    console.print(f"[green]Project '{project_name}' resumed.[/green]")


@click.command()
@click.argument("project_name", type=str)
def approve_cmd(project_name: str):
    """Approve the current approval gate."""
    console.print(f"[green]Stage approved for '{project_name}'.[/green]")


@click.command()
@click.argument("project_name", type=str)
@click.argument("reason", type=str, default="")
def reject_cmd(project_name: str, reason: str):
    """Reject the current stage with optional feedback."""
    console.print(f"[red]Stage rejected for '{project_name}'.[/red]")
    if reason:
        console.print(f"Feedback: {reason}")


COMMANDS = [status_cmd, pause_cmd, resume_cmd, approve_cmd, reject_cmd]
```

- [ ] **Step 2: Create onep/cli/show.py**

```python
"""onep show — display pipeline artifacts."""
from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown

from onep.persistence.database import init_db, list_projects

console = Console()


@click.group(invoke_without_command=True)
@click.pass_context
def show_group(ctx):
    """View project artifacts (prd, design, architecture, report, log)."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@show_group.command()
@click.argument("project_name", type=str)
def prd(project_name: str):
    """Show the PRD for a project."""
    _show_artifact(project_name, "docs/PRD.md", "PRD")


@show_group.command()
@click.argument("project_name", type=str)
def design(project_name: str):
    """Show the UI/UX design document."""
    _show_artifact(project_name, "docs/DESIGN.md", "Design")


@show_group.command()
@click.argument("project_name", type=str)
def architecture(project_name: str):
    """Show the architecture document."""
    _show_artifact(project_name, "docs/ARCHITECTURE.md", "Architecture")


@show_group.command()
@click.argument("project_name", type=str)
def report(project_name: str):
    """Show the test report."""
    _show_artifact(project_name, "docs/TEST_REPORT.md", "Test Report")


@show_group.command()
@click.argument("project_name", type=str)
def log(project_name: str):
    """Show the deployment log."""
    _show_artifact(project_name, "docs/DEPLOY_LOG.md", "Deploy Log")


def _show_artifact(project_name: str, file_path: str, label: str):
    init_db()
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return

    workspace = Path(project.workspace_path)
    target = workspace / file_path
    if not target.exists():
        console.print(f"[yellow]{label} not found: {file_path}[/yellow]")
        return

    console.print(Markdown(target.read_text()))


COMMANDS = [show_group]
```

- [ ] **Step 3: Create tests/test_cli/test_status.py**

```python
from click.testing import CliRunner

from onep.main import cli


def test_status_no_projects():
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0


def test_show_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["show", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_cli/ -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add onep/cli/status.py onep/cli/show.py tests/test_cli/test_status.py
git commit -m "feat: add status and show CLI commands"
```

---

### Task 14: Pipeline runner — connect orchestrator to CLI

**Files:**
- Create: `onep/orchestrator/runner.py`
- Modify: `onep/cli/create.py` (update run command)
- Create: `tests/test_orchestrator/test_runner.py`

- [ ] **Step 1: Create onep/orchestrator/runner.py**

```python
"""Pipeline runner — executes stages sequentially, handles state and checkpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from onep.config import load_config
from onep.llm.adapters import get_llm
from onep.persistence.database import (
    init_db, get_project, update_project,
    insert_stage_run, update_stage_run,
)
from onep.persistence.models import (
    Project, PipelineState, StageRun, StageStatus, ProjectStatus,
)
from onep.persistence.state import load_state, save_state
from onep.tools.git import GitTool
from onep.orchestrator.greenfield import GREENFIELD_STAGES, STAGE_PROMPTS

console = Console()


def run_pipeline(project_name: str, start_from: Optional[str] = None) -> bool:
    """
    Execute the Greenfield pipeline for a project.

    Returns True if the pipeline completed successfully.
    """
    config = load_config()
    init_db()

    # Find project by name
    from onep.persistence.database import list_projects
    projects = list_projects()
    project = next((p for p in projects if p.name == project_name), None)
    if project is None:
        console.print(f"[red]Project '{project_name}' not found.[/red]")
        return False

    workspace = Path(project.workspace_path)
    state = load_state(workspace)
    git = GitTool(workspace=workspace)
    llm = get_llm()

    # Determine which stages to run
    stages = GREENFIELD_STAGES
    skip_until = start_from or state.current_stage

    # Update project status
    project.status = ProjectStatus.RUNNING
    project.touch()
    update_project(project)

    approval_required_stages = {"pm", "architect"}  # Stages that need user approval

    for stage in stages:
        stage_name = stage["name"]

        # Skip already completed stages
        if stage_name in state.stages_completed:
            continue

        # If resuming, skip past stages until we reach the target
        if skip_until and stage_name not in [s["name"] for s in stages if s["name"] == skip_until]:
            continue
        skip_until = None  # Only skip on first iteration

        console.print(f"\n[bold cyan]▶ Stage: {stage_name} ({stage['agent']})[/bold cyan]")

        # Create stage run record
        stage_run = StageRun(
            project_id=project.id,
            stage_name=stage_name,
            agent_name=stage["agent"],
        )
        insert_stage_run(stage_run)

        # Update current stage
        project.current_stage = stage_name
        project.touch()
        update_project(project)
        state.current_stage = stage_name
        save_state(workspace, state)

        # Get context for the prompt
        prd_content = ""
        prd_path = workspace / "docs" / "PRD.md"
        if prd_path.exists():
            prd_content = prd_path.read_text()

        # Build prompt
        from onep.orchestrator.greenfield import STAGE_PROMPTS
        prompt_template = STAGE_PROMPTS[stage_name]
        requirement = getattr(project, 'requirement', '')
        user_prompt = prompt_template.format(
            requirement=requirement,
            prd_content=prd_content,
            workspace=str(workspace),
        )

        system_prompt = (
            "你是一个软件开发团队的成员。请按照指令完成当前阶段的工作。"
            "直接输出结果，保存到指定文件，不需要额外解释。"
        )

        # Run the stage
        stage_run.start()
        insert_stage_run(stage_run)  # Re-insert with start time

        try:
            response = llm.invoke(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                stage_name=stage_name,
            )
            console.print(f"[dim]Agent response received ({len(response)} chars)[/dim]")

            # If agent output contains file writing instructions, save them
            _save_agent_output(workspace, response, stage_name)

            stage_run.complete(output_files=_detect_output_files(workspace, stage_name))
            update_stage_run(stage_run)

        except Exception as e:
            console.print(f"[red]Stage failed: {e}[/red]")
            stage_run.fail(str(e))
            update_stage_run(stage_run)
            project.status = ProjectStatus.FAILED
            project.touch()
            update_project(project)
            return False

        # Git commit after stage completion
        git.add(["."])
        git.commit(f"feat: {stage_name} stage completed — {stage['description']}")

        # Mark stage complete
        state.stages_completed.append(stage_name)
        state.current_stage = ""
        save_state(workspace, state)

        # Handle approval gates
        if stage_name in approval_required_stages and not config.pipeline.auto_approve:
            state.pending_approval = True
            save_state(workspace, state)
            console.print(f"[yellow]⏸ Approval required for stage: {stage_name}[/yellow]")
            console.print(f"  Run: [bold cyan]onep approve {project_name}[/bold cyan] to continue")
            console.print(f"   or: [bold cyan]onep reject {project_name} '<feedback>'[/bold cyan] to request changes")

            # In MVP, we pause here. The user resumes via CLI.
            project.status = ProjectStatus.PAUSED
            project.touch()
            update_project(project)
            return False  # Pipeline paused for approval

        state.pending_approval = False
        save_state(workspace, state)

    # All stages complete
    project.status = ProjectStatus.COMPLETED
    project.touch()
    update_project(project)

    console.print(f"\n[bold green]🎉 Project '{project_name}' completed successfully![/bold green]")
    return True


def _save_agent_output(workspace: Path, response: str, stage_name: str) -> None:
    """Parse agent response and save any file outputs to the workspace."""
    # Agent output with ```file:path ... ``` blocks
    import re
    file_blocks = re.findall(r'```(?:file:)?([\w./-]+)\n(.*?)```', response, re.DOTALL)
    for filepath, content in file_blocks:
        full_path = workspace / filepath
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content.strip())

    # If no file blocks found, the agent might write files directly via tool calls.
    # CrewAI's agent execution handles tool calls automatically.


def _detect_output_files(workspace: Path, stage_name: str) -> list[str]:
    """Detect which files were created/modified by a stage."""
    stage_outputs = {
        "pm": ["docs/PRD.md"],
        "designer": ["docs/DESIGN.md"],
        "architect": ["docs/ARCHITECTURE.md"],
        "developer": ["backend/", "frontend/", "docker-compose.yml", "Dockerfile"],
        "tester": ["docs/TEST_REPORT.md"],
        "devops": ["docs/DEPLOY_LOG.md"],
    }
    expected = stage_outputs.get(stage_name, [])
    result = []
    for path in expected:
        if (workspace / path).exists():
            result.append(path)
    return result
```

- [ ] **Step 2: Create tests/test_orchestrator/test_runner.py**

```python
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from onep.orchestrator.runner import _detect_output_files


def test_detect_output_files_pm():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "docs").mkdir(parents=True)
        (ws / "docs" / "PRD.md").write_text("# PRD")
        files = _detect_output_files(ws, "pm")
        assert "docs/PRD.md" in files


def test_detect_output_files_empty():
    with tempfile.TemporaryDirectory() as tmp:
        files = _detect_output_files(Path(tmp), "pm")
        assert files == []
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_orchestrator/ -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add onep/orchestrator/runner.py onep/cli/create.py tests/test_orchestrator/test_runner.py
git commit -m "feat: add pipeline runner connecting orchestrator to CLI"
```

---

### Task 15: Integration — end-to-end smoke test

**Files:**
- Create: `tests/test_integration/__init__.py`
- Create: `tests/test_integration/test_greenfield_smoke.py`

- [ ] **Step 1: Create tests/test_integration/__init__.py**

```python
"""Integration tests for the full system."""
```

- [ ] **Step 2: Create tests/test_integration/test_greenfield_smoke.py**

```python
"""Smoke test: verify all components wire together without LLM calls."""
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from onep.agents.registry import get_agent, list_agents, clear_registry
from onep.config import Config, load_config
from onep.orchestrator.greenfield import GREENFIELD_STAGES, STAGE_PROMPTS
from onep.persistence.models import Project, ProjectMode, PipelineState, StageRun, StageStatus
from onep.persistence.state import load_state, save_state
from onep.persistence.database import init_db, insert_project, get_project, list_projects
from onep.subflows.code_review import build_code_review_graph
from onep.subflows.test_retry import build_test_retry_graph
from onep.main import cli


def test_config_loads():
    config = load_config()
    assert config.llm.default_model is not None
    assert config.pipeline.max_retries > 0


def test_all_agents_registered():
    # Clear registry and re-import to trigger registration
    clear_registry()
    import onep.agents.pm
    import onep.agents.designer
    import onep.agents.architect
    import onep.agents.developer
    import onep.agents.tester
    import onep.agents.devops

    agents = list_agents()
    assert "pm" in agents
    assert "designer" in agents
    assert "architect" in agents
    assert "developer" in agents
    assert "tester" in agents
    assert "devops" in agents


def test_agent_instantiation():
    clear_registry()
    import onep.agents.pm
    import onep.agents.designer
    import onep.agents.architect
    import onep.agents.developer
    import onep.agents.tester
    import onep.agents.devops

    for name in ["pm", "designer", "architect", "developer", "tester", "devops"]:
        agent = get_agent(name)
        assert agent.role is not None
        assert agent.goal is not None


def test_pipeline_stages_have_prompts():
    for stage in GREENFIELD_STAGES:
        assert stage["name"] in STAGE_PROMPTS


def test_state_save_and_load():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        state = PipelineState(
            mode="greenfield",
            current_stage="developer",
            stages_completed=["pm", "designer", "architect"],
        )
        save_state(ws, state)
        loaded = load_state(ws)
        assert loaded.current_stage == "developer"
        assert len(loaded.stages_completed) == 3


def test_project_crud():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "meta.db"
        with mock.patch("onep.persistence.database._config_dir", return_value=Path(tmp)):
            init_db()
            p = Project(
                name="smoke-test",
                mode=ProjectMode.GREENFIELD,
                workspace_path="/tmp/test-ws",
            )
            insert_project(p)
            loaded = get_project(p.id)
            assert loaded is not None
            assert loaded.name == "smoke-test"


def test_subflow_graphs_compile():
    cr = build_code_review_graph()
    assert cr is not None

    tr = build_test_retry_graph()
    assert tr is not None


def test_cli_shows_help():
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "OnePTeam" in result.output


def test_cli_create_and_status_registered():
    from click.testing import CliRunner
    runner = CliRunner()
    # Verify create command exists
    result = runner.invoke(cli, ["create", "--help"])
    assert result.exit_code == 0
    # Verify status command exists
    result = runner.invoke(cli, ["status", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass

- [ ] **Step 4: Verify CLI is wired up**

Run: `python -m onep.main --help`
Expected: displays help with create, status, show commands

- [ ] **Step 5: Commit**

```bash
git add tests/test_integration/
git commit -m "test: add integration smoke tests for full system"
```

---

## Post-MVP Iterations (not in this plan)

The following are deferred to future plans:

1. **Brownfield pipeline** — `onep analyze` command, code analyzer agent, multi-round discussion
2. **Web UI** — React management console on top of the API
3. **Cloud deployment** — DeployTarget abstraction for AWS/K8s
4. **Test depth** — E2E tests, performance tests, security scans
5. **Multi-developer parallelism** — Multiple developer agents working on different modules
6. **Mobile target** — React Native code generation
