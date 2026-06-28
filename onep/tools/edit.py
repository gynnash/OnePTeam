"""EditTool — exact string replacement in files, matching Claude Code's Edit behavior."""
from __future__ import annotations

from pathlib import Path

from crewai.tools import BaseTool


class EditTool(BaseTool):
    name: str = "edit"
    description: str = (
        "Performs exact string replacements in an existing file. "
        "When editing text, ensure you preserve the EXACT indentation (tabs/spaces) "
        "as it appears before. ALWAYS prefer editing existing files. "
        "Only use emojis if the user explicitly requests it. Avoid adding emojis "
        "to files unless asked. "
        "Use replace_all=True to replace every instance of old_string, "
        "or leave it False to replace only the first match. "
        "old_string must include all whitespace, indentation, blank lines, "
        "and surrounding code exactly as it appears in the file."
    )

    workspace: str = ""

    def _run(self, file_path: str, old_string: str, new_string: str,
             replace_all: bool = False) -> str:
        full = (Path(self.workspace) / file_path).resolve()
        if not str(full).startswith(str(Path(self.workspace).resolve())):
            return f"Error: path '{file_path}' is outside workspace"
        if not full.exists():
            return f"Error: file not found: {file_path}"

        content = full.read_text()

        if replace_all:
            if old_string not in content:
                return f"Error: old_string not found in {file_path}"
            count = content.count(old_string)
            new_content = content.replace(old_string, new_string)
            full.write_text(new_content)
            return f"Edited {file_path}: {count} replacement(s)"

        # single replacement — must be unique
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {file_path}"
        if count > 1:
            return (
                f"Error: old_string is not unique in {file_path}. "
                f"Found {count} matches. Add more surrounding context to make it unique, "
                f"or use replace_all=True to replace all occurrences."
            )

        new_content = content.replace(old_string, new_string, 1)
        full.write_text(new_content)
        return f"Edited {file_path}: 1 replacement"
