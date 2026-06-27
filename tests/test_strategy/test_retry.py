import pytest
from onep.strategy.retry import retry_with_backoff, is_transient_error

def test_is_transient_rate_limit():
    assert is_transient_error(Exception("rate limit exceeded"))

def test_is_transient_network():
    assert is_transient_error(Exception("connection reset"))

def test_not_transient_auth():
    assert not is_transient_error(Exception("invalid api key"))

def test_not_transient_value():
    assert not is_transient_error(ValueError("bad input"))

def test_retry_succeeds_on_third_try():
    calls = [0]
    def flaky():
        calls[0] += 1
        if calls[0] < 3:
            raise Exception("rate limit")
        return "ok"
    result = retry_with_backoff(flaky, max_retries=3)
    assert result == "ok"
    assert calls[0] == 3

def test_retry_exhausted():
    def always_fail():
        raise Exception("rate limit")
    result = retry_with_backoff(always_fail, max_retries=2)
    assert result is None
