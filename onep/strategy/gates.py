"""Deterministic gates applied around model-led optimization attempts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import json

from onep.strategy.optimize_models import PlanCandidate


@dataclass(frozen=True)
class PatchScopeResult:
    passed: bool
    unexpected_files: tuple[str, ...] = ()

    @property
    def feedback(self) -> str:
        if self.passed:
            return ""
        files = ", ".join(self.unexpected_files)
        return (
            "Patch scope violation. Revert changes outside the Plan's declared "
            f"files, or implement the change using only the allowed files. "
            f"Unexpected files: {files}"
        )


class PatchScopeGate:
    """Require every changed path to be declared by the generated Plan."""

    def check(
        self,
        candidate: PlanCandidate,
        changed_files: list[str],
    ) -> PatchScopeResult:
        allowed = {_normalize(path) for path in candidate.files}
        changed = {_normalize(Path(path)) for path in changed_files}
        unexpected = tuple(sorted(path for path in changed if path not in allowed))
        return PatchScopeResult(not unexpected, unexpected)


def combined_test_commands(candidate: PlanCandidate) -> list[str]:
    """Run fast model suggestions first, then all mandatory project gates."""
    return list(dict.fromkeys(
        (*candidate.focused_test_commands, *candidate.test_commands)
    ))


def validate_focused_test_commands(commands: tuple[str, ...]) -> None:
    """Reject model-proposed commands that are not recognizable test runners."""
    allowed_prefixes = (
        ("pytest",),
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
        ("uv", "run", "pytest"),
        ("poetry", "run", "pytest"),
        ("npm", "test"),
        ("npm", "run", "test"),
        ("pnpm", "test"),
        ("pnpm", "run", "test"),
        ("yarn", "test"),
        ("go", "test"),
        ("cargo", "test"),
        ("make", "test"),
        ("./gradlew", "test"),
        ("mvn", "test"),
        ("mvn", "verify"),
    )
    forbidden = ("\n", "\r", ";", "&&", "||", "|", ">", "<", "`", "$(")
    for command in commands:
        if any(token in command for token in forbidden):
            raise ValueError(f"Unsafe focused test command: {command}")
        try:
            parts = tuple(shlex.split(command))
        except ValueError as exc:
            raise ValueError(f"Invalid focused test command: {command}") from exc
        if not any(parts[:len(prefix)] == prefix for prefix in allowed_prefixes):
            raise ValueError(f"Unsupported focused test command: {command}")


def discover_required_test_commands(source: Path) -> tuple[str, ...]:
    """Derive deterministic project gates from repository manifests."""
    source = Path(source)
    commands = []
    if any((source / name).exists() for name in (
        "pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"
    )) or (source / "tests").is_dir():
        commands.append("pytest -q")
    package_json = source / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            package = {}
        scripts = package.get("scripts") if isinstance(package, dict) else {}
        test_script = scripts.get("test") if isinstance(scripts, dict) else None
        if (
            isinstance(test_script, str)
            and test_script.strip()
            and "no test specified" not in test_script.lower()
        ):
            if (source / "pnpm-lock.yaml").exists():
                commands.append("pnpm test")
            elif (source / "yarn.lock").exists():
                commands.append("yarn test")
            else:
                commands.append("npm test")
    if (source / "go.mod").exists():
        commands.append("go test ./...")
    if (source / "Cargo.toml").exists():
        commands.append("cargo test")
    if (source / "gradlew").exists():
        commands.append("./gradlew test")
    if (source / "pom.xml").exists():
        commands.append("mvn test")
    return tuple(dict.fromkeys(commands))


def _normalize(path: Path) -> str:
    normalized = path.as_posix()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
