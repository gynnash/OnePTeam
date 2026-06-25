from onep.persistence.models import (
    Project,
    ProjectMode,
    ProjectStatus,
    StageRun,
    StageStatus,
    Approval,
    Decision,
    PipelineState,
)


def test_project_creation():
    p = Project(
        name="test-app",
        mode=ProjectMode.GREENFIELD,
        workspace_path="/tmp/test-app",
    )
    assert p.name == "test-app"
    assert p.mode == ProjectMode.GREENFIELD
    assert p.status == ProjectStatus.RUNNING
    assert len(p.id) == 32


def test_stage_run_lifecycle():
    sr = StageRun(
        project_id="proj-1",
        stage_name="pm",
        agent_name="Product Manager",
    )
    assert sr.status == StageStatus.PENDING

    sr.start()
    assert sr.status == StageStatus.IN_PROGRESS
    assert sr.started_at != ""

    sr.complete(output_files=["docs/PRD.md"], token_count=1500)
    assert sr.status == StageStatus.COMPLETED
    assert sr.output_files == ["docs/PRD.md"]
    assert sr.token_count == 1500
    assert sr.finished_at != ""


def test_stage_run_fail():
    sr = StageRun(project_id="p1", stage_name="test", agent_name="Tester")
    sr.fail("connection timeout")
    assert sr.status == StageStatus.FAILED
    assert sr.error_message == "connection timeout"


def test_approval_creation():
    a = Approval(stage_run_id="sr-1", decision=Decision.APPROVED, feedback="LGTM")
    assert a.decision == Decision.APPROVED
    assert a.feedback == "LGTM"


def test_pipeline_state_defaults():
    ps = PipelineState()
    assert ps.mode == ProjectMode.GREENFIELD
    assert ps.stages_completed == []
    assert ps.pending_approval is False
