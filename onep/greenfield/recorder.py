"""Durable Greenfield run records and user-facing traces."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import shutil

from rich.console import Console
from rich.markup import escape
import yaml

from onep.greenfield.models import AcceptanceContract, GreenfieldRun, SlicePlan


class GreenfieldRecorder:
    def __init__(self, run_dir: Path, run: GreenfieldRun, console: Console):
        self.run_dir = Path(run_dir)
        self.run = run
        self.console = console
        self.started = time.monotonic()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._engineer_stats: dict = {}
        self._failure_counts: dict[str, int] = {}

    def begin_engineer_attempt(self) -> None:
        self._engineer_stats = {
            "rounds": 0,
            "reads": 0,
            "writes": 0,
            "commands": 0,
            "messages": [],
            "tool_context": {},
        }

    def save_run(self) -> None:
        self._write_yaml(self.run_dir / "run.yaml", self.run.to_dict())

    def save_contract(self, contract: AcceptanceContract) -> None:
        self._write_yaml(self.run_dir / "acceptance.yaml", contract.to_dict())
        target = Path(self.run.workspace) / ".onep" / "greenfield" / "acceptance.yaml"
        self._write_yaml(target, contract.to_dict())

    def save_slice(self, plan: SlicePlan, payload: dict | None = None) -> Path:
        path = self.run_dir / "slices" / plan.id / "plan.yaml"
        data = plan.to_dict()
        if payload:
            data["artifacts"] = payload
        self._write_yaml(path, data)
        return path

    def save_attempt(self, plan: SlicePlan, number: int, data: dict) -> Path:
        path = self.run_dir / "slices" / plan.id / "attempts" / f"{number:02d}.yaml"
        self._write_yaml(path, data)
        return path

    def save_review(self, plan: SlicePlan, data: dict) -> None:
        self._write_json(self.run_dir / "slices" / plan.id / "review.json", data)

    def save_diff(self, plan: SlicePlan, diff: str) -> None:
        self._write_text(self.run_dir / "slices" / plan.id / "final.diff", diff)

    def architecture_decision(self, data: dict) -> None:
        self._append_jsonl(self.run_dir / "architecture-decisions.jsonl", data)
        self._append_jsonl(
            Path(self.run.workspace)
            / ".onep"
            / "greenfield"
            / "architecture-decisions.jsonl",
            data,
        )

    def event(self, event_type: str, payload: dict | None = None) -> None:
        self._append_jsonl(
            self.run_dir / "events.jsonl",
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "stage": self.run.stage.value,
                "round": self.run.round_number,
                "payload": payload or {},
            },
        )

    def trace(self, stage: str, message: str, style: str = "cyan") -> None:
        elapsed = int(time.monotonic() - self.started)
        stamp = f"{elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}"
        self.console.print(f"[{style}][{stamp}] [{stage}] {escape(message)}[/{style}]")
        self.event("trace", {"label": stage, "message": message})

    def failure(
        self,
        stage: str,
        failure_type: str,
        detail: object,
        *,
        context: str = "",
    ) -> int:
        """Persist every failure and compact repeated console output."""
        raw_detail = str(detail or "No diagnostic output.")
        diagnostic = self._diagnostic(raw_detail)
        signature = hashlib.sha256(
            f"{stage}\0{failure_type}\0{diagnostic}".encode("utf-8")
        ).hexdigest()
        count = self._failure_counts.get(signature, 0) + 1
        self._failure_counts[signature] = count
        emit = count <= 3 or count % 3 == 0
        self.event(
            "failure_observed",
            {
                "label": stage,
                "failure_type": failure_type,
                "context": context,
                "detail": raw_detail,
                "diagnostic": diagnostic,
                "repeat_count": count,
                "console_emitted": emit,
            },
        )
        if emit:
            repeat = "首次" if count == 1 else f"同类失败累计 {count} 次"
            location = f" | {context}" if context else ""
            self.trace(
                stage,
                f"{failure_type}（{repeat}）{location} | {diagnostic}",
                "yellow",
            )
        return count

    def engineer_event(self, event: dict) -> None:
        """Persist full trajectory and print safe observable progress summaries."""
        if not self._engineer_stats:
            self.begin_engineer_attempt()
        self.event("engineer_trajectory", event)
        event_type = str(event.get("type") or "")
        payload = event.get("payload") or {}
        if event_type == "model_round_started":
            self._engineer_stats["rounds"] = payload.get("round", 0)
        elif event_type == "tool_requested":
            tool = str(payload.get("tool_name") or "unknown")
            args = payload.get("tool_args") or {}
            if tool in {"file_read", "file_list", "grep"}:
                self._engineer_stats["reads"] += 1
            elif tool in {"file_write", "edit"}:
                self._engineer_stats["writes"] += 1
            elif tool == "shell":
                self._engineer_stats["commands"] += 1
            detail = ""
            for key in ("path", "file_path", "command", "operation", "query"):
                if key in args:
                    detail = f" {key}={self._brief(self._redact(args[key]))}"
                    break
            self._engineer_stats["tool_context"][tool] = detail.strip()
            if self.run.options.verbose:
                self.trace("TOOL", f"准备执行 {tool}{detail}", "dim")
        elif event_type == "tool_completed":
            tool = str(payload.get("tool_name") or "unknown")
            raw_result = str(payload.get("tool_result") or "完成")
            result = self._brief(raw_result)
            if self._tool_failed(raw_result):
                self.failure(
                    "TOOL_FAIL",
                    tool,
                    raw_result,
                    context=self._engineer_stats.get("tool_context", {}).get(tool, ""),
                )
            if self.run.options.verbose:
                self.trace("TOOL", f"{tool} 完成：{result}", "dim")
        elif event_type == "model_message":
            content = self._brief(payload.get("content") or "", 600)
            if content and content not in self._engineer_stats["messages"]:
                self._engineer_stats["messages"].append(content)
                self.trace("MODEL", content, "blue")
        elif event_type == "implementation_nudge":
            self.trace(
                "PROGRESS",
                "连续检查后尚未修改文件，已要求模型停止宽泛分析并批量实现当前切片",
                "yellow",
            )
        elif event_type == "implementation_deadline":
            self.trace(
                "PROGRESS",
                "已进入实现截止阶段：停止继续读取和测试，剩余轮次只允许完成代码修改",
                "yellow",
            )
        elif event_type == "implementation_read_blocked" and self.run.options.verbose:
            self.trace("TOOL", "实现截止阶段已拦截新的只读操作", "dim")
        elif event_type == "full_test_blocked":
            self.trace(
                "TEST",
                "已阻止工程模型运行全量测试；继续实现当前切片，完整测试留给最终门禁",
                "yellow",
            )
        elif event_type == "loop_limit_reached":
            self.trace(
                "MODEL",
                f"达到工具轮次上限 {payload.get('rounds', '?')}，实现尚未完成",
                "yellow",
            )
        elif event_type == "loop_stuck":
            self.trace("MODEL", f"模型工具循环停滞：{self._brief(payload)}", "yellow")
        elif event_type == "loop_completed":
            if self.run.options.verbose:
                self.trace(
                    "MODEL",
                    f"模型完成本轮实现，共 {payload.get('rounds', '?')} 个工具轮次",
                    "green",
                )

    def engineer_summary(
        self,
        output: str,
        changed_files: list[str],
        termination_reason: str,
    ) -> None:
        stats = self._engineer_stats
        summary = self._brief(output, 600)
        if summary and not stats.get("messages"):
            self.trace("RESULT", summary, "blue")
        changed = ", ".join(changed_files[:8]) or "无"
        self.trace(
            "IMPLEMENT",
            f"模型轮次 {stats.get('rounds', 0)}；读取/搜索 {stats.get('reads', 0)}；"
            f"写入/编辑 {stats.get('writes', 0)}；命令 {stats.get('commands', 0)}；"
            f"结束原因 {termination_reason}；变更文件: {changed}",
            "green" if changed_files else "yellow",
        )

    @staticmethod
    def _brief(value, limit: int = 180) -> str:
        text = " ".join(str(value).split())
        return text if len(text) <= limit else text[: limit - 3] + "..."

    @staticmethod
    def _tool_failed(result: str) -> bool:
        lowered = result.strip().lower()
        return (
            lowered.startswith(("error:", "failed:", "command timed out"))
            or "traceback (most recent call last)" in lowered
            or re.search(r"\[exit:\s*[1-9]\d*\]", lowered) is not None
        )

    @staticmethod
    def _diagnostic(value: str, limit: int = 900) -> str:
        """Select actionable error lines rather than an arbitrary output tail."""
        lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
        meaningful = [line for line in lines if line]
        selected = []
        markers = (
            "error",
            "failed",
            "exception",
            "traceback",
            "assert",
            "timeout",
            "timed out",
            "exit:",
            "no such file",
            "cannot ",
            "can't ",
        )
        for line in meaningful:
            lowered = line.lower()
            if any(marker in lowered for marker in markers) and line not in selected:
                selected.append(line)
        if not selected:
            selected = meaningful[-4:]
        text = GreenfieldRecorder._redact(" | ".join(selected))
        return text if len(text) <= limit else text[: limit - 3] + "..."

    @staticmethod
    def _redact(value: object) -> str:
        text = str(value)
        text = re.sub(
            r"(?i)\b(api[_-]?key|access[_-]?token|token|password|authorization)"
            r"(\s*[=:]\s*)([^\s]+)",
            r"\1\2***",
            text,
        )
        return re.sub(r"(?i)\bBearer\s+[^\s]+", "Bearer ***", text)

    def save_wip(
        self,
        plan: SlicePlan,
        changed_files: list[str],
        workspace: Path,
    ) -> None:
        root = self.run_dir / "slices" / plan.id / "wip"
        if root.exists():
            shutil.rmtree(root)
        files_root = root / "files"
        saved = []
        deleted = []
        workspace = Path(workspace).resolve()
        for relative in changed_files:
            if self._is_runtime_wip_path(Path(relative)):
                continue
            source = workspace / relative
            try:
                source.resolve().relative_to(workspace)
            except (OSError, ValueError):
                continue
            if not source.exists():
                deleted.append(relative)
                continue
            if not source.is_file() or source.is_symlink():
                continue
            target = files_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            saved.append(relative)
        self._write_json(
            root / "manifest.json",
            {
                "plan_id": plan.id,
                "files": saved,
                "deleted": deleted,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    @staticmethod
    def _is_runtime_wip_path(path: Path) -> bool:
        if not path.parts:
            return False
        roots = {
            "tmp",
            "temp",
            ".tmp",
            ".cache",
            "cache",
            "output",
            "outputs",
            "log",
            "logs",
            ".coverage",
            "coverage",
            "htmlcov",
        }
        name = path.name.lower()
        return path.parts[0].lower() in roots or name.endswith(
            (".log", ".db", ".db-wal", ".db-shm", ".db-journal")
        )

    def restore_wip(self, plan: SlicePlan, workspace: Path) -> list[str]:
        root = self.run_dir / "slices" / plan.id / "wip"
        manifest = root / "manifest.json"
        if not manifest.exists():
            return []
        try:
            data = json.loads(manifest.read_text())
        except (OSError, json.JSONDecodeError):
            return []
        if data.get("plan_id") != plan.id:
            return []
        restored = []
        workspace = Path(workspace).resolve()
        for relative in data.get("files") or []:
            source = root / "files" / relative
            target = workspace / relative
            try:
                target.resolve().relative_to(workspace)
            except (OSError, ValueError):
                continue
            if not source.is_file():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored.append(relative)
        for relative in data.get("deleted") or []:
            target = workspace / relative
            try:
                target.resolve().relative_to(workspace)
            except (OSError, ValueError):
                continue
            if target.is_file() or target.is_symlink():
                target.unlink()
                restored.append(relative)
        return restored

    def clear_wip(self, plan: SlicePlan) -> None:
        root = self.run_dir / "slices" / plan.id / "wip"
        if root.exists():
            shutil.rmtree(root)

    def save_report(self, content: str) -> None:
        self._write_text(self.run_dir / "report.md", content)

    @staticmethod
    def load(path: Path) -> GreenfieldRun | None:
        if not path.exists():
            return None
        return GreenfieldRun.from_dict(yaml.safe_load(path.read_text()) or {})

    @staticmethod
    def _write_yaml(path: Path, data: dict) -> None:
        GreenfieldRecorder._write_text(
            path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        )

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        GreenfieldRecorder._write_text(
            path, json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        )

    @staticmethod
    def _append_jsonl(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
            temporary.replace(path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
