"""Memory hooks — fire-and-forget capture points for pipeline lifecycle events."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def on_stage_complete(project_name: str, stage_name: str, summary: str) -> None:
    """Called when a Greenfield stage completes."""
    try:
        from onep.memory.manager import MemoryManager
        mgr = MemoryManager()
        mgr.capture(
            source_id=f"greenfield:{project_name}",
            title=f"[{stage_name}] {summary[:60]}",
            content=summary,
            importance=_stage_importance(stage_name),
        )
    except Exception as e:
        logger.warning(f"Memory hook failed (stage_complete): {e}")


def on_analysis_complete(project_name: str, strategy_count: int, summary: str) -> None:
    """Called when Brownfield Layer 2 analysis finishes."""
    try:
        from onep.memory.manager import MemoryManager
        mgr = MemoryManager()
        mgr.capture(
            source_id=f"brownfield:{project_name}",
            title=f"策略分析完成 — 发现 {strategy_count} 个优化方向",
            content=summary,
            importance=8,
        )
    except Exception as e:
        logger.warning(f"Memory hook failed (analysis_complete): {e}")


def on_dialogue_exit(project_name: str, item_count: int, summary: str) -> None:
    """Called when user exits the workbench dialogue."""
    try:
        from onep.memory.manager import MemoryManager
        mgr = MemoryManager()
        mgr.capture(
            source_id=f"brownfield:{project_name}",
            title=f"对话会话结束 — 讨论了 {item_count} 个优化方向",
            content=summary,
            importance=5,
        )
    except Exception as e:
        logger.warning(f"Memory hook failed (dialogue_exit): {e}")


def on_plan_generated(project_name: str, item_title: str, plan_content: str) -> None:
    """Called when a Plan is generated for a strategy item."""
    try:
        from onep.memory.manager import MemoryManager
        mgr = MemoryManager()
        mgr.capture(
            source_id=f"brownfield:{project_name}",
            title=f"Plan: {item_title}",
            content=plan_content[:2000],
            importance=7,
        )
    except Exception as e:
        logger.warning(f"Memory hook failed (plan_generated): {e}")


def _stage_importance(stage_name: str) -> int:
    mapping = {"pm": 6, "designer": 5, "architect": 7, "developer": 5,
               "tester": 4, "devops": 4}
    return mapping.get(stage_name, 3)
