# Brownfield Capability Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Align Brownfield code modification, problem discovery, and project context capabilities with Claude Code.

**Architecture:** Scanner reads full file content (not just paths) with hash-based caching. A Re-check layer filters false positives between Scanner and Analyzer. Project context auto-generated and injected to all LLM calls.

**Tech Stack:** hashlib, JSONL cache, existing scanner/analyzer modules.

---

## File Map

| Action | Path | Role |
|--------|------|------|
| Create | `onep/strategy/scan_cache.py` | File hash cache for scan results |
| Create | `onep/strategy/project_context.py` | Auto-generate + load project context |
| Modify | `onep/cli/analyze.py` | Wire full-content scan, cache, re-check, context |
| Modify | `onep/orchestrator/brownfield.py` | Update SCAN_PROMPT for full content |
| Modify | `onep/strategy/optimize_engine.py` | Inject project context into execute prompt |
| Modify | `onep/strategy/workbench.py` | Inject project context into dialogue + plan prompts |
| Modify | `onep/cli/optimize_cmd.py` | Pass project context |

---

### Task 1: Scanner — full content + cache + Re-check

**Files:**
- Create: `onep/strategy/scan_cache.py`
- Modify: `onep/orchestrator/brownfield.py`
- Modify: `onep/cli/analyze.py`

**Goal:** Scanner sends full file content to LLM, caches results by hash, adds Re-check layer.

- [ ] **Step 1: Create `onep/strategy/scan_cache.py`**

```python
"""File-level scan result cache keyed by content hash."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

def file_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]

class ScanCache:
    def __init__(self, workspace: Path):
        self.path = workspace / "scan_cache.jsonl"
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    self._data[entry["file"]] = entry

    def get(self, file_path: str, content: str) -> dict | None:
        h = file_hash(content)
        entry = self._data.get(file_path)
        if entry and entry.get("hash") == h:
            return entry
        return None

    def put(self, file_path: str, content: str, is_strategy: bool, reason: str,
            recheck_verdict: str = "", recheck_reason: str = ""):
        h = file_hash(content)
        entry = {
            "file": file_path, "hash": h,
            "is_strategy": is_strategy, "reason": reason,
            "recheck_verdict": recheck_verdict, "recheck_reason": recheck_reason,
        }
        self._data[file_path] = entry
        with open(self.path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
```

- [ ] **Step 2: Update SCAN_PROMPT in brownfield.py**

Replace the current file-list-only SCAN_PROMPT:

```python
SCAN_PROMPT_FULL = """请分析以下文件内容，判定是否包含业务策略或算法策略逻辑。

策略逻辑包括：
- 推荐算法、排序算法、匹配算法
- LLM prompt 链、Agent 工作流、模型路由
- 缓存策略、限流策略、资源分配策略
- 业务规则、定价策略、风控规则、风险评分
- 任何影响系统行为的非平凡决策逻辑

不属于策略逻辑：
- 纯工具函数（字符串处理、日期格式化）
- 配置常量或枚举
- 简单 CRUD（无决策逻辑）
- 样板代码（中间件、日志、路由注册）
- 测试文件

文件内容:
{file_block}

只输出一行 JSON：
{{"file": "<path>", "is_strategy": true/false, "reason": "<一句话理由>"}}"""
```

- [ ] **Step 3: Add RECHECK_PROMPT to brownfield.py**

```python
RECHECK_PROMPT = """判定以下文件是否有值得优化的策略逻辑。如果不是，输出 drop。

文件: {file_path}
内容:
```
{content}
```

输出一行 JSON：
{{"verdict": "keep" | "drop", "reason": "<一句话>"}}

drop 的情况：
- 虽然有策略关键词但实现已合理
- 纯样板代码被误标为策略
- 决策逻辑简单清晰无优化空间"""
```

- [ ] **Step 4: Update analyze.py scan loop**

In `_run_strategy_mode`, update the scan loop to read file content, use cache, and add re-check:

```python
from onep.strategy.scan_cache import ScanCache, file_hash
from onep.orchestrator.brownfield import SCAN_PROMPT_FULL, RECHECK_PROMPT

cache = ScanCache(workspace)

# Layer 1: Full-content scan
for i, batch in enumerate(batches):
    pending = []
    for f in batch:
        rel = str(f.relative_to(source_path))
        try:
            content = f.read_text()
        except Exception:
            content = ""
        cached = cache.get(rel, content)
        if cached is not None:
            all_results.append(ScanResult(
                file_path=rel, is_strategy=cached["is_strategy"],
                reason=cached["reason"],
            ))
        else:
            pending.append((f, rel, content))

    if pending:
        file_blocks = []
        for f, rel, content in pending:
            file_blocks.append(f"### {rel}\n```\n{content[:3000]}\n```")
        prompt = SCAN_PROMPT_FULL.format(file_block="\n\n".join(file_blocks))
        response = _invoke_agent("analyzer", prompt)
        if response:
            results = parse_scan_response(response)
            for r in results:
                # save to cache
                orig_content = next((c for _, r2, c in pending if r2 == r.file_path), "")
                cache.put(r.file_path, orig_content, r.is_strategy, r.reason)
        else:
            results = [_no_llm_scan_result(rel) for _, rel, _ in pending]
        all_results.extend(results)

# Layer 1B: Re-check
strategy_files = get_strategy_files(all_results)
recheck_cache = ScanCache(workspace)  # reuses same cache file
filtered = []
for sf in strategy_files:
    full = source_path / sf
    try:
        content = full.read_text()
    except Exception:
        filtered.append(sf); continue
    cached = cache.get(sf, content)
    if cached and cached.get("recheck_verdict") == "drop":
        continue  # pre-filtered
    prompt = RECHECK_PROMPT.format(file_path=sf, content=content[:3000])
    response = _invoke_agent("analyzer", prompt)
    if response:
        try:
            verdict = json.loads(response.split("\n")[0])
            if verdict.get("verdict") == "drop":
                cache.put(sf, content, True, cached["reason"] if cached else "",
                         recheck_verdict="drop", recheck_reason=verdict.get("reason", ""))
                continue
            cache.put(sf, content, True, cached["reason"] if cached else "",
                     recheck_verdict="keep", recheck_reason=verdict.get("reason", ""))
        except Exception:
            pass
    filtered.append(sf)

strategy_files = filtered
```

- [ ] **Step 5: Run tests**

```
pytest tests/ -q
Expected: all pass
```

- [ ] **Step 6: Commit**

```bash
git add onep/strategy/scan_cache.py onep/orchestrator/brownfield.py onep/cli/analyze.py
git commit -m "feat: full-content scanner + hash cache + re-check layer"
```

---

### Task 2: Project context — auto-generate + inject

**Files:**
- Create: `onep/strategy/project_context.py`
- Modify: `onep/cli/analyze.py`
- Modify: `onep/strategy/optimize_engine.py`
- Modify: `onep/strategy/workbench.py`
- Modify: `onep/cli/optimize_cmd.py`

**Goal:** Auto-generate project context on first analyze, inject into all LLM calls.

- [ ] **Step 1: Create `onep/strategy/project_context.py`**

```python
"""Project context — auto-generated overview of the codebase for agent injection."""
from __future__ import annotations

from pathlib import Path

def generate_project_context(source_path: str, workspace: Path, llm_adapter=None) -> str:
    """Generate a project context overview using LLM analysis."""
    sp = Path(source_path)
    # gather basic stats
    py_files = list(sp.rglob("*.py"))
    ts_files = list(sp.rglob("*.ts")) + list(sp.rglob("*.tsx"))
    has_pyproject = (sp / "pyproject.toml").exists()
    has_package_json = (sp / "package.json").exists()
    has_docker = (sp / "Dockerfile").exists() or (sp / "docker-compose.yml").exists()

    # collect top-level dirs
    top_dirs = sorted(set(
        p.relative_to(sp).parts[0] for p in sp.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name not in ("node_modules", "__pycache__", ".git")
    ))

    # gather entry points
    setup_files = []
    for pat in ["main.py", "app.py", "index.ts", "index.tsx", "cli.py"]:
        found = list(sp.rglob(pat))
        setup_files.extend(str(f.relative_to(sp)) for f in found[:3])

    if llm_adapter:
        prompt = f"""分析以下项目信息，生成一份简洁的项目概述。

源路径: {source_path}
Python 文件: {len(py_files)} 个
TypeScript 文件: {len(ts_files)} 个
顶层目录: {', '.join(top_dirs[:10])}
入口文件: {', '.join(setup_files[:10])}
有 pyproject.toml: {has_pyproject}
有 package.json: {has_package_json}
有 Docker: {has_docker}

输出 Markdown 格式的项目概述，包含:
1. Tech Stack
2. Directory Structure
3. Code Conventions (基于你看到的项目结构推断)
4. Key Patterns"""
        try:
            response = llm_adapter.invoke(
                system_prompt="你是一位项目分析专家。",
                user_prompt=prompt, stage_name="project_context",
            )
            path = workspace / "project_context.md"
            path.write_text(response)
            return response
        except Exception:
            pass
    return _fallback_context(source_path, py_files, ts_files, top_dirs, setup_files,
                            has_pyproject, has_package_json, has_docker)

def _fallback_context(source_path, py_files, ts_files, top_dirs, setup_files,
                      has_pyproject, has_package_json, has_docker) -> str:
    lines = [
        f"# Project Context",
        f"Source: {source_path}",
        f"Python files: {len(py_files)}",
        f"TypeScript files: {len(ts_files)}",
        f"Top directories: {', '.join(top_dirs[:10])}",
    ]
    if has_pyproject: lines.append("Has pyproject.toml")
    if has_package_json: lines.append("Has package.json")
    if has_docker: lines.append("Has Docker config")
    return "\n".join(lines)

def load_project_context(workspace: Path, source_path: str = "") -> str:
    """Load saved project context. Falls back to generating it."""
    path = workspace / "project_context.md"
    if path.exists():
        return path.read_text()
    if source_path:
        ctx = _fallback_context(source_path, [], [], [], [], False, False, False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(ctx)
        return ctx
    return ""

def merge_manual_context(source_path: str, auto_context: str) -> str:
    """Merge CLAUDE.md or ONEP.md content into project context."""
    sp = Path(source_path)
    for name in ("CLAUDE.md", "ONEP.md", "AGENTS.md"):
        p = sp / name
        if p.exists():
            manual = p.read_text()[:3000]
            return auto_context + f"\n\n## Manual Context ({name})\n\n{manual}"
    return auto_context
```

- [ ] **Step 2: Wire into analyze.py**

In `_run_strategy_mode`, after Layer 2 completes and before Layer 3:

```python
from onep.strategy.project_context import generate_project_context, merge_manual_context

ctx = load_project_context(workspace)
if not ctx:
    ctx = generate_project_context(str(source_path), workspace, llm)
    ctx = merge_manual_context(str(source_path), ctx)
```

Also inject `ctx` into `_invoke_agent` and `_invoke_agent_with_tools` as part of the system prompt. Add a `project_context` parameter to both functions, defaulting to `""`.

- [ ] **Step 3: Wire into optimize_engine.py**

In `execute()`, load and inject context into the EXECUTE_PROMPT:

```python
from onep.strategy.project_context import load_project_context
ctx = load_project_context(Path(workspace), source_path)
if ctx:
    prompt = EXECUTE_PROMPT.format(..., project_context=ctx)
```

Add `{project_context}` placeholder to EXECUTE_PROMPT.

- [ ] **Step 4: Wire into workbench.py**

In `_build_dialogue_context` and `_cmd_generate_plan`, inject context:

```python
from onep.strategy.project_context import load_project_context
ctx = load_project_context(workspace)
if ctx:
    context_parts.append(f"\n项目上下文:\n{ctx[:2000]}")
```

- [ ] **Step 5: Run tests**

```
pytest tests/ -q
Expected: all pass
```

- [ ] **Step 6: Commit**

```bash
git add onep/strategy/project_context.py onep/cli/analyze.py onep/strategy/optimize_engine.py onep/strategy/workbench.py onep/cli/optimize_cmd.py
git commit -m "feat: auto-generate project context + inject into all LLM calls"
```
