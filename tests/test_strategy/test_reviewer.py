from onep.strategy.reviewer import ReviewAgent


class FakeLLM:
    def __init__(self, output):
        self.output = output
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return self.output


def test_reviewer_parses_structured_blockers():
    llm = FakeLLM(
        '{"passed":false,"blocking_issues":'
        '[{"file":"app.py","line":2,"message":"incorrect"}],'
        '"summary":"one blocker"}'
    )
    result = ReviewAgent(llm).review("# Plan", "diff", "1 passed", "# Context")
    assert not result.passed
    assert "app.py:2" in result.findings[0]
    assert llm.calls[0]["stage_name"] == "code_reviewer"


def test_invalid_review_is_blocking():
    result = ReviewAgent(FakeLLM("looks fine")).review(
        "# Plan", "diff", "ok", ""
    )
    assert not result.passed
    assert result.summary == "invalid reviewer output"
