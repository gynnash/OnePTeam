"""Deterministic quality and deployment gates for Greenfield projects."""
from __future__ import annotations

import json
from pathlib import Path
import shlex

from onep.strategy.test_runner import PlanTestResult, PlanTestRunner


_SAFE_GATE_PREFIXES = (
    ("pytest",), ("python", "-m", "pytest"), ("python3", "-m", "pytest"),
    ("python",), ("python3",), ("sqlite3",),
    ("bash",), ("sh",), ("cat",), ("head",), ("tail",),
    ("ruff", "check"), ("ruff", "format"), ("mypy",), ("pyright",),
    ("npm", "test"), ("npm", "run"), ("pnpm",), ("yarn",),
    ("go", "test"), ("go", "vet"), ("cargo", "test"),
    ("cargo", "clippy"), ("make",), ("./gradlew",), ("mvn",),
    ("docker", "compose"),
)


def validate_gate_commands(commands: list[str] | tuple[str, ...]) -> None:
    for command in commands:
        if _has_shell_composition(command):
            raise ValueError(f"Unsafe quality gate command: {command}")
        parts = tuple(shlex.split(command))
        if not parts or not any(
            parts[:len(prefix)] == prefix for prefix in _SAFE_GATE_PREFIXES
        ):
            raise ValueError(f"Unsupported quality gate command: {command}")


def _has_shell_composition(command: str) -> bool:
    """Detect shell operators while allowing punctuation inside quoted arguments."""
    if "\n" in command or "\r" in command:
        return True
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            if quote == '"' and (
                char == "`" or command[index:index + 2] == "$("
            ):
                return True
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            index += 1
            continue
        if char in {";", "|", ">", "<", "`"} or command[index:index + 2] in {
            "&&", "||", "$(",
        }:
            return True
        index += 1
    return bool(quote or escaped)


def discover_quality_commands(workspace: Path) -> list[str]:
    workspace = Path(workspace)
    commands: list[str] = []
    pyproject = workspace / "pyproject.toml"
    pyproject_text = pyproject.read_text(errors="replace") if pyproject.exists() else ""
    pytest_configured = (
        (workspace / "pytest.ini").exists()
        or "[tool.pytest." in pyproject_text
        or any(
            path.exists() and "[pytest]" in path.read_text(errors="replace")
            for path in (workspace / "tox.ini", workspace / "setup.cfg")
        )
    )
    test_files = [
        *workspace.glob("test_*.py"),
        *workspace.glob("*_test.py"),
    ]
    for root_name in ("test", "tests"):
        root = workspace / root_name
        if root.is_dir():
            test_files.extend(root.rglob("test_*.py"))
            test_files.extend(root.rglob("*_test.py"))
    if pytest_configured or test_files:
        commands.append("pytest -q")
    if "ruff" in pyproject_text:
        commands.append("ruff check .")
    if "mypy" in pyproject_text:
        commands.append("mypy .")
    package = workspace / "package.json"
    if package.exists():
        try:
            scripts = (json.loads(package.read_text()).get("scripts") or {})
        except (OSError, json.JSONDecodeError, AttributeError):
            scripts = {}
        runner = "pnpm" if (workspace / "pnpm-lock.yaml").exists() else (
            "yarn" if (workspace / "yarn.lock").exists() else "npm run"
        )
        for script in ("test", "lint", "typecheck", "build"):
            value = scripts.get(script)
            if isinstance(value, str) and value.strip() and "no test specified" not in value.lower():
                commands.append(
                    f"{runner} {script}" if runner != "yarn" else f"yarn {script}"
                )
    if (workspace / "go.mod").exists():
        commands.extend(["go test ./...", "go vet ./..."])
    if (workspace / "Cargo.toml").exists():
        commands.extend(["cargo test", "cargo clippy"])
    if (workspace / "gradlew").exists():
        commands.append("./gradlew test")
    if (workspace / "pom.xml").exists():
        commands.append("mvn verify")
    return list(dict.fromkeys(commands))


class GreenfieldGateRunner:
    def __init__(self, timeout: int = 300):
        self.runner = PlanTestRunner(timeout)

    def run(
        self,
        workspace: Path,
        focused: list[str],
        mandatory: list[str],
    ) -> PlanTestResult:
        validate_gate_commands(focused)
        validate_gate_commands(mandatory)
        commands = list(dict.fromkeys([*focused, *mandatory]))
        if not commands:
            raise ValueError(
                "No deterministic quality gate discovered. Add --test-command."
            )
        return self.runner.run(workspace, commands)

    def deploy(self, workspace: Path, mode: str) -> PlanTestResult | None:
        if mode == "none":
            return None
        compose = (workspace / "compose.yaml").exists() or (
            workspace / "docker-compose.yml"
        ).exists()
        dockerfile = (workspace / "Dockerfile").exists()
        if not compose and not dockerfile:
            return None
        if compose:
            commands = ["docker compose config", "docker compose up -d --build", "docker compose ps"]
            result = self.runner.run(workspace, commands)
            if mode == "verify":
                self.runner.run(workspace, ["docker compose down"])
            return result
        return self.runner.run(workspace, ["docker build ."])
