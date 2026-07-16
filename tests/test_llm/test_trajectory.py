from onep.llm.trajectory import StuckDetector, TrajectoryRecorder


def test_trajectory_recorder_sequences_and_forwards_events():
    forwarded = []
    recorder = TrajectoryRecorder(forwarded.append)
    first = recorder.emit("tool_requested", tool_name="file_read")
    second = recorder.emit("tool_completed", tool_name="file_read")
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert forwarded == recorder.events


def test_stuck_detector_flags_repeated_identical_tool_call():
    detector = StuckDetector(repeat_limit=3)
    assert detector.observe_call("file_read", {"path": "a.py"}) is None
    assert detector.observe_call("file_read", {"path": "a.py"}) is None
    assert detector.observe_call("file_read", {"path": "a.py"}) == (
        "repeated_tool_call:file_read"
    )


def test_stuck_detector_resets_when_action_changes():
    detector = StuckDetector(repeat_limit=2)
    assert detector.observe_call("file_read", {"path": "a.py"}) is None
    assert detector.observe_call("file_read", {"path": "b.py"}) is None
