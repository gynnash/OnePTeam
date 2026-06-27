"""MemoryTool — search and capture memories from within Agent execution."""
from __future__ import annotations

from crewai.tools import BaseTool


class MemoryTool(BaseTool):
    default_source_id: str = ""
    name: str = "memory"
    description: str = (
        "Search past memories across projects, or capture a new memory. "
        "Use operation='search' with a query string to find relevant past decisions "
        "and patterns. Use operation='capture' with title and content to save "
        "something worth remembering."
    )

    def _run(self, operation: str, query: str = "", title: str = "",
             content: str = "", source_id: str = "") -> str:
        op = operation.lower()
        from onep.memory.manager import MemoryManager
        mgr = MemoryManager()

        if op == "search":
            if not query:
                return "Error: 'query' is required for search."
            results = mgr.search(query, top_k=5)
            if not results:
                return "No relevant memories found."
            lines = []
            for r in results:
                title = r.get("title", "?")
                source = r.get("source_id", "?")
                score = r.get("score", 0)
                lines.append(f"  [{source}] {title} (score: {score:.2f})")
            return "Found memories:\n" + "\n".join(lines)

        if op == "capture":
            if not title or not content:
                return "Error: 'title' and 'content' are required for capture."
            mgr.capture(
                source_id=source_id or self.default_source_id or "agent",
                title=title,
                content=content,
            )
            return f"Memory captured: {title}"

        return f"Unknown operation '{operation}'. Use 'search' or 'capture'."
