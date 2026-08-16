from onep.harness.cross_project import CrossProjectDistiller
from onep.harness.vault import VaultWriter


class CrossLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append(stage_name)
        return self.payload


def test_cross_distiller_writes_global_principles_with_backlinks(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    events = [{
        "type": "insight", "iteration": 1,
        "problem": "abstraction too early hurts",
        "outcome": "delayed abstraction", "generalizable": True,
    }]
    llm = CrossLLM(
        '{"principles": [{"title": "Delay Abstraction", '
        '"summary": "Wait for the second consumer.", '
        '"tags": ["design"]}], "patterns": []}'
    )
    distiller = CrossProjectDistiller(llm, writer)
    written = distiller.run(events, "demo", "build value")
    assert written[0]["section"] == "Engineering/Principles"
    note = tmp_path / "global" / "Engineering" / "Principles" / "delay-abstraction.md"
    assert note.exists()
    text = note.read_text()
    assert "type: principle" in text
    assert "## Source" in text
    assert "[[abstraction-too-early-hurts]]" in text
    assert llm.calls == ["harness_cross_distiller"]


def test_cross_distiller_skips_without_generalizable_events(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    llm = CrossLLM('{"principles": []}')
    distiller = CrossProjectDistiller(llm, writer)
    assert distiller.run(
        [{"type": "failure", "generalizable": False}], "d", "") == []
    assert llm.calls == []


def test_cross_distiller_degrades_on_garbage(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    llm = CrossLLM("not json")
    assert CrossProjectDistiller(llm, writer).run(
        [{"type": "insight", "generalizable": True}], "d", "") == []


class RaisingCrossLLM:
    def invoke(self, system_prompt, user_prompt, stage_name):
        raise RuntimeError("cross boom")


def test_cross_distiller_llm_failure_writes_nothing(tmp_path):
    writer = VaultWriter(tmp_path / "global", tmp_path / "project")
    distiller = CrossProjectDistiller(RaisingCrossLLM(), writer)
    assert distiller.run(
        [{"type": "insight", "generalizable": True}], "d", "") == []
    assert not (tmp_path / "global" / "Engineering").exists()
