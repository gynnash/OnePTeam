# tests/test_harness/test_discover.py
from onep.harness.discover import BrainstormStage, PrioritizeStage
from onep.harness.models import ImprovementCandidate, QualitySnapshot


class BrainstormLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append((system_prompt, user_prompt, stage_name))
        return self.payload


def test_brainstorm_parses_candidates():
    llm = BrainstormLLM(
        '{"candidates": ['
        '{"id": "I-001", "title": "Add CLI", "description": "expose VALUE"},'
        '{"id": "I-002", "title": "Add caching", "description": "cache reads"}'
        "]}"
    )
    stage = BrainstormStage(llm)
    snapshot = QualitySnapshot(
        iteration=1, acceptance_pass_rate=1.0, test_pass_rate=1.0,
        goal_coverage=1.0, quality_score=1.0, hard_gates_passed=True,
    )
    candidates = stage.run("build value", "- REQ-1 ok", 1, snapshot)
    assert [c.id for c in candidates] == ["I-001", "I-002"]
    assert candidates[0].description == "expose VALUE"
    assert llm.calls[0][2] == "harness_brainstorm"


def test_brainstorm_handles_code_fences():
    llm = BrainstormLLM(
        '```json\n{"candidates": [{"id": "I-1", "title": "T", '
        '"description": "d"}]}\n```'
    )
    candidates = BrainstormStage(llm).run("g", "", 1, None)
    assert len(candidates) == 1
    assert candidates[0].id == "I-1"


def test_brainstorm_tolerates_garbage():
    llm = BrainstormLLM("not json at all")
    assert BrainstormStage(llm).run("g", "", 1, None) == []


def test_brainstorm_track_callback():
    tracked = []
    llm = BrainstormLLM('{"candidates": []}')

    def track(tracker, stage):
        tracked.append((tracker, stage))

    BrainstormStage(llm, track=track).run("g", "", 1, None, tracker="tracker")
    assert tracked == [("tracker", "harness_brainstorm")]


def test_prioritize_caps_backlog_and_dedupes():
    stage = PrioritizeStage(cap=2)
    # Titles must differ on >2-char tokens: PlanScheduler.fingerprint drops
    # short tokens, so "T0".."T4" would all collide and dedupe to one.
    titles = ["Add CLI", "Add caching", "Add tests", "Add docs", "Fix bugs"]
    candidates = [
        ImprovementCandidate(id=f"I-{i}", title=titles[i], description="d")
        for i in range(5)
    ]
    backlog, parked = stage.run(candidates, set())
    assert [c.id for c in backlog] == ["I-0", "I-1"]
    assert [c.id for c in parked] == ["I-2", "I-3", "I-4"]
    assert all(c.status == "backlog" for c in backlog)
    assert all(c.status == "parked" for c in parked)


def test_prioritize_skips_integrated_fingerprints():
    stage = PrioritizeStage(cap=3)
    first = ImprovementCandidate(id="I-0", title="Add CLI", description="d")
    first_backlog, _ = stage.run([first], set())
    assert first_backlog[0].fingerprint
    integrated = {first_backlog[0].fingerprint}
    duplicate = ImprovementCandidate(
        id="I-9", title="Add CLI", description="same idea again"
    )
    backlog, parked = stage.run([duplicate], integrated)
    assert backlog == []
    assert parked[0].status == "duplicate"
