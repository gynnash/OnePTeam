"""Minimal GitHub API client for the RESEARCH stage (stdlib only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


class GitHubUnavailable(RuntimeError):
    """GitHub API is unreachable, rate limited, or returned an error."""


@dataclass(frozen=True)
class RepoInfo:
    full_name: str
    url: str = ""
    language: str = ""
    topics: tuple[str, ...] = ()
    stargazers_count: int = 0
    description: str = ""
    pushed_at: str = ""
    archived: bool = False


class GitHubSearchClient:
    BASE_URL = "https://api.github.com"

    def __init__(
        self,
        token: str | None = None,
        urlopen: Callable[..., Any] | None = None,
        timeout: float = 10.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self._urlopen = urlopen or urllib.request.urlopen
        self._timeout = timeout
        self._now = now or (lambda: datetime.now(timezone.utc))

    def _get(self, path: str, accept: str) -> str:
        request = urllib.request.Request(
            self.BASE_URL + path,
            headers={
                "User-Agent": "onep-harness",
                "Accept": accept,
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
        )
        try:
            try:
                with self._urlopen(request, timeout=self._timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except TypeError:
                # Some urlopen callables (e.g. test doubles) only accept a
                # positional request; fall back to the default timeout.
                with self._urlopen(request) as response:
                    return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise GitHubUnavailable(
                f"GitHub API returned HTTP {exc.code} for {path}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GitHubUnavailable(
                f"GitHub API unreachable for {path}: {exc}"
            ) from exc

    def _get_json(self, path: str) -> dict[str, Any]:
        body = self._get(path, "application/vnd.github+json")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise GitHubUnavailable(
                f"GitHub API returned invalid JSON for {path}"
            ) from exc
        return data if isinstance(data, dict) else {}

    def search_repos(self, query: str, max_results: int = 10) -> list[RepoInfo]:
        path = (
            "/search/repositories?q="
            + urllib.parse.quote(query)
            + f"&sort=stars&order=desc&per_page={max(1, max_results)}"
        )
        data = self._get_json(path)
        repos = []
        for item in data.get("items") or []:
            if not isinstance(item, dict):
                continue
            topics = item.get("topics") or []
            repos.append(
                RepoInfo(
                    full_name=str(item.get("full_name") or ""),
                    url=str(item.get("html_url") or ""),
                    language=str(item.get("language") or ""),
                    topics=tuple(str(topic) for topic in topics),
                    stargazers_count=int(item.get("stargazers_count") or 0),
                    description=str(item.get("description") or ""),
                    pushed_at=str(item.get("pushed_at") or ""),
                    archived=bool(item.get("archived", False)),
                )
            )
        return repos

    def filter_repos(
        self,
        repos: list[RepoInfo],
        max_repos: int = 3,
        min_stars: int = 100,
        max_age_days: int = 730,
    ) -> list[RepoInfo]:
        kept: dict[str, RepoInfo] = {}
        for repo in repos:
            if repo.archived:
                continue
            if repo.stargazers_count < min_stars:
                continue
            if repo.pushed_at and not self._recent(repo.pushed_at, max_age_days):
                continue
            if repo.full_name not in kept:
                kept[repo.full_name] = repo
        ordered = sorted(
            kept.values(),
            key=lambda repo: (-repo.stargazers_count, repo.full_name),
        )
        return ordered[: max(0, max_repos)]

    def _recent(self, pushed_at: str, max_age_days: int) -> bool:
        try:
            pushed = datetime.strptime(pushed_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return True  # unparsable dates are not dropped
        pushed = pushed.replace(tzinfo=timezone.utc)
        age = self._now() - pushed
        return age.days <= max_age_days

    def fetch_readme(self, full_name: str, max_chars: int = 8000) -> str:
        body = self._get(
            f"/repos/{full_name}/readme",
            "application/vnd.github.raw+json",
        )
        try:
            decoded = json.loads(body)
            if isinstance(decoded, str):
                body = decoded
        except json.JSONDecodeError:
            pass  # raw markdown is not JSON; use it as-is
        return body[:max_chars]

    def fetch_top_tree(self, full_name: str, max_entries: int = 200) -> list[str]:
        data = self._get_json(f"/repos/{full_name}/git/trees/HEAD?recursive=1")
        paths = []
        for entry in data.get("tree") or []:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if isinstance(path, str):
                paths.append(path)
            if len(paths) >= max_entries:
                break
        return paths

    def fetch_file(self, full_name: str, path: str, max_chars: int = 6000) -> str:
        safe_path = urllib.parse.quote(path.strip("/"), safe="/")
        body = self._get(
            f"/repos/{full_name}/contents/{safe_path}",
            "application/vnd.github.raw+json",
        )
        return body[:max_chars]
