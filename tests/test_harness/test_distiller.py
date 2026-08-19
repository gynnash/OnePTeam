from onep.harness.distiller import KnowledgeDistiller


class DistillLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append((system_prompt, user_prompt, stage_name))
        return self.payload


EVENTS_PAYLOAD = (
    '{"events": ['
    '{"type": "failure", "problem": "gate kept failing", '
    '"reason": "race in setup", "evidence": "3 retries", '
    '"files": ["tests/conftest.py"], "generalizable": true},'
    '{"type": "insight", "problem": "reset state between tests", '
    '"outcome": "use a fixture", "generalizable": true}]}'
)


def test_distill_parses_structured_events():
    llm = DistillLLM(EVENTS_PAYLOAD)
    events = KnowledgeDistiller(llm).distill(
        [{"type": "trace", "payload": {"message": "noise"}}],
        "round_end",
        2,
    )
    assert [event.type for event in events] == ["failure", "insight"]
    assert events[0].iteration == 2
    assert events[0].generalizable is True
    assert events[0].files == ["tests/conftest.py"]
    assert llm.calls[0][2] == "harness_distiller"


def test_distill_empty_raw_events_skips_llm():
    llm = DistillLLM(EVENTS_PAYLOAD)
    assert KnowledgeDistiller(llm).distill([], "round_end", 1) == []
    assert llm.calls == []


def test_distill_garbage_degrades_to_empty():
    llm = DistillLLM("not json")
    assert KnowledgeDistiller(llm).distill([{"type": "trace"}], "round_end", 1) == []


def test_distill_ignores_non_object_entries():
    llm = DistillLLM('{"events": ["x", 42, {"type": "insight"}]}')
    events = KnowledgeDistiller(llm).distill([{"type": "trace"}], "round_end", 1)
    assert len(events) == 1
    assert events[0].type == "insight"


def test_distill_rejects_unknown_types_and_caps_output():
    payload = (
        '{"events": ['
        + ",".join(
            ['{"type": "operation_log", "problem": "noise"}']
            + ['{"type": "insight", "problem": "p"}'] * 7
        )
        + "]}"
    )
    events = KnowledgeDistiller(DistillLLM(payload)).distill(
        [{"type": "trace"}], "round_end", 1
    )
    assert len(events) == 6
    assert {event.type for event in events} == {"insight"}


def test_distill_track_callback():
    tracked = []
    llm = DistillLLM(EVENTS_PAYLOAD)

    def track(tracker, stage):
        tracked.append((tracker, stage))

    KnowledgeDistiller(llm, track=track).distill(
        [{"type": "trace"}], "round_end", 1, tracker="tracker"
    )
    assert tracked == [("tracker", "harness_distiller")]


def test_collapse_repair_loops_groups_per_slice():
    raw = [
        {
            "type": "trace",
            "payload": {"label": "SLICE 1/2", "message": "SLICE 1/2: core"},
        },
        {"type": "engineer_trajectory", "payload": {}},
        {"type": "repair_brief", "payload": {"failure_type": "test_failed"}},
        {"type": "engineer_trajectory", "payload": {}},
        {"type": "trace", "payload": {"label": "REPAIR", "message": "x"}},
        {"type": "repair_brief", "payload": {"failure_type": "test_failed"}},
        {
            "type": "trace",
            "payload": {"label": "SLICE", "message": "core 已通过并提交 abc12345"},
        },
        {
            "type": "trace",
            "payload": {"label": "SLICE 2/2", "message": "SLICE 2/2: api"},
        },
        {"type": "repair_brief", "payload": {"failure_type": "review_failed"}},
    ]
    collapsed = KnowledgeDistiller.collapse_repair_loops(raw)
    assert len(collapsed) == 2
    assert collapsed[0]["payload"]["retry_count"] == 2
    assert collapsed[1]["payload"]["retry_count"] == 1
    assert collapsed[0]["payload"]["attempts"][0]["failure_type"] == "test_failed"
    assert collapsed[1]["payload"]["attempts"][0]["failure_type"] == "review_failed"


def test_collapse_repair_loops_empty_and_noise():
    assert KnowledgeDistiller.collapse_repair_loops([]) == []
    assert (
        KnowledgeDistiller.collapse_repair_loops(
            [{"type": "trace", "payload": {"label": "STATE", "message": "x"}}]
        )
        == []
    )


def test_distill_collapse_false_passes_structured_payload_verbatim():
    llm = DistillLLM(EVENTS_PAYLOAD)
    payload = [
        {"checkpoint": "review_complete", "slice_id": "core", "review": "passed"}
    ]
    events = KnowledgeDistiller(llm).distill(
        payload,
        "review_complete",
        1,
        collapse=False,
    )
    assert [event.type for event in events] == ["failure", "insight"]
    user_prompt = llm.calls[0][1]
    assert "review_complete" in user_prompt
    assert "core" in user_prompt
    assert '"review": "passed"' in user_prompt


def test_distill_collapse_true_renders_collapsed_groups():
    llm = DistillLLM(EVENTS_PAYLOAD)
    KnowledgeDistiller(llm).distill(
        [{"checkpoint": "review_complete", "slice_id": "core", "review": "passed"}],
        "review_complete",
        1,
    )
    user_prompt = llm.calls[0][1]
    assert '"checkpoint": "review_complete"' in user_prompt
    assert '"review": "passed"' in user_prompt
