import pytest

from onep.greenfield.models import GreenfieldRun
from onep.greenfield.recorder import GreenfieldRecorder
from onep.harness.understand import HarnessUnsupportedMode, UnderstandStage
from onep.llm.cost import CostTracker


class DiscoverLLM:
    def invoke(self, system_prompt, user_prompt, stage_name):
        return """{
          "acceptance": [{"id":"REQ-1","priority":"P0","behavior":"value is one",
                          "verification":{"commands":["pytest -q"],"evidence":[]}}],
          "architecture": {"selected":"Python","rationale":"minimal"},
          "slices": [{"id":"core","title":"Core","objective":"set value",
                      "acceptance_ids":["REQ-1"],
                      "expected_files":["app.py","test_app.py"],
                      "focused_commands":[]}]
        }"""


class _Kernel:
    def __init__(self, llm):
        self.llm = llm

    def _discover(self, run, workspace, recorder, tracker):
        from onep.greenfield.engine import DISCOVERY_PROMPT
        output = self.llm.invoke("", "", "greenfield_engineer")
        import json
        data = json.loads(output)
        from onep.greenfield.models import AcceptanceContract, SlicePlan
        contract = AcceptanceContract.from_dict(
            {"requirements": data.get("acceptance") or []}
        )
        run.slices = [
            SlicePlan.from_dict(item, index)
            for index, item in enumerate(data.get("slices") or [])
        ]
        return contract


def test_understand_produces_contract(tmp_path):
    run = GreenfieldRun(
        id="gf-1", project_name="demo", requirement="build value",
        workspace=str(tmp_path),
    )
    recorder = GreenfieldRecorder(tmp_path / "runs" / "gf-1", run, None)
    stage = UnderstandStage(_Kernel(DiscoverLLM()), mode="greenfield")
    contract = stage.run(run, tmp_path, recorder, CostTracker(0.0))
    assert len(contract.items) == 1
    assert contract.items[0].id == "REQ-1"
    assert len(run.slices) == 1
    assert run.slices[0].id == "core"


def test_mixed_understand_uses_requirement_contract(tmp_path):
    run = GreenfieldRun(
        id="gf-mixed", project_name="demo", requirement="add auth",
        workspace=str(tmp_path),
    )
    recorder = GreenfieldRecorder(tmp_path / "runs" / "gf-mixed", run, None)
    contract = UnderstandStage(_Kernel(DiscoverLLM()), mode="mixed").run(
        run, tmp_path, recorder, CostTracker(0.0)
    )
    assert contract.items[0].id == "REQ-1"
    assert run.slices[0].id == "core"


def test_brownfield_mode_raises():
    class _BrownfieldKernel:
        pass
    with pytest.raises(HarnessUnsupportedMode):
        UnderstandStage(_BrownfieldKernel(), mode="brownfield").run(
            GreenfieldRun(
                id="gf-2", project_name="x", requirement="",
                workspace="/tmp/x",
            ),
            __import__("pathlib").Path("/tmp/x"),
            None,
            None,
        )
