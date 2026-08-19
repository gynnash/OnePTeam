"""Knowledge views over vault directories (read-only)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from onep.harness.vault import (
    VaultWriter,
    global_vault_root,
    project_vault_root as configured_project_vault_root,
)

PROJECT_VAULT = "project"
GLOBAL_VAULT = "global"


def project_vault_root(workspace: Path) -> Path:
    return configured_project_vault_root(workspace)


def vault_root(workspace: Path, vault: str) -> Path:
    if vault == PROJECT_VAULT:
        return project_vault_root(workspace)
    if vault == GLOBAL_VAULT:
        return global_vault_root()
    raise ValueError(f"unknown vault: {vault!r}")


def parse_note(path: Path) -> dict[str, Any] | None:
    """Parse a note: frontmatter dict + markdown body."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    frontmatter: dict[str, Any] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                raw = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                raw = {}
            if isinstance(raw, dict):
                frontmatter = raw
            body = parts[2]
    return {"frontmatter": frontmatter, "body": body.strip()}


def _wikilink_slugs(body: str) -> list[str]:
    return re.findall(r"\[\[([^\]|#]+?)\]\]", body or "")


def _related_slugs(related) -> list[str]:
    out = []
    for entry in related or []:
        text = str(entry).strip()
        if text.startswith("[[") and text.endswith("]]"):
            text = text[2:-2]
        out.append(text.split("|")[0].strip())
    return out


def list_notes(workspace: Path, vault: str) -> list[dict[str, Any]]:
    root = vault_root(workspace, vault)
    notes = []
    for path in sorted(root.rglob("*.md")):
        parsed = parse_note(path)
        if parsed is None:
            continue
        relative = path.relative_to(root).as_posix()
        frontmatter = parsed["frontmatter"]
        title = ""
        for line in parsed["body"].splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        notes.append(
            {
                "id": relative,
                "vault": vault,
                "path": relative,
                "title": title or path.stem,
                "slug": path.stem,
                "type": str(frontmatter.get("type") or ""),
                "project": str(frontmatter.get("project") or ""),
                "iteration": frontmatter.get("iteration", 0),
                "tags": list(frontmatter.get("tags") or []),
                "created": str(frontmatter.get("created") or ""),
                "related": _related_slugs(frontmatter.get("related")),
            }
        )
    return notes


def note_reader(workspace: Path, vault: str, rel_path: str) -> dict[str, Any] | None:
    """Read one note, containment-safe against its vault root."""
    root = vault_root(workspace, vault).resolve(strict=False)
    try:
        resolved = (root / rel_path).resolve(strict=False)
        resolved.relative_to(root)
    except (ValueError, OSError):
        return None
    parsed = parse_note(resolved)
    if parsed is None:
        return None
    return {
        "vault": vault,
        "path": resolved.relative_to(root).as_posix(),
        "frontmatter": parsed["frontmatter"],
        "body": parsed["body"],
    }


def reasoning_graph(workspace: Path) -> dict[str, Any]:
    """Nodes = project + global notes; edges = related frontmatter + body wikilinks."""
    nodes: list[dict[str, Any]] = []
    bodies: dict[str, str] = {}
    by_slug: dict[str, str] = {}
    for vault in (PROJECT_VAULT, GLOBAL_VAULT):
        for note in list_notes(workspace, vault):
            node_id = f"{vault}:{note['id']}"
            nodes.append(
                {
                    "id": node_id,
                    "vault": vault,
                    "label": note["title"],
                    "kind": note["type"],
                    "slug": note["slug"],
                }
            )
            reader = note_reader(workspace, vault, note["path"])
            bodies[node_id] = reader["body"] if reader else ""
            if note["slug"] not in by_slug:
                by_slug[note["slug"]] = node_id
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    kinds = {node["id"]: node["kind"] for node in nodes}

    def edge_label(source: str, target: str, fallback: str) -> str:
        pair = (kinds.get(source), kinds.get(target))
        return {
            ("problem", "experiment"): "attempted_by",
            ("experiment", "failure"): "failed_as",
            ("failure", "insight"): "revealed",
            ("insight", "decision"): "informed",
            ("decision", "experiment"): "validated_by",
        }.get(pair, fallback)

    for note in list_notes(workspace, PROJECT_VAULT) + list_notes(
        workspace, GLOBAL_VAULT
    ):
        source = f"{note['vault']}:{note['id']}"
        for slug in _related_slugs(note["related"]):
            if slug in by_slug:
                target = by_slug[slug]
                key = (source, target)
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        {
                            "source": source,
                            "target": target,
                            "label": edge_label(source, target, "related"),
                        }
                    )
        for slug in _wikilink_slugs(bodies.get(source, "")):
            if slug in by_slug:
                target = by_slug[slug]
                key = (source, target)
                if key not in seen:
                    seen.add(key)
                    edges.append(
                        {
                            "source": source,
                            "target": target,
                            "label": edge_label(source, target, "wikilink"),
                        }
                    )
    return {"nodes": nodes, "edges": edges}


def articles_root() -> Path:
    return global_vault_root() / "Engineering" / "Articles"


def list_articles() -> list[dict[str, Any]]:
    root = articles_root()
    if not root.exists():
        return []
    articles = []
    for path in sorted(root.glob("*.md")):
        parsed = parse_note(path)
        frontmatter = parsed["frontmatter"] if parsed else {}
        articles.append(
            {
                "slug": path.stem,
                "title": str(frontmatter.get("title") or path.stem),
                "project": str(frontmatter.get("project") or ""),
                "iteration": frontmatter.get("iteration", 0),
                "created": str(frontmatter.get("created") or ""),
                "tags": list(frontmatter.get("tags") or []),
            }
        )
    return articles


def article_content(slug: str) -> dict[str, Any] | None:
    root = articles_root()
    safe_slug = VaultWriter.sanitize(slug)
    if safe_slug != slug:
        return None
    parsed = parse_note(root / f"{safe_slug}.md")
    if parsed is None:
        return None
    graph: dict[str, Any] = {"nodes": [], "edges": []}
    graph_path = root / f"{safe_slug}.graph.json"
    if graph_path.exists():
        try:
            raw = json.loads(graph_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                graph = raw
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "slug": slug,
        "frontmatter": parsed["frontmatter"],
        "title": str(parsed["frontmatter"].get("title") or slug),
        "markdown": parsed["body"],
        "graph": graph,
    }
