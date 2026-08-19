# tests/test_harness/test_research.py
from pathlib import Path

from onep.harness.github_client import GitHubUnavailable, RepoInfo
from onep.harness.research import ResearchStage


class FakeClient:
    def __init__(self, repos, readmes):
        self.repos = repos
        self.readmes = readmes
        self.searches = []
        self.readme_calls = []

    def search_repos(self, query, max_results=10):
        self.searches.append(query)
        return [repo for repo in self.repos if query.split()[0] in repo.full_name]

    def filter_repos(self, repos, max_repos=3, min_stars=100, max_age_days=730):
        return repos[:max_repos]

    def fetch_readme(self, full_name, max_chars=8000):
        self.readme_calls.append(full_name)
        return self.readmes.get(full_name, "")

    def fetch_top_tree(self, full_name, max_entries=30):
        return ["src", "src/parse.py", "README.md"]

    def fetch_file(self, full_name, path, max_chars=6000):
        return "def parse(value):\n    return value\n"


class ScriptedLLM:
    """Returns responses per stage; research makes 3 calls in full mode."""

    def __init__(self, questions, cards, synthesis):
        self.questions = questions
        self.cards = cards
        self.synthesis = synthesis
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append(stage_name)
        if len(self.calls) == 1:
            return self.questions
        if len(self.calls) == 2:
            return self.cards
        return self.synthesis


CARDS = (
    '{"cards": [{"repo": "cli/repo", "pattern": "builder", '
    '"module_boundaries": ["parse"], "data_flow": "in -> out", '
    '"evidence_files": ["src/parse.py"], "strengths": ["clean"], '
    '"weaknesses": ["slow"]}]}'
)
SYNTHESIS = (
    '{"evidence": [{"claim": "builders win", '
    '"source_repos": ["cli/repo"], "detail": "scale fits"}], '
    '"tradeoffs": [{"option": "builder", "decision": "adopt", '
    '"reason": "fits", "source_repos": ["cli/repo"]}]}'
)


def _stage(llm, client=None):
    return ResearchStage(llm, client=client or FakeClient([], {}))


def test_full_mode_searches_extracts_and_synthesizes(tmp_path):
    client = FakeClient(
        [
            RepoInfo(
                full_name="cli/repo",
                stargazers_count=900,
                pushed_at="2026-06-01T00:00:00Z",
            )
        ],
        {"cli/repo": "# great cli\n"},
    )
    llm = ScriptedLLM('{"questions": ["cli orchestration patterns"]}', CARDS, SYNTHESIS)
    report = _stage(llm, client=client).run(
        goal="build a CLI",
        acceptance_summary="- REQ-1 ok",
        architecture_summary="selected: python",
        iteration=1,
        run_dir=tmp_path / "runs" / "r-1",
    )
    assert report.mode == "full"
    assert report.questions == ["cli orchestration patterns"]
    assert report.cards[0].repo == "cli/repo"
    assert report.cards[0].pattern == "builder"
    assert report.evidence[0].claim == "builders win"
    assert report.tradeoffs[0].decision == "adopt"
    assert client.searches == ["cli orchestration patterns"]
    assert client.readme_calls == ["cli/repo"]
    assert llm.calls == ["harness_researcher"] * 3
    assert (tmp_path / "runs" / "r-1" / "research-reports.jsonl").exists()


def test_full_mode_skips_without_questions(tmp_path):
    llm = ScriptedLLM('{"questions": []}', "", "")
    client = FakeClient(
        [
            RepoInfo(
                full_name="cli/repo",
                stargazers_count=1,
                pushed_at="2026-06-01T00:00:00Z",
            )
        ],
        {},
    )
    report = _stage(llm, client=client).run("g", "", "", 1, tmp_path / "runs" / "r-1")
    assert report.mode == "skipped"
    assert report.skip_reason == "no_research_questions"
    assert client.searches == []


def test_full_mode_skips_without_repos(tmp_path):
    llm = ScriptedLLM('{"questions": ["q"]}', "", "")
    client = FakeClient([], {})
    report = _stage(llm, client=client).run("g", "", "", 1, tmp_path / "runs" / "r-1")
    assert report.mode == "skipped"
    assert report.skip_reason == "no_matching_repositories"


def test_full_mode_degrades_to_skipped_on_github_unavailable(tmp_path):
    class FailingClient:
        def search_repos(self, query, max_results=10):
            raise GitHubUnavailable("HTTP 403")

    llm = ScriptedLLM('{"questions": ["q"]}', "", "")
    report = _stage(llm, client=FailingClient()).run(
        "g", "", "", 1, tmp_path / "runs" / "r-1"
    )
    assert report.mode == "skipped"
    assert "GitHubUnavailable" in report.skip_reason


def test_lightweight_mode_skips_network_and_uses_local_evidence(tmp_path):
    llm = ScriptedLLM(SYNTHESIS, "", "")
    client = FakeClient(
        [
            RepoInfo(
                full_name="x/y", stargazers_count=1, pushed_at="2026-06-01T00:00:00Z"
            )
        ],
        {},
    )
    report = _stage(llm, client=client).run(
        "g",
        "",
        "selected: python",
        2,
        tmp_path / "runs" / "r-1",
        mode="lightweight",
    )
    assert report.mode == "lightweight"
    assert client.searches == []
    assert report.evidence[0].claim == "builders win"
    assert len(llm.calls) == 1


def test_lightweight_mode_without_evidence_is_skipped(tmp_path):
    llm = ScriptedLLM('{"evidence": []}', "", "")
    report = _stage(llm, client=FakeClient([], {})).run(
        "g", "", "", 2, tmp_path / "runs" / "r-1", mode="lightweight"
    )
    assert report.mode == "skipped"
    assert report.skip_reason == "lightweight_no_evidence"


def test_auto_mode_resolves_by_iteration(tmp_path):
    llm = ScriptedLLM('{"questions": []}', "", "")
    stage = _stage(llm)
    stage._resolve_mode("auto", 1)
    assert stage._last_mode == "full"
    stage._resolve_mode("auto", 3)
    assert stage._last_mode == "lightweight"


def test_track_callback_fires_after_run(tmp_path):
    tracked = []
    llm = ScriptedLLM('{"questions": []}', "", "")

    def track(tracker, stage):
        tracked.append((tracker, stage))

    stage = ResearchStage(llm, client=FakeClient([], {}), track=track)
    stage.run("g", "", "", 1, tmp_path / "runs" / "r-1", tracker="the-tracker")
    assert tracked == [("the-tracker", "harness_researcher")]


def test_full_mode_skips_with_readme_fetch_failed(tmp_path):
    class FailingReadmeClient(FakeClient):
        def fetch_readme(self, full_name, max_chars=8000):
            self.readme_calls.append(full_name)
            raise GitHubUnavailable("HTTP 404")

    llm = ScriptedLLM('{"questions": ["cli orchestration patterns"]}', "", "")
    client = FailingReadmeClient(
        [
            RepoInfo(
                full_name="cli/repo",
                stargazers_count=900,
                pushed_at="2026-06-01T00:00:00Z",
            )
        ],
        {},
    )
    report = _stage(llm, client=client).run("g", "", "", 1, tmp_path / "runs" / "r-1")
    assert report.mode == "skipped"
    assert report.skip_reason == "readme_fetch_failed"


def test_lightweight_evidence_strips_invented_source_repos(tmp_path):
    llm = ScriptedLLM(SYNTHESIS, "", "")
    report = _stage(llm, client=FakeClient([], {})).run(
        "g",
        "",
        "selected: python",
        2,
        tmp_path / "runs" / "r-1",
        mode="lightweight",
    )
    assert report.evidence[0].source_repos == []


def test_full_mode_evidence_filters_invented_source_repos(tmp_path):
    client = FakeClient(
        [
            RepoInfo(
                full_name="cli/repo",
                stargazers_count=900,
                pushed_at="2026-06-01T00:00:00Z",
            )
        ],
        {"cli/repo": "# great cli\n"},
    )
    synthesis = (
        '{"evidence": [{"claim": "builders win", '
        '"source_repos": ["cli/repo", "ghost/repo"], '
        '"detail": "scale fits"}], '
        '"tradeoffs": [{"option": "builder", "decision": "adopt", '
        '"reason": "fits", "source_repos": ["cli/repo"]}]}'
    )
    llm = ScriptedLLM('{"questions": ["cli orchestration patterns"]}', CARDS, synthesis)
    report = _stage(llm, client=client).run(
        goal="build a CLI",
        acceptance_summary="- REQ-1 ok",
        architecture_summary="selected: python",
        iteration=1,
        run_dir=tmp_path / "runs" / "r-1",
    )
    assert report.mode == "full"
    assert report.evidence[0].source_repos == ["cli/repo"]
