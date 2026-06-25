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


def test_prompts_contain_expected_placeholders():
    """Each prompt must contain the placeholders the runner provides."""
    expected = {
        "pm": ["{requirement}"],
        "designer": ["{prd_content}"],
        "architect": ["{prd_content}", "{design_content}", "{workspace}"],
        "developer": ["{arch_content}", "{workspace}"],
        "tester": ["{workspace}"],
        "devops": ["{workspace}"],
    }
    for name, placeholders in expected.items():
        prompt = STAGE_PROMPTS[name]
        for ph in placeholders:
            assert ph in prompt, f"Stage '{name}' missing placeholder '{ph}'"
