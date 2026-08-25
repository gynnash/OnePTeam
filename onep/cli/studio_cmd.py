"""Small CLI companion for the Web-first Product Studio."""

from __future__ import annotations

import json
from pathlib import Path

import click


def _service():
    from onep.studio import StudioService

    return StudioService()


def _print(value) -> None:
    click.echo(json.dumps(value, ensure_ascii=False, indent=2, default=str))


@click.group(name="project")
def project_group():
    """Define and deliver Product Studio projects."""


@project_group.command(name="new")
@click.option("--idea", required=True, help="One-sentence product idea")
@click.option("--repo", default="", help="Existing repository or future workspace path")
@click.option("--name", default="")
def project_new(idea: str, repo: str, name: str):
    _print(_service().create_project({"idea": idea, "repo": repo, "name": name}))


@project_group.command(name="show")
@click.argument("project_id")
def project_show(project_id: str):
    _print(_service().studio(project_id))


@project_group.command(name="answer")
@click.argument("project_id")
@click.option(
    "--answer", "answers", multiple=True, required=True, help="QUESTION_ID=answer"
)
def project_answer(project_id: str, answers: tuple[str, ...]):
    parsed = []
    for value in answers:
        question_id, separator, answer = value.partition("=")
        if not separator or not question_id.strip() or not answer.strip():
            raise click.ClickException("--answer must be QUESTION_ID=answer")
        parsed.append({"question_id": question_id.strip(), "answer": answer.strip()})
    _print(_service().answer_discovery(project_id, {"answers": parsed}))


@project_group.command(name="discovery-decision")
@click.argument("project_id")
@click.option(
    "--action",
    required=True,
    type=click.Choice(["continue", "accept-recommendations", "draft-with-assumptions"]),
)
@click.option("--reason", default="")
def project_discovery_decision(project_id: str, action: str, reason: str):
    mapped = action.replace("-", "_")
    _print(
        _service().decide_discovery(project_id, {"action": mapped, "reason": reason})
    )


@project_group.command(name="approve-prd")
@click.argument("project_id")
@click.option("--version", required=True, type=int)
@click.option("--feature", "features", multiple=True)
@click.option("--reason", default="")
def approve_prd(project_id: str, version: int, features: tuple[str, ...], reason: str):
    service = _service()
    approved = service.approve_prd(
        project_id, version, {"feature_ids": list(features), "reason": reason}
    )
    from onep.studio.execution import StudioExecutionService

    delivery = StudioExecutionService(service.store).execute_project(project_id)
    _print({**approved, "delivery": delivery})


@project_group.command(name="strategy")
@click.argument("project_id")
@click.argument("feature_id")
@click.option(
    "--mode",
    required=True,
    type=click.Choice(["auto", "direct", "plan", "goal", "plan-goal"]),
)
@click.option("--reason", default="CLI user override")
def project_strategy(project_id: str, feature_id: str, mode: str, reason: str):
    mapped = {
        "auto": "auto",
        "direct": "direct",
        "plan": "plan_then_execute",
        "goal": "goal",
        "plan-goal": "plan_then_goal",
    }[mode]
    _print(
        _service().set_feature_strategy(
            project_id, feature_id, {"strategy": mapped, "reason": reason}
        )
    )


def _state_command(name: str):
    @click.command(name=name)
    @click.argument("project_id")
    def command(project_id: str):
        _print({"project": _service().set_project_state(project_id, name)})

    return command


for _command in (
    _state_command("pause"),
    _state_command("resume"),
    _state_command("stop"),
):
    project_group.add_command(_command)


@click.group(name="knowledge")
def knowledge_group():
    """Search the reusable engineering knowledge ledger."""


@knowledge_group.command(name="search")
@click.argument("query")
@click.option("--limit", type=click.IntRange(1, 50), default=10)
def knowledge_search(query: str, limit: int):
    _print({"records": _service().knowledge.search(query, limit=limit)})


@click.group(name="article")
def article_group():
    """Inspect and export Article Studio drafts."""


@article_group.command(name="list")
def article_list():
    _print({"articles": _service().store.articles()})


@article_group.command(name="show")
@click.argument("article_id")
def article_show(article_id: str):
    _print(_service().store.get_article(article_id))


@article_group.command(name="export")
@click.argument("article_id")
@click.option("--platform", type=click.Choice(["long", "short"]), default="long")
@click.option(
    "--format",
    "format_name",
    type=click.Choice(["markdown", "html", "text"]),
    default="markdown",
)
@click.option("--output", type=click.Path(path_type=Path), default=None)
def article_export(
    article_id: str, platform: str, format_name: str, output: Path | None
):
    result = _service().articles.export(article_id, platform, format_name)
    target = output or Path(result["filename"])
    target.write_text(result["content"], encoding="utf-8")
    click.echo(str(target.resolve()))


COMMANDS = [project_group, knowledge_group, article_group]
