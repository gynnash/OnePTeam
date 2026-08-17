# tests/test_harness/test_scorer.py
from onep.harness.models import ImprovementCandidate
from onep.harness.scorer import (
    BACKLOG_THRESHOLD,
    DEFAULT_UNSCORED_SCORE,
    OpportunityScorer,
    classify,
    compute_score,
)


def test_compute_score_all_zero():
    assert compute_score({}) == 0.0


def test_compute_score_all_one_is_0_75():
    # (0.80 positive - 0.20 negative) / 0.80 == 0.75
    dims = {"V": 1.0, "Q": 1.0, "R": 1.0, "E": 1.0, "C": 1.0, "Risk": 1.0}
    assert compute_score(dims) == 0.75


def test_compute_score_value_only():
    # 0.30 * 1.0 / 0.80 == 0.375
    assert compute_score({"V": 1.0}) == 0.375


def test_compute_score_cost_only_is_negative():
    # -0.10 * 1.0 / 0.80 == -0.125
    assert compute_score({"C": 1.0}) == -0.125


def test_compute_score_clamps_out_of_range():
    assert compute_score({"V": 5.0}) == 0.375
    assert compute_score({"C": -3.0}) == 0.0


def test_classify_boundaries():
    assert classify(BACKLOG_THRESHOLD + 0.0001) == "backlog"
    assert classify(BACKLOG_THRESHOLD) == "parked"
    assert classify(0.50) == "parked"
    assert classify(0.4999) == "rejected"
    assert classify(0.0) == "rejected"


class ScorerLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls.append(stage_name)
        return self.payload


SCORES_PAYLOAD = ('{"scores": ['
                  '{"id": "I-1", "V": 0.9, "Q": 0.8, "R": 0.7, "E": 0.3, '
                  '"C": 0.2, "Risk": 0.1, "rationale": "clear win"},'
                  '{"id": "I-2", "V": 0.1, "Q": 0.1, "R": 0.1, "E": 0.1, '
                  '"C": 0.9, "Risk": 0.9, "rationale": "expensive"}]}')


def _candidates():
    return [
        ImprovementCandidate(id="I-1", title="Add caching"),
        ImprovementCandidate(id="I-2", title="Rewrite engine"),
    ]


def test_score_candidates_fills_scores_and_dimensions():
    llm = ScorerLLM(SCORES_PAYLOAD)
    scored = OpportunityScorer(llm).score_candidates(
        _candidates(), "build fast", "- REQ-1 ok", 1,
    )
    assert scored[0].score == compute_score({
        "V": 0.9, "Q": 0.8, "R": 0.7, "E": 0.3, "C": 0.2, "Risk": 0.1,
    })
    assert scored[0].dimensions["rationale"] == "clear win"
    assert scored[1].score == compute_score({
        "V": 0.1, "Q": 0.1, "R": 0.1, "E": 0.1, "C": 0.9, "Risk": 0.9,
    })
    assert scored[1].dimensions["V"] == 0.1
    assert llm.calls == ["harness_scorer"]


def test_score_candidates_returns_empty_for_no_input():
    llm = ScorerLLM(SCORES_PAYLOAD)
    assert OpportunityScorer(llm).score_candidates([], "g", "", 1) == []
    assert llm.calls == []


def test_score_candidates_falls_back_on_garbage():
    llm = ScorerLLM("not json at all")
    scored = OpportunityScorer(llm).score_candidates(
        _candidates(), "g", "", 1,
    )
    assert all(c.score == DEFAULT_UNSCORED_SCORE for c in scored)
    assert all(c.dimensions == {"rationale": "scorer unavailable"}
               for c in scored)


def test_score_candidates_falls_back_for_unmatched_ids():
    llm = ScorerLLM('{"scores": [{"id": "OTHER", "V": 1, "Q": 1, "R": 1, '
                    '"E": 1, "C": 0, "Risk": 0}]}')
    scored = OpportunityScorer(llm).score_candidates(
        _candidates(), "g", "", 1,
    )
    assert all(c.score == DEFAULT_UNSCORED_SCORE for c in scored)


class ExplodingLLM:
    def __init__(self):
        self.calls = 0

    def invoke(self, system_prompt, user_prompt, stage_name):
        self.calls += 1
        raise RuntimeError("api down")


def test_score_candidates_llm_failure_falls_back_to_default():
    llm = ExplodingLLM()
    scored = OpportunityScorer(llm).score_candidates(
        _candidates(), "g", "", 1,
    )
    assert all(c.score == DEFAULT_UNSCORED_SCORE for c in scored)
    assert all(c.dimensions == {"rationale": "scorer unavailable"}
               for c in scored)
    assert llm.calls == 1


def test_score_candidates_empty_dims_treated_as_unscored():
    llm = ScorerLLM('{"scores": [{"id": "I-1"}, {"id": "I-2"}]}')
    scored = OpportunityScorer(llm).score_candidates(
        _candidates(), "g", "", 1,
    )
    assert all(c.score == DEFAULT_UNSCORED_SCORE for c in scored)
