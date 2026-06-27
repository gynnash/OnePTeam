"""Project-aware memory context for business LLM calls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from onep.memory.manager import MemoryManager


@dataclass(frozen=True)
class MemoryContextRequest:
    query: str
    stage_name: str
    project_name: str = ""
    source_id: str = ""
    local_top_k: int = 6
    global_top_k: int = 3
    local_min_score: float = 0.15
    global_min_score: float = 0.45
    max_chars: int = 5000


class MemoryContextBuilder:
    def __init__(
        self, manager_factory: Callable[[], MemoryManager] = MemoryManager
    ):
        self._manager_factory = manager_factory

    def build(self, request: MemoryContextRequest) -> str:
        try:
            manager = self._manager_factory()
            local = []
            if request.source_id:
                local = manager.search(
                    query=request.query,
                    top_k=request.local_top_k,
                    source_id=request.source_id,
                    exclude_source_id=None,
                    min_score=request.local_min_score,
                )
            global_results = manager.search(
                query=request.query,
                top_k=request.global_top_k,
                source_id=None,
                exclude_source_id=request.source_id or None,
                min_score=request.global_min_score,
            )
            return self._format(local, global_results, request.max_chars)
        except Exception:
            return ""

    @staticmethod
    def _format(local: list[dict], global_results: list[dict], max_chars: int) -> str:
        seen_ids = set()
        seen_content = set()
        lines = []
        for label, results in (("当前项目", local), ("跨项目", global_results)):
            for result in results:
                identity = result.get("id")
                content = str(result.get("content", "")).strip()
                signature = (str(result.get("title", "")).strip(), content[:500])
                if identity in seen_ids or signature in seen_content:
                    continue
                seen_ids.add(identity)
                seen_content.add(signature)
                line = (
                    f"[{label}][{result.get('source_id', '?')}] "
                    f"{result.get('title', '?')}: {content[:800]}"
                )
                candidate = "\n".join(lines + [line])
                if len(candidate) > max_chars:
                    break
                lines.append(line)
        if not lines:
            return ""
        return "<relevant_memories>\n" + "\n".join(lines) + "\n</relevant_memories>"


def append_memory_context(prompt: str, context: str) -> str:
    if not context:
        return prompt
    return (
        f"{prompt}\n\n{context}\n\n"
        "历史记忆仅供参考；如与当前用户要求或代码事实冲突，以当前信息为准。"
    )
