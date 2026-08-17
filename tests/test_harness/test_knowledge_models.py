from onep.harness.knowledge_models import (
    KnowledgeEvent, KnowledgeEventType, distillations_path, load_distillations,
    load_jsonl, load_run_events, save_distillations,
)


def test_knowledge_event_round_trip():
    event = KnowledgeEvent(
        type="decision", iteration=2, problem="how to wire",
        options=["flat", "nested"], selected="flat", reason="simpler",
        evidence="gate passed", files=["app.py"], outcome="accepted",
        generalizable=True,
    )
    restored = KnowledgeEvent.from_dict(event.to_dict())
    assert restored.type == "decision"
    assert restored.iteration == 2
    assert restored.options == ["flat", "nested"]
    assert restored.selected == "flat"
    assert restored.generalizable is True
    assert restored.created_at == event.created_at


def test_knowledge_event_from_dict_tolerates_missing_fields():
    restored = KnowledgeEvent.from_dict({"type": "failure"})
    assert restored.iteration == 0
    assert restored.options == []
    assert restored.files == []
    assert restored.generalizable is False


def test_event_type_enum_values():
    assert KnowledgeEventType.DECISION.value == "decision"
    assert KnowledgeEventType.INSIGHT.value == "insight"
    assert KnowledgeEventType.FAILURE.value == "failure"


def test_save_and_load_distillations_appends(tmp_path):
    run_dir = tmp_path / "runs" / "r-1"
    save_distillations(run_dir, [
        KnowledgeEvent(type="decision", iteration=1, problem="how to wire"),
    ])
    save_distillations(run_dir, [
        KnowledgeEvent(type="failure", iteration=1, problem="gate failed"),
    ])
    loaded = load_distillations(run_dir)
    assert [event.type for event in loaded] == ["decision", "failure"]
    assert loaded[0].problem == "how to wire"
    assert distillations_path(run_dir) == run_dir / "distillations.jsonl"


def test_load_distillations_missing_dir_returns_empty(tmp_path):
    assert load_distillations(tmp_path / "nope") == []


def test_load_run_events_parses_events_jsonl(tmp_path):
    run_dir = tmp_path / "runs" / "r-1"
    path = run_dir / "events.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"type": "trace", "payload": {"label": "SLICE"}}\n'
        "not json\n"
        '{"type": "repair_brief", "payload": {}}\n'
    )
    events = load_run_events(run_dir)
    assert [event["type"] for event in events] == ["trace", "repair_brief"]


def test_load_run_events_missing_file_returns_empty(tmp_path):
    assert load_run_events(tmp_path / "nope") == []


def test_load_jsonl_missing_file_returns_empty(tmp_path):
    assert load_jsonl(tmp_path / "missing.jsonl") == []
