"""Fingerprint, deduplicate, and dependency-group Optimize Plans."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from onep.strategy.optimize_models import PlanCandidate


_SHARED_NAMES = {
    "package.json", "pyproject.toml", "requirements.txt", "go.mod",
    "cargo.toml", "schema.sql", "openapi.yaml", "openapi.json",
}
_SHARED_FLAGS = {
    "schema", "api_contract", "manifest", "shared_config",
    "semantic_coupling",
}


class PlanScheduler:
    def fingerprint(self, candidate: PlanCandidate) -> str:
        payload = {
            "title": " ".join(candidate.title.lower().split()),
            "summary": " ".join(candidate.summary.lower().split()),
            "primary_file": (
                sorted(str(path).lower() for path in candidate.files)[0]
                if candidate.files else ""
            ),
            "tags": sorted(tag.lower() for tag in candidate.tags),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

    def new_candidates(
        self, candidates: list[PlanCandidate], known_fingerprints: set[str]
    ) -> list[PlanCandidate]:
        seen = set(known_fingerprints)
        result = []
        for candidate in candidates:
            candidate.fingerprint = candidate.fingerprint or self.fingerprint(candidate)
            if candidate.fingerprint in seen:
                continue
            seen.add(candidate.fingerprint)
            result.append(candidate)
        return result

    def _conflict(self, left: PlanCandidate, right: PlanCandidate) -> bool:
        left_files = {str(path) for path in left.files}
        right_files = {str(path) for path in right.files}
        if left_files & right_files:
            return True
        if left.risk_flags & right.risk_flags & _SHARED_FLAGS:
            return True
        if "semantic_coupling" in left.risk_flags | right.risk_flags:
            return True
        return any(Path(path).name.lower() in _SHARED_NAMES for path in left_files) and any(
            Path(path).name.lower() in _SHARED_NAMES for path in right_files
        )

    def groups(
        self,
        candidates: list[PlanCandidate],
        satisfied_dependencies: set[str] | None = None,
    ) -> list[list[PlanCandidate]]:
        satisfied_dependencies = satisfied_dependencies or set()
        ids = {candidate.id for candidate in candidates}
        for candidate in candidates:
            missing = candidate.dependencies - ids - satisfied_dependencies
            if missing:
                raise ValueError(f"unknown dependency: {sorted(missing)[0]}")
        self._validate_acyclic(candidates)
        levels: dict[str, int] = {}
        for index, candidate in enumerate(candidates):
            dependency_levels = [
                levels[dependency] + 1 for dependency in candidate.dependencies
            ]
            if candidate.dependencies and index:
                dependency_levels.append(
                    max(levels[earlier.id] for earlier in candidates[:index]) + 1
                )
            conflict_levels = [
                levels[earlier.id] + 1
                for earlier in candidates[:index]
                if self._conflict(earlier, candidate)
            ]
            levels[candidate.id] = max(dependency_levels + conflict_levels + [0])
        groups: list[list[PlanCandidate]] = []
        for candidate in candidates:
            level = levels[candidate.id]
            while len(groups) <= level:
                groups.append([])
            groups[level].append(candidate)
        return groups

    def integration_order(
        self, candidates: list[PlanCandidate]
    ) -> list[PlanCandidate]:
        impact = {"medium": 0, "low": 1, "high": 2}
        pending = {candidate.id: candidate for candidate in candidates}
        ordered = []
        completed: set[str] = set()
        while pending:
            ready = [
                candidate for candidate in pending.values()
                if not (candidate.dependencies & pending.keys())
            ]
            if not ready:
                raise ValueError("dependency cycle detected")
            ready.sort(key=lambda candidate: (
                impact.get(candidate.impact, 3),
                candidate.discovery_index,
                candidate.id,
            ))
            for candidate in ready:
                ordered.append(candidate)
                completed.add(candidate.id)
                pending.pop(candidate.id)
        return ordered

    @staticmethod
    def _validate_acyclic(candidates: list[PlanCandidate]) -> None:
        graph = {candidate.id: set(candidate.dependencies) for candidate in candidates}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise ValueError("dependency cycle detected")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph.get(node, set()):
                if dependency in graph:
                    visit(dependency)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
