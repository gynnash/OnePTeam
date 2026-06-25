"""Layer 2: Deep strategy analyzer. Calls the Strategy Architect agent on strategy-dense files."""
from __future__ import annotations

import json
from pathlib import Path

from onep.strategy.models import StrategyItem


def _build_analysis_prompt(strategy_files: list[str], source_root: Path) -> str:
    file_list = "\n".join(f"- {f}" for f in strategy_files)
    return f"""请分析以下文件中的策略逻辑，发现可优化点。

策略密集文件列表：
{file_list}

项目根目录: {source_root}

对于每个发现的优化点，请输出一条JSON（一行），包含以下字段：
- title: 优化方向标题（简洁明了，10字以内）
- file_location: 主文件位置（如 "cache.py:30"）
- tags: 策略类型标签数组（如 ["缓存策略", "性能"]）
- impact: 影响评估（"high" / "medium" / "low"）
- summary: 问题摘要（2-3句描述当前策略的问题和优化方向）

注意：
- 只输出确实存在优化空间的发现，不要为每个文件都生成条目
- 如果多个文件涉及同一个策略问题，合并为一个条目
- 影响评估要基于实际分析，不要全部标 high
- 按影响程度从高到低排序输出

输出格式（每行一个JSON对象）：
{{"title": "...", "file_location": "...", "tags": [...], "impact": "high", "summary": "..."}}"""


def _parse_analysis_response(response: str) -> list[StrategyItem]:
    items = []
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            items.append(StrategyItem(
                title=obj["title"],
                file_location=obj["file_location"],
                tags=obj.get("tags", []),
                impact=obj.get("impact", "medium"),
                summary=obj.get("summary", ""),
            ))
        except (json.JSONDecodeError, KeyError):
            continue
    return items


def analyze_strategies(
    strategy_files: list[str],
    source_root: Path,
    llm_adapter=None,
) -> list[StrategyItem]:
    if not strategy_files:
        return []
    if llm_adapter is not None:
        prompt = _build_analysis_prompt(strategy_files, source_root)
        response = llm_adapter.invoke(
            system_prompt="你是一位策略架构师。只输出JSON，每行一个优化发现，按影响程度从高到低排序。",
            user_prompt=prompt,
            stage_name="strategy_architect",
        )
        items = _parse_analysis_response(response)
    else:
        items = [StrategyItem(
            title="LLM不可用，策略分析待执行",
            file_location="N/A",
            summary="请配置API密钥后重新运行分析。",
            tags=["系统"],
            impact="high",
        )]
    impact_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda x: impact_order.get(x.impact, 2))
    return items
