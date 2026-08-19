"""Article Synthesizer: reconstruct a project's reasoning journey as an article."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from onep.harness.discover import _json_object
from onep.harness.knowledge_models import (
    load_distillations,
    load_jsonl,
)
from onep.harness.vault import VaultWriter

ARTICLE_SYSTEM = (
    "You are the Article Synthesizer for an autonomous development harness. "
    "You reconstruct the intellectual journey of a development project as a "
    "reasoning-organized narrative with decision-chain citations. "
    "Return JSON only."
)

EXTRACT_PROMPT = """Extract the significant development events from these
inputs, discarding operational noise.

Inputs (JSON):
{inputs}

Return JSON only:
{{"events": [{{"id": "e1", "type": "problem|decision|experiment|failure|discovery|insight",
"problem": "...", "selected": "...", "reason": "...", "evidence": "...",
"iteration": 1}}]}}
Emit at most 12 events; keep the events that shaped the outcome."""

CLUSTER_PROMPT = """Cluster the extracted events into problems.
Events (JSON):
{events}

Return JSON only:
{{"clusters": [{{"problem": "the problem statement", "event_ids": ["e1", "e3"],
"resolution": "how it was resolved"}}]}}"""

GRAPH_PROMPT = """Build the decision graph for this project.
Clusters (JSON):
{clusters}

Return JSON only:
{{"nodes": [{{"id": "n1", "label": "event or problem label",
"kind": "problem|decision|experiment|failure|insight"}}],
"edges": [{{"source": "n1", "target": "n2", "label": "caused|led_to|rejected|adopted"}}]}}"""

INSIGHT_PROMPT = """Extract the transferable insights from the project.
Inputs (JSON):
{inputs}
Decision graph (JSON):
{graph}

Return JSON only:
{{"insights": [{{"title": "...", "summary": "...",
"evidence": "which event or outcome supports this"}}]}}
Emit at most 4 insights."""

NARRATIVE_PROMPT = """Write the final article.

Project: {project}
Goal: {goal}
Quality curve: {quality}
Stop evidence: {stop}
Decision graph (JSON):
{graph}
Insights (JSON):
{insights}
Available knowledge-note citations (JSON):
{citations}

The article MUST NOT be chronological. Organize it by reasoning:
belief -> test -> failure -> discovery -> revision. Use these section types:
1. The Goal
2. What We Initially Believed
3. Where Beliefs Failed (cite the failing experiments/failures)
4. Decisions That Shaped the Outcome (cite each decision)
5. What We Learned (insights)

Cite decisions by their [[wikilink]] slugs so the reasoning graph stays
connected. Only use wikilinks from the available citation list. Timeline is
evidence only, never structure.

Return JSON only:
{{"title": "article title",
"markdown": "full markdown article with # headings and [[wikilinks]]"}}"""


class ArticleSynthesizer:
    """Reconstructs the project's reasoning journey as a narrative article."""

    def __init__(
        self,
        llm,
        writer: VaultWriter,
        track: Callable[[Any, str], None] | None = None,
    ) -> None:
        self.llm = llm
        self.writer = writer
        self.track = track

    def collect_inputs(
        self,
        workspace: Path,
        run_dir: Path,
        run,
    ) -> dict[str, Any]:
        workspace = Path(workspace)
        run_dir = Path(run_dir)
        git_history = ""
        try:
            import git

            git_history = git.Repo(workspace).git.log("--oneline", "-n", "50")
        except Exception:
            git_history = ""
        distilled = [event.to_dict() for event in load_distillations(run_dir)]
        for event in distilled:
            event["wikilink"] = VaultWriter.event_note_slug(event)
        architecture_versions = load_jsonl(run_dir / "architecture-decisions.jsonl")
        if not architecture_versions and run.architecture:
            architecture_versions = [dict(run.architecture)]
        return {
            "project_name": run.project_name,
            "original_goal": run.original_goal,
            "iteration": run.iteration,
            "requirement_evolution": [item.to_dict() for item in run.work_items],
            "architecture_versions": architecture_versions,
            "decisions": [e for e in distilled if e.get("type") == "decision"],
            "experiments": [e for e in distilled if e.get("type") == "experiment"],
            "failures": [e for e in distilled if e.get("type") == "failure"],
            "insights": [e for e in distilled if e.get("type") == "insight"],
            "discoveries": [e for e in distilled if e.get("type") == "discovery"],
            "git_history": git_history,
            "quality_curve": [
                {
                    "iteration": snap.iteration,
                    "quality_score": snap.quality_score,
                }
                for snap in run.quality_history
            ],
            "stop_evidence": run.stop_state,
            "stop_reason": run.stop_state.get("reason", ""),
        }

    def _invoke(self, stage: str, prompt: str, tracker) -> dict:
        try:
            output = self.llm.invoke(
                system_prompt=ARTICLE_SYSTEM,
                user_prompt=prompt,
                stage_name=stage,
            )
        except Exception:
            # Advisory: an LLM failure degrades to empty output, so the
            # stage-level empty handling (and the deterministic narrative
            # fallback) takes over instead of aborting synthesis.
            return {}
        if self.track is not None and tracker is not None:
            self.track(tracker, stage)
        return _json_object(output or "")

    def _extract_events(
        self,
        inputs: dict[str, Any],
        tracker=None,
    ) -> list[dict[str, Any]]:
        data = self._invoke(
            "harness_article_extract",
            EXTRACT_PROMPT.format(
                inputs=json.dumps(inputs, ensure_ascii=False, indent=2, default=str),
            ),
            tracker,
        )
        return [event for event in data.get("events") or [] if isinstance(event, dict)]

    def _cluster_problems(
        self,
        events: list[dict[str, Any]],
        tracker=None,
    ) -> list[dict[str, Any]]:
        if not events:
            return []
        data = self._invoke(
            "harness_article_cluster",
            CLUSTER_PROMPT.format(
                events=json.dumps(events, ensure_ascii=False, indent=2),
            ),
            tracker,
        )
        return [
            cluster
            for cluster in data.get("clusters") or []
            if isinstance(cluster, dict)
        ]

    def _decision_graph(
        self,
        clusters: list[dict[str, Any]],
        events: list[dict[str, Any]],
        tracker=None,
    ) -> dict[str, Any]:
        if not clusters:
            return {"nodes": [], "edges": []}
        data = self._invoke(
            "harness_article_graph",
            GRAPH_PROMPT.format(
                clusters=json.dumps(clusters, ensure_ascii=False, indent=2),
            ),
            tracker,
        )
        return self._validate_graph(
            {
                "nodes": [
                    node for node in data.get("nodes") or [] if isinstance(node, dict)
                ],
                "edges": [
                    edge for edge in data.get("edges") or [] if isinstance(edge, dict)
                ],
            }
        )

    @staticmethod
    def _validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
        nodes = []
        node_ids = set()
        for node in graph.get("nodes") or []:
            node_id = str(node.get("id") or "").strip()
            if not node_id or node_id in node_ids:
                continue
            node_ids.add(node_id)
            nodes.append({**node, "id": node_id})
        edges = []
        for edge in graph.get("edges") or []:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            if source in node_ids and target in node_ids:
                edges.append({**edge, "source": source, "target": target})
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _validate_markdown(markdown: str, inputs: dict[str, Any]) -> str:
        allowed = {
            event["wikilink"]
            for kind in (
                "decisions",
                "experiments",
                "failures",
                "insights",
                "discoveries",
            )
            for event in inputs.get(kind) or []
            if event.get("wikilink")
        }

        def replace(match):
            target, _, label = match.group(1).partition("|")
            return match.group(0) if target in allowed else (label or target)

        return re.sub(r"\[\[([^\]]+)\]\]", replace, markdown)

    def _extract_insights(
        self,
        inputs: dict[str, Any],
        events: list[dict[str, Any]],
        clusters: list[dict[str, Any]],
        graph: dict[str, Any],
        tracker=None,
    ) -> list[dict[str, Any]]:
        if (
            not events
            and not clusters
            and not graph.get("nodes")
            and not graph.get("edges")
        ):
            return []
        data = self._invoke(
            "harness_article_insight",
            INSIGHT_PROMPT.format(
                inputs=json.dumps(inputs, ensure_ascii=False, indent=2, default=str),
                graph=json.dumps(graph, ensure_ascii=False, indent=2),
            ),
            tracker,
        )
        return [
            insight
            for insight in data.get("insights") or []
            if isinstance(insight, dict)
        ]

    def _narrative(
        self,
        inputs: dict[str, Any],
        graph: dict[str, Any],
        insights: list[dict[str, Any]],
        tracker=None,
    ) -> dict[str, Any]:
        data = self._invoke(
            "harness_article_narrative",
            NARRATIVE_PROMPT.format(
                project=inputs["project_name"],
                goal=inputs["original_goal"] or "(none)",
                quality=json.dumps(inputs["quality_curve"], ensure_ascii=False),
                stop=json.dumps(inputs["stop_evidence"], ensure_ascii=False),
                graph=json.dumps(graph, ensure_ascii=False, indent=2),
                insights=json.dumps(insights, ensure_ascii=False, indent=2),
                citations=json.dumps(
                    sorted(
                        {
                            event["wikilink"]
                            for kind in (
                                "decisions",
                                "experiments",
                                "failures",
                                "insights",
                                "discoveries",
                            )
                            for event in inputs.get(kind) or []
                            if event.get("wikilink")
                        }
                    ),
                    ensure_ascii=False,
                ),
            ),
            tracker,
        )
        markdown = str(data.get("markdown") or "")
        if not markdown:
            return {}
        return {
            "title": str(data.get("title") or inputs["project_name"]),
            "markdown": markdown,
        }

    def _fallback_narrative(self, inputs: dict[str, Any]) -> dict[str, Any]:
        lines = [
            f"# {inputs['project_name']}",
            "",
            "## The Goal",
            "",
            inputs["original_goal"] or "(no goal recorded)",
            "",
            "## What We Initially Believed",
            "",
            "The initial architecture and acceptance plan represented the first "
            "working hypothesis.",
        ]
        failures = inputs.get("failures") or []
        lines += ["", "## Where Beliefs Failed", ""]
        if failures:
            for event in failures[:8]:
                link = event.get("wikilink") or VaultWriter.event_note_slug(event)
                lines.append(
                    f"- [[{link}]] — {event.get('problem') or event.get('reason') or 'failure'}"
                )
        else:
            lines.append("No distilled failure evidence was recorded.")
        decisions = inputs.get("decisions") or []
        lines += ["", "## Decisions That Shaped the Outcome", ""]
        if decisions:
            for event in decisions[:8]:
                link = event.get("wikilink") or VaultWriter.event_note_slug(event)
                lines.append(
                    f"- [[{link}]] — {event.get('selected') or event.get('problem') or 'decision'}"
                )
        else:
            lines.append("No distilled decision evidence was recorded.")
        insights = inputs.get("insights") or []
        lines += ["", "## What We Learned", ""]
        if insights:
            for event in insights[:8]:
                link = event.get("wikilink") or VaultWriter.event_note_slug(event)
                lines.append(
                    f"- [[{link}]] — {event.get('outcome') or event.get('problem') or 'insight'}"
                )
        else:
            lines.append(
                "The available evidence does not support a durable insight yet."
            )
        quality = inputs["quality_curve"]
        if quality:
            lines += ["", "## Quality Curve", ""]
            for point in quality:
                lines.append(
                    f"- iteration {point.get('iteration')}: "
                    f"score {point.get('quality_score')}"
                )
        if inputs.get("git_history"):
            lines += ["", "## Supporting Evidence", "", "```text"]
            lines.extend(str(inputs["git_history"]).splitlines()[:20])
            lines.append("```")
        lines += [
            "",
            "## Why the Harness Stopped",
            "",
            inputs["stop_reason"] or "unknown",
        ]
        return {
            "title": f"{inputs['project_name']} — Development Journey",
            "markdown": "\n".join(lines),
        }

    def synthesize(
        self,
        workspace: Path,
        run_dir: Path,
        run,
        tracker=None,
    ) -> dict[str, Any]:
        inputs = self.collect_inputs(workspace, run_dir, run)
        events = self._extract_events(inputs, tracker)
        clusters = self._cluster_problems(events, tracker)
        graph = self._decision_graph(clusters, events, tracker)
        insights = self._extract_insights(inputs, events, clusters, graph, tracker)
        narrative = self._narrative(inputs, graph, insights, tracker)
        if not narrative:
            narrative = self._fallback_narrative(inputs)
        narrative["markdown"] = self._validate_markdown(narrative["markdown"], inputs)
        slug = self.writer.sanitize(f"{run.project_name}-article")
        created = datetime.now(timezone.utc).isoformat()
        frontmatter = {
            "type": "article",
            "title": narrative["title"],
            "project": run.project_name,
            "iteration": run.iteration,
            "tags": [run.project_name, "article"],
            "created": created,
            "related": [],
        }
        article_path = self.writer.write_note(
            "Engineering/Articles",
            slug,
            frontmatter,
            narrative["markdown"],
        )
        graph_path = self.writer.write_json(
            "Engineering/Articles",
            f"{slug}.graph.json",
            graph,
        )
        return {
            "article_path": article_path,
            "graph_path": graph_path,
            "title": narrative["title"],
            "markdown": narrative["markdown"],
            "graph": graph,
        }
