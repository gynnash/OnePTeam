from onep.orchestrator.greenfield import (
    GREENFIELD_STAGES,
    get_greenfield_stages,
    STAGE_PROMPTS,
)


def test_greenfield_has_six_stages():
    assert len(GREENFIELD_STAGES) == 6
    stage_names = [s["name"] for s in GREENFIELD_STAGES]
    assert stage_names == ["pm", "designer", "architect", "developer", "tester", "devops"]


def test_all_stages_have_prompts():
    for stage in GREENFIELD_STAGES:
        assert stage["name"] in STAGE_PROMPTS, f"Missing prompt for {stage['name']}"


def test_prompts_contain_workspace_placeholder():
    for name, prompt in STAGE_PROMPTS.items():
        if name == "pm":
            assert "{requirement}" in prompt
        else:
            assert "{workspace}" in prompt or "{prd_content}" in prompt
