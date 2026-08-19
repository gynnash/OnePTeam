"""Two-layer Obsidian vault writer: global + project, plain Markdown."""

from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Any

import yaml

PROJECT_SECTIONS = {
    "Sessions",
    "Decisions",
    "Experiments",
    "Failures",
    "Insights",
}

_SECTION_TO_FOLDER = {
    "problem": "Sessions",
    "decision": "Decisions",
    "experiment": "Experiments",
    "failure": "Failures",
    "discovery": "Insights",
    "insight": "Insights",
}


def section_for_type(event_type: str) -> str:
    return _SECTION_TO_FOLDER.get(str(event_type).lower(), "Sessions")


def _config_path() -> Path:
    return Path.home() / ".onep" / "config.yaml"


def global_vault_root() -> Path:
    """Global vault root: config.yaml `knowledge.vault_root`, else ~/.onep/vault."""
    try:
        raw = yaml.safe_load(_config_path().read_text(encoding="utf-8")) or {}
        root = str((raw.get("knowledge") or {}).get("vault_root") or "").strip()
        if root:
            return Path(root).expanduser()
    except (OSError, yaml.YAMLError, AttributeError, TypeError):
        pass
    return Path.home() / ".onep" / "vault"


def project_vault_root(workspace: Path) -> Path:
    """Per-project override from .onep/config.yaml, else the local default."""
    workspace = Path(workspace).resolve()
    path = workspace / ".onep" / "config.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        configured = str(
            (raw.get("knowledge") or {}).get("project_vault_root") or ""
        ).strip()
        if configured:
            candidate = Path(configured).expanduser()
            return (
                (workspace / candidate).resolve()
                if not candidate.is_absolute()
                else candidate.resolve()
            )
    except (OSError, yaml.YAMLError, AttributeError, TypeError):
        pass
    return workspace / ".onep" / "knowledge"


class VaultWriter:
    """Filesystem-safe Markdown writes for both Obsidian vault layers.

    Project notes go under `project_root` (Sessions/Decisions/Experiments/
    Failures/Insights + Project.md MOC); global notes go under `global_root`
    (Engineering/Principles, Engineering/Patterns, Engineering/Articles).
    """

    def __init__(self, global_root: Path, project_root: Path | None = None) -> None:
        self.global_root = Path(global_root).resolve()
        self.project_root = Path(project_root).resolve() if project_root else None

    @staticmethod
    def sanitize(title: str) -> str:
        text = " ".join(str(title or "").split()).lower()
        # ``\w`` is Unicode-aware in Python, so CJK and other letter/digit
        # titles remain distinct instead of all collapsing to ``note.md``.
        # Path separators and punctuation are still replaced.
        slug = re.sub(r"[^\w.-]+", "-", text, flags=re.UNICODE)
        slug = slug.strip(".-_")[:80]
        return slug or "note"

    @staticmethod
    def render_frontmatter(frontmatter: dict[str, Any]) -> str:
        return (
            "---\n"
            + yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).rstrip()
            + "\n---\n"
        )

    @staticmethod
    def event_note_title(event: dict[str, Any]) -> str:
        raw = (
            event.get("problem")
            or event.get("selected")
            or event.get("outcome")
            or event.get("type")
            or "note"
        )
        return " ".join(str(raw).split())[:80]

    @classmethod
    def event_note_slug(cls, event: dict[str, Any]) -> str:
        identity = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str)
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
        prefix = f"{int(event.get('iteration') or 0)}-{event.get('type') or 'note'}"
        return cls.sanitize(f"{prefix}-{cls.event_note_title(event)}-{digest}")

    def _resolve_section(self, section: str) -> Path:
        section = str(section).strip("/")
        if section == "Project":
            if self.project_root is None:
                raise ValueError("project vault root is not configured")
            return self.project_root
        if section in PROJECT_SECTIONS:
            if self.project_root is None:
                raise ValueError("project vault root is not configured")
            root = self.project_root
        else:
            root = self.global_root
        resolved = (root / section).resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"section escapes vault root: {section!r}") from exc
        return resolved

    def note_path(self, section: str, slug: str) -> Path:
        slug = self.sanitize(slug)
        return self._resolve_section(section) / f"{slug}.md"

    def write_note(
        self,
        section: str,
        slug: str,
        frontmatter: dict[str, Any],
        body: str,
    ) -> Path:
        path = self.note_path(section, slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.render_frontmatter(frontmatter) + "\n" + str(body).strip() + "\n"
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, section: str, filename: str, data: dict[str, Any]) -> Path:
        directory = self._resolve_section(section)
        safe_name = self.sanitize(Path(str(filename)).name)
        if not safe_name.endswith(".json"):
            safe_name += ".json"
        path = directory / safe_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    def write_event_note(
        self,
        event: dict[str, Any],
        project: str,
        iteration: int,
        related: list[str] | None = None,
    ) -> Path:
        slug = self.event_note_slug(event)
        frontmatter = {
            "type": str(event.get("type") or ""),
            "project": project,
            "iteration": int(event.get("iteration") or iteration),
            "tags": [project, str(event.get("type") or "")],
            "created": str(event.get("created_at") or ""),
            "related": [f"[[{slug}]]" for slug in related or []],
        }
        body = [
            f"# {self.event_note_title(event)}",
            "",
            f"- Type: {frontmatter['type']}",
            f"- Iteration: {frontmatter['iteration']}",
            f"- Generalizable: {event.get('generalizable', False)}",
        ]
        if event.get("problem"):
            body.append(f"\n## Problem\n\n{event['problem']}")
        if event.get("options"):
            body.append(
                "\n## Options\n\n" + "\n".join(f"- {opt}" for opt in event["options"])
            )
        if event.get("selected"):
            body.append(f"\n## Selected\n\n{event['selected']}")
        if event.get("reason"):
            body.append(f"\n## Reason\n\n{event['reason']}")
        if event.get("evidence"):
            body.append(f"\n## Evidence\n\n{event['evidence']}")
        if event.get("outcome"):
            body.append(f"\n## Outcome\n\n{event['outcome']}")
        if event.get("files"):
            body.append(
                "\n## Files\n\n" + "\n".join(f"- `{f}`" for f in event["files"])
            )
        section = section_for_type(str(event.get("type") or ""))
        return self.write_note(section, slug, frontmatter, "\n".join(body))

    def write_project_moc(
        self,
        project: str,
        goal: str,
        status: str,
        events: list[dict[str, Any]],
        architecture: str = "",
    ) -> Path:
        if self.project_root is None:
            raise ValueError("project vault root is not configured")
        by_section: dict[str, list[dict[str, Any]]] = {
            section: [] for section in sorted(PROJECT_SECTIONS)
        }
        seen: set[str] = set()
        for event in events:
            slug = self.event_note_slug(event)
            if slug in seen:
                continue
            seen.add(slug)
            by_section[section_for_type(str(event.get("type") or ""))].append(event)
        lines = [
            f"# {project}",
            "",
            f"- Goal: {goal or '(none)'}",
            f"- Status: {status or 'unknown'}",
            f"- Architecture: {architecture or '(none)'}",
            f"- Knowledge events: {len(events)}",
        ]
        for section in sorted(PROJECT_SECTIONS):
            entries = by_section[section]
            if not entries:
                continue
            lines.append(f"\n## {section}\n")
            for event in entries:
                lines.append(f"- [[{self.event_note_slug(event)}]]")
        body = "\n".join(lines) + "\n"
        frontmatter = {
            "type": "project",
            "project": project,
            "iteration": 0,
            "tags": [project, "moc"],
            "created": "",
            "related": [],
            "architecture": architecture,
        }
        path = self.project_root / "Project.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.render_frontmatter(frontmatter) + "\n" + body,
            encoding="utf-8",
        )
        return path
