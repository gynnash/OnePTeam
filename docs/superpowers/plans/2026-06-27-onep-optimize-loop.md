# onep optimize loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an optimize engine that executes code changes based on strategy analysis items, exposed as `/execute` in workbench and `onep optimize` as a fully automated command.

**Architecture:** Shared `OptimizeEngine` with 3 steps (architect_refine → developer_implement → tester_verify). B mode via workbench slash command. C mode via CLI with gate checks (impact/cost/test). Progress logged to JSONL, final report to Markdown.

**Tech Stack:** Click + Rich (CLI), GitPython (commit/revert), existing agents (architect, developer, tester).

---

## File Map

| Action | Path | Role |
|--------|------|------|
| Create | `onep/strategy/optimize_engine.py` | Shared 3-step engine |
| Create | `onep/cli/optimize_cmd.py` | `onep optimize` CLI |
| Modify | `onep/strategy/workbench.py` | Add `/execute` slash command |
| Modify | `onep/strategy/models.py` | Add impact classification helper |
| Create | `tests/test_strategy/test_optimize_engine.py` | Engine tests |
| Create | `tests/test_cli/test_optimize.py` | CLI tests |

---

### Task 1: Impact classification helper

**Files:**
- Modify: `onep/strategy/models.py`

**Goal:** Add a deterministic impact classification function based on the spec's criteria.

- [ ] **Step 1: Add to `onep/strategy/models.py`**

```python
IMPACT_RULES = {
    "high": [
        "api", "schema", "migration", "contract", "signature", "breaking",
        "security", "injection", "leak", "crash", "data loss", "corruption",
        "regression", "correctness", "output", "parse", "error",
    ],
    "medium": [
        "performance", "latency", "slow", "cost", "token", "memory",
        "duplicate", "retry", "timeout", "logging", "monitoring",
        "refactor", "maintainability",
    ],
    "low": [
        "naming", "rename", "style", "comment", "format", "type hint",
        "docstring", "spelling", "typo",
    ],
}

def classify_impact(title: str, summary: str, tags: list[str],
                    override: str | None = None) -> str:
    """Classify impact as high/medium/low based on keyword heuristics.
    Falls back to LLM judgment. Accepts manual override."""
    if override and override in ("high", "medium", "low"):
        return override
    text = (title + " " + summary + " " + " ".join(tags)).lower()
    for level in ("high", "medium", "low"):
        if any(kw in text for kw in IMPACT_RULES[level]):
            return level
    return "medium"  # default fallback
```

- [ ] **Step 2: Run tests**

```
pytest tests/test_strategy/test_models.py -q
Expected: all pass
```

- [ ] **Step 3: Commit**

```bash
git add onep/strategy/models.py
git commit -m "feat: add deterministic impact classification helper"
```

---

### Task 2: Optimize Engine

**Files:**
- Create: `onep/strategy/optimize_engine.py`
- Create: `tests/test_strategy/test_optimize_engine.py`

**Goal:** Shared 3-step engine: architect refine → developer implement → tester verify.

- [ ] **Step 1: Create test**

```python
from pathlib import Path
from onep.strategy.optimize_engine import OptimizeEngine
from onep.strategy.models import StrategyItem

def test_engine_returns_structure():
    engine = OptimizeEngine()
    item = StrategyItem(
        title="test", file_location="f.py:1",
        summary="test", tags=["perf"], impact="medium",
    )
    result = engine.execute(item, "/tmp/src", "/tmp/ws")
    assert "success" in result
    assert "files_changed" in result
    assert "steps" in result
    assert len(result["steps"]) == 3

def test_engine_steps_are_sequential():
    engine = OptimizeEngine()
    item = StrategyItem(
        title="test", file_location="f.py:1",
        summary="test", tags=["style"], impact="low",
    )
    result = engine.execute(item, "/tmp/src", "/tmp/ws")
    step_names = [s["name"] for s in result["steps"]]
    assert step_names == ["architect_refine", "developer_implement", "tester_verify"]
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_strategy/test_optimize_engine.py -v
Expected: FAIL
```

- [ ] **Step 3: Create `onep/strategy/optimize_engine.py`**

```python
"""Optimize Engine — shared 3-step execution for strategy items."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from onep.strategy.models import StrategyItem

console = Console()

ARCHITECT_REFINE_PROMPT = """你是一位架构师。基于以下优化Plan，输出一份技术实现方案。

优化方向: {title}
问题摘要: {summary}
策略标签: {tags}
影响级别: {impact}
文件位置: {file_location}

Plan 内容:
{plan_content}

输出一份简洁的技术实现方案，包含:
1. 需要修改的文件列表
2. 每个文件的修改要点
3. API 变更（如有）
4. 实现风险
"""

DEVELOPER_PROMPT = """你是一位研发工程师。根据技术方案实现代码改动。

技术方案:
{tech_plan}

源代码位置: {source_path}

请直接修改源码文件。使用 file_write 写入改动，使用 shell 运行 lint 检查。
每个文件改动后确保代码可运行。不要创建新项目结构，只修改现有文件。"""

TESTER_PROMPT = """你是一位测试工程师。验证代码改动。

源代码位置: {source_path}
改动文件: {files_changed}

请运行相关测试。如果项目有 pytest 配置，运行 pytest。否则检查代码是否能正常导入。
输出测试结果: passed/failed, 测试数量, 失败详情。"""


class OptimizeEngine:
    """3-step execution engine for strategy optimization items."""

    def execute(self, item: StrategyItem, source_path: str, workspace: str,
                llm_adapter=None) -> dict:
        """Execute architect_refine → developer_implement → tester_verify.
        Returns {success, files_changed, steps, test_output}.
        """
        result = {"success": False, "files_changed": [], "steps": []}

        # Step 1: Architect refine
        console.print("\n  [bold cyan]=== Step 1/3: 架构细化 ===[/bold cyan]")
        tech_plan = self._step_architect(item, source_path, llm_adapter)
        result["steps"].append({"name": "architect_refine", "output": tech_plan})

        if not tech_plan:
            result["error"] = "architect_refine failed"
            return result

        # Step 2: Developer implement
        console.print("\n  [bold cyan]=== Step 2/3: 代码实现 ===[/bold cyan]")
        impl_result = self._step_developer(tech_plan, source_path, llm_adapter)
        result["steps"].append({"name": "developer_implement", "output": impl_result})

        if not impl_result:
            result["error"] = "developer_implement failed"
            return result

        result["files_changed"] = impl_result.get("files", [])

        # Step 3: Tester verify
        console.print("\n  [bold cyan]=== Step 3/3: 测试验证 ===[/bold cyan]")
        test_result = self._step_tester(source_path, result["files_changed"], llm_adapter)
        result["steps"].append({"name": "tester_verify", "output": test_result})
        result["test_output"] = test_result
        result["success"] = test_result.get("passed", False) if test_result else False

        return result

    def _step_architect(self, item, source_path, llm_adapter):
        if llm_adapter is None:
            return "LLM not available"
        plan_content = ""
        if item.plan_path:
            p = Path(item.plan_path)
            if p.exists():
                plan_content = p.read_text()[:3000]
        prompt = ARCHITECT_REFINE_PROMPT.format(
            title=item.title, summary=item.summary,
            tags=", ".join(item.tags), impact=item.impact,
            file_location=item.file_location,
            plan_content=plan_content or item.summary,
        )
        return _invoke_stream(llm_adapter, "architect", prompt, source_path)

    def _step_developer(self, tech_plan, source_path, llm_adapter):
        if llm_adapter is None:
            return None
        prompt = DEVELOPER_PROMPT.format(
            tech_plan=tech_plan, source_path=source_path,
        )
        output = _invoke_stream(llm_adapter, "developer", prompt, source_path)
        return {"output": output, "files": _extract_files(output)}

    def _step_tester(self, source_path, files_changed, llm_adapter):
        if llm_adapter is None:
            return {"passed": False, "output": "LLM not available"}
        prompt = TESTER_PROMPT.format(
            source_path=source_path,
            files_changed=", ".join(files_changed) if files_changed else "unknown",
        )
        output = _invoke_stream(llm_adapter, "tester", prompt, source_path)
        passed = "passed" in output.lower() and "failed" not in output.lower()
        return {"passed": passed, "output": output}


def _invoke_stream(llm_adapter, agent_name: str, prompt: str,
                   source_path: str) -> str:
    """Invoke agent with tools and streaming output."""
    from onep.agents.registry import get_agent
    from onep.llm.router import resolve_model

    agent = get_agent(agent_name, workspace=source_path, source_id="")
    system_prompt = _build_prompt(agent)
    tools = getattr(agent, "tools", []) or []
    model_name, _ = resolve_model(agent_name)

    console.print(f"  [dim]Agent: {agent.role} | Model: {model_name}[/dim]")

    parts = []
    for event in llm_adapter.invoke_with_tools_stream(
        system_prompt=system_prompt,
        user_prompt=prompt,
        tools=tools,
        stage_name=agent_name,
        max_tool_rounds=10,
    ):
        if event["type"] == "tool_call":
            args_str = ", ".join(
                f"{k}={_brief_val(v)}" for k, v in event.get("tool_args", {}).items()
            )
            console.print(f"  [dim]{event['tool_name']}({args_str})[/dim]")
        elif event["type"] == "token":
            console.print(event["content"], end="")
            parts.append(event["content"])
        elif event["type"] == "done":
            pass

    console.print()
    from onep.llm.adapters import display_usage
    display_usage()
    return "".join(parts)


def _build_prompt(agent) -> str:
    return f"{agent.role}\n\n目标: {agent.goal}\n\n背景: {agent.backstory}\n\n请按照指令完成工作。"


def _brief_val(v) -> str:
    s = str(v)
    if "/" in s:
        return s.rsplit("/", 1)[-1]
    if len(s) > 70:
        return s[:67] + "..."
    return s


def _extract_files(output: str) -> list[str]:
    import re
    files = set()
    for m in re.finditer(r'(?:file_write|modified|changed)[^\n]*?([\w./-]+\.\w+)', output):
        files.add(m.group(1))
    return list(files)[:20]
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_strategy/test_optimize_engine.py -v
Expected: PASS (2 tests)
```

- [ ] **Step 5: Commit**

```bash
git add onep/strategy/optimize_engine.py tests/test_strategy/test_optimize_engine.py
git commit -m "feat: add optimize engine with 3-step execution"
```

---

### Task 3: `/execute` — Workbench slash command

**Files:**
- Modify: `onep/strategy/workbench.py`

**Goal:** Add `/execute <n>` command to workbench dialogue.

- [ ] **Step 1: Add to SLASH_COMMANDS and HELP_TEXT**

In `SLASH_COMMANDS` dict, add: `"execute": "execute"`

In `HELP_TEXT`, add before `/help`:
```
  [bold]/execute[/bold] <n>          执行第 n 个优化方向的开发+测试
```

- [ ] **Step 2: Add handler in `handle_slash_command`**

```python
elif cmd == "execute":
    _cmd_execute(args, wb, workspace, llm_adapter)
```

- [ ] **Step 3: Add `_cmd_execute` function**

```python
def _cmd_execute(args: str, wb: WorkbenchState, workspace: Path,
                 llm_adapter=None) -> None:
    """Execute develop+test for an optimization item."""
    item_id = _resolve_item_id(args, wb)
    if not item_id:
        console.print(f"[red]未找到方向: {args}[/red]")
        return
    item = _find_item(wb, item_id)
    if not item:
        return
    if not item.plan_path:
        console.print("[red]请先生成 Plan (/plan) 再执行。[/red]")
        return

    from onep.strategy.optimize_engine import OptimizeEngine
    engine = OptimizeEngine()
    result = engine.execute(item, wb.source_path, str(workspace), llm_adapter)

    if result["success"]:
        console.print(f"\n[green]✅ 优化 {item.title} 执行完成[/green]")
        console.print(f"改动文件: {', '.join(result['files_changed']) or '无'}")
    else:
        console.print(f"\n[red]❌ 优化 {item.title} 执行失败[/red]")
        if result.get("error"):
            console.print(f"[red]{result['error']}[/red]")
```

- [ ] **Step 4: Run tests**

```
pytest tests/test_strategy/test_workbench.py -q
Expected: existing tests pass
```

- [ ] **Step 5: Commit**

```bash
git add onep/strategy/workbench.py
git commit -m "feat: add /execute command to workbench"
```

---

### Task 4: `onep optimize` — CLI command

**Files:**
- Create: `onep/cli/optimize_cmd.py`
- Create: `tests/test_cli/test_optimize.py`

**Goal:** Full auto command with gates and reporting.

- [ ] **Step 1: Create test**

```python
from click.testing import CliRunner
from onep.cli.optimize_cmd import optimize_cmd

def test_optimize_help():
    runner = CliRunner()
    result = runner.invoke(optimize_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--max-rounds" in result.output
    assert "--auto-approve" in result.output
    assert "--max-cost" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_cli/test_optimize.py -v
Expected: FAIL
```

- [ ] **Step 3: Create `onep/cli/optimize_cmd.py`**

```python
"""onep optimize — automated optimize loop with safety gates."""
from __future__ import annotations

import json
import time
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from onep.config import load_config
from onep.persistence.database import init_db, insert_project
from onep.persistence.models import Project, ProjectMode
from onep.strategy.models import classify_impact
from onep.strategy.scanner import walk_files, batch_files, parse_scan_response, get_strategy_files
from onep.strategy.analyzer import parse_analysis_response, load_analysis_items, save_analysis_items
from onep.strategy.optimize_engine import OptimizeEngine
from onep.llm.cost import CostTracker, estimate_scan_cost

console = Console()


@click.command()
@click.argument("source", type=str)
@click.option("--max-rounds", type=int, default=5, help="Max optimize rounds")
@click.option("--auto-approve", default="low,medium",
              help="Impact levels to auto-execute (comma-separated)")
@click.option("--max-cost", type=float, default=0, help="Max cost in USD (0=no limit)")
@click.option("--name", "-n", default=None, help="Project name")
def optimize_cmd(source: str, max_rounds: int, auto_approve: str,
                 max_cost: float, name: str | None):
    """Automated optimize loop: analyze → plan → develop → test → repeat."""
    import re, uuid, os
    source_path = Path(source).resolve()
    if name is None:
        clean = re.sub(r'[^\w一-鿿]', '', source_path.name)[:20]
        name = clean or f"optimize-{uuid.uuid4().hex[:6]}"

    config = load_config()
    init_db()
    project_root = Path(os.path.expanduser(config.project.root_dir))
    workspace = (project_root / "projects" / name / "workspace")
    workspace.mkdir(parents=True, exist_ok=True)
    project = Project(name=name, mode=ProjectMode.BROWNFIELD,
                      workspace_path=str(workspace))
    insert_project(project)

    auto_levels = set(auto_approve.split(","))

    tracker = CostTracker(budget=max_cost)

    from onep.llm.adapters import get_llm
    llm = None
    try:
        llm = get_llm()
    except Exception:
        pass

    engine = OptimizeEngine()

    skipped: list[dict] = []
    completed: list[dict] = []
    failed: list[dict] = []
    log_path = workspace / "optimize_log.jsonl"

    for round_num in range(1, max_rounds + 1):
        console.print(f"\n[bold]=== Round {round_num}/{max_rounds} ===[/bold]")

        # Analyze
        all_files = walk_files(source_path)
        batches = batch_files(all_files)
        all_results = []
        for batch in batches:
            # simplified scan — in real impl use full analyze pipeline
            prompt = _build_scan_prompt(batch, source_path)
            response = _invoke_llm(llm, "analyzer", prompt)
            if response:
                all_results.extend(parse_scan_response(response))
        strategy_files = get_strategy_files(all_results)

        if not strategy_files:
            console.print("[green]No more optimization targets found.[/green]")
            break

        # Analyze Layer 2
        analyze_prompt = _build_analyze_prompt(strategy_files, str(source_path))
        response = _invoke_llm(llm, "strategy_architect", analyze_prompt)
        items = parse_analysis_response(response) if response else []

        if not items:
            break

        # Process each item
        round_completed = 0
        for item_data in items:
            item = _dict_to_item(item_data)
            impact = classify_impact(item.title, item.summary, item.tags)

            if impact not in auto_levels:
                skipped.append({"title": item.title, "impact": impact, "round": round_num})
                console.print(f"  [yellow]⏸ 跳过 (impact={impact}): {item.title}[/yellow]")
                continue

            if not tracker.can_continue():
                console.print(f"[red]预算用尽 ({tracker.summary()})[/red]")
                break

            console.print(f"  [cyan]▶ 执行: {item.title} (impact={impact})[/cyan]")
            result = engine.execute(item, str(source_path), str(workspace), llm)

            if result["success"]:
                completed.append({"title": item.title, "impact": impact, "round": round_num})
                round_completed += 1
            else:
                failed.append({"title": item.title, "impact": impact, "round": round_num,
                              "error": result.get("error", "unknown")})

            # Log
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps({"round": round_num, "item": item.title,
                                    "impact": impact, "success": result["success"],
                                    "cost": tracker.spent}, ensure_ascii=False) + "\n")

        console.print(f"  [dim]Round {round_num}: {round_completed} completed, "
                      f"{len(skipped)} skipped, {tracker.summary()}[/dim]")

        if round_completed == 0:
            break

    # Generate report
    _generate_report(workspace, completed, failed, skipped, tracker, max_rounds)


def _invoke_llm(llm, agent_name: str, prompt: str) -> str | None:
    if llm is None:
        return None
    try:
        return llm.invoke(
            system_prompt=f"You are the {agent_name} agent. Complete the task as instructed.",
            user_prompt=prompt, stage_name=agent_name,
        )
    except Exception:
        return None


def _dict_to_item(d: dict):
    from onep.strategy.models import StrategyItem
    return StrategyItem(
        title=d.get("title", "?"),
        file_location=d.get("file_location", "?"),
        summary=d.get("summary", ""),
        tags=d.get("tags", []),
        impact=d.get("impact", "medium"),
    )


def _generate_report(workspace: Path, completed: list, failed: list,
                     skipped: list, tracker: CostTracker, max_rounds: int):
    lines = [
        "# 优化报告",
        f"- 执行轮次: {max_rounds}",
        f"- 成功: {len(completed)}",
        f"- 失败: {len(failed)}",
        f"- 跳过待审核: {len(skipped)}",
        f"- 总花费: {tracker.summary()}",
        "",
    ]
    if completed:
        lines.append("## 成功")
        for c in completed:
            lines.append(f"- [{c['impact']}] {c['title']} (round {c['round']})")
    if failed:
        lines.append("\n## 失败")
        for f in failed:
            lines.append(f"- [{f['impact']}] {f['title']}: {f.get('error', '?')}")
    if skipped:
        lines.append("\n## 待审核 (high impact)")
        for s in skipped:
            lines.append(f"- [{s['impact']}] {s['title']} (round {s['round']})")

    report = "\n".join(lines)
    (workspace / "optimize_report.md").write_text(report)

    console.print(Panel(report, title="Optimize Report"))


COMMANDS = [optimize_cmd]
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_cli/test_optimize.py -v
Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add onep/cli/optimize_cmd.py tests/test_cli/test_optimize.py
git commit -m "feat: add onep optimize CLI with gates and reporting"
```
