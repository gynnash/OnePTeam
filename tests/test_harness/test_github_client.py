# tests/test_harness/test_github_client.py
import json
from datetime import datetime, timezone
from io import BytesIO

import pytest

from onep.harness.github_client import (
    GitHubSearchClient,
    GitHubUnavailable,
    RepoInfo,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode() if not isinstance(
            payload, bytes) else payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def _client(urlopen, now=None, token=None):
    return GitHubSearchClient(
        token=token or "test-token",
        urlopen=urlopen,
        now=now or (lambda: datetime(2026, 8, 1, tzinfo=timezone.utc)),
    )


def _repos():
    return [
        RepoInfo(full_name="a/b", stargazers_count=500,
                 pushed_at="2026-07-01T00:00:00Z"),
        RepoInfo(full_name="c/d", stargazers_count=50,
                 pushed_at="2026-07-01T00:00:00Z"),
        RepoInfo(full_name="e/f", stargazers_count=800, archived=True,
                 pushed_at="2026-07-01T00:00:00Z"),
        RepoInfo(full_name="g/h", stargazers_count=300,
                 pushed_at="2024-01-01T00:00:00Z"),
        RepoInfo(full_name="a/b", stargazers_count=900,
                 pushed_at="2026-07-01T00:00:00Z"),
        RepoInfo(full_name="i/j", stargazers_count=200,
                 pushed_at="not-a-date"),
    ]


def test_search_repos_parses_items_and_sends_auth_headers():
    requests = []

    def urlopen(request):
        requests.append(request)
        return FakeResponse({
            "items": [{
                "full_name": "clap-rs/clap",
                "html_url": "https://github.com/clap-rs/clap",
                "language": "Rust",
                "topics": ["cli"],
                "stargazers_count": 15000,
                "description": "CLI framework",
                "pushed_at": "2026-06-01T00:00:00Z",
                "archived": False,
            }],
        })

    client = _client(urlopen)
    repos = client.search_repos("cli framework")
    assert len(repos) == 1
    assert repos[0].full_name == "clap-rs/clap"
    assert repos[0].stargazers_count == 15000
    assert repos[0].topics == ("cli",)
    request = requests[0]
    assert request.get_header("User-agent") == "onep-harness"
    assert request.get_header("Authorization") == "Bearer test-token"
    assert "/search/repositories" in request.full_url
    assert "sort=stars" in request.full_url


def test_search_repos_raises_github_unavailable_on_http_error():
    def urlopen(request):
        raise __import__("urllib.error").error.HTTPError(
            request.full_url, 403, "rate limited", {}, BytesIO(b"{}"))

    with pytest.raises(GitHubUnavailable) as excinfo:
        _client(urlopen).search_repos("x")
    assert "403" in str(excinfo.value)


def test_search_repos_raises_on_url_error():
    def urlopen(request):
        raise __import__("urllib.error").error.URLError("dns down")

    with pytest.raises(GitHubUnavailable):
        _client(urlopen).search_repos("x")


def test_filter_repos_drops_archived_stale_and_low_stars():
    client = _client(lambda request: FakeResponse({}))
    kept = client.filter_repos(_repos(), max_repos=3)
    # archived (e/f), stale (g/h), and under-100-stars (c/d) dropped;
    # duplicates deduped keeping the first; sort by stars desc; cap 3.
    assert [r.full_name for r in kept] == ["a/b", "i/j"]
    assert kept[0].stargazers_count == 500


def test_fetch_readme_uses_raw_accept_header():
    requests = []

    def urlopen(request):
        requests.append(request)
        return FakeResponse("# hello world\n")

    client = _client(urlopen)
    assert client.fetch_readme("clap-rs/clap") == "# hello world\n"
    assert requests[0].get_header("Accept") == (
        "application/vnd.github.raw+json")
    assert requests[0].full_url.endswith("/repos/clap-rs/clap/readme")


def test_fetch_readme_truncates():
    def urlopen(request):
        return FakeResponse("x" * 200)

    assert len(_client(urlopen).fetch_readme("a/b", max_chars=50)) == 50


def test_fetch_top_tree_returns_paths():
    requests = []

    def urlopen(request):
        requests.append(request)
        return FakeResponse({
            "tree": [
                {"path": "src", "type": "tree"},
                {"path": "pyproject.toml", "type": "blob"},
            ],
        })

    paths = _client(urlopen).fetch_top_tree("a/b", max_entries=10)
    assert paths == ["src", "pyproject.toml"]
    assert requests[0].full_url.endswith(
        "/repos/a/b/git/trees/HEAD?recursive=1"
    )
