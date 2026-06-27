import tempfile
from pathlib import Path
from onep.strategy.pipeline_state import PipelineState, Layer, Status

def test_state_transitions():
    state = PipelineState(project_name="test", workspace="/tmp/test")
    assert state.status == Status.INIT

    state.start_layer(Layer.SCAN)
    assert state.status == Status.SCANNING

    state.complete_layer(Layer.SCAN)
    assert state.status == Status.SCAN_DONE

    state.start_layer(Layer.ANALYZE)
    assert state.status == Status.ANALYZING

    state.complete_layer(Layer.ANALYZE)
    assert state.status == Status.ANALYZE_DONE

    state.start_layer(Layer.DIALOGUE)
    assert state.status == Status.DIALOGUE_ACTIVE
    state.complete_layer(Layer.DIALOGUE)
    assert state.status == Status.COMPLETED

def test_state_save_and_load():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        state = PipelineState(project_name="test", workspace=str(ws))
        state.start_layer(Layer.SCAN)
        state.save()

        loaded = PipelineState.load(str(ws))
        assert loaded.status == Status.SCANNING
        assert loaded.project_name == "test"

def test_fail_and_resume():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        state = PipelineState(project_name="test", workspace=str(ws))
        state.start_layer(Layer.SCAN)
        state.fail("rate limit")
        assert state.status == Status.FAILED

        # resume should go back to scanning
        state.start_layer(Layer.SCAN)
        assert state.status == Status.SCANNING

def test_from_layer_skip():
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d)
        state = PipelineState(project_name="test", workspace=str(ws))
        state.start_from(Layer.ANALYZE)
        assert state.status == Status.ANALYZING
