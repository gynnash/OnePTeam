"""Plan generator — produces standard and full optimization plans."""
from __future__ import annotations

from pathlib import Path
from onep.strategy.models import StrategyItem
from onep.strategy.persistence import save_plan
from onep.memory.context import append_memory_context


STANDARD_PLAN_TEMPLATE = """# 优化 Plan: {title}

## 基本信息

- **文件位置**: {file_location}
- **策略类型**: {tags}
- **影响评估**: {impact}
- **版本**: 标准版
- **生成时间**: {timestamp}

## 问题描述

{problem_description}

## 优化方向

{optimization_direction}

## 实现思路

{implementation_approach}

## 风险评估

{risk_assessment}

## 参考方案

{reference_solutions}
"""

FULL_PLAN_APPENDIX = """

---

## 完整版附加内容

## 伪代码 / 架构变更

{pseudocode}

## 数据对比

{data_comparison}

## 优先级与依赖

{priority_and_dependencies}
"""


def _build_standard_prompt(item: StrategyItem) -> str:
    return f"""请为以下策略优化方向生成标准版优化Plan。

优化方向: {item.title}
文件位置: {item.file_location}
当前问题: {item.summary}
策略标签: {', '.join(item.tags)}
影响评估: {item.impact}

请按以下结构输出完整的标准版Plan（中文撰写）：

1. 问题描述 — 详细描述当前策略的行为、适用场景和存在的缺陷（200-300字）
2. 优化方向 — 建议的新策略方向，说明核心改进点（200-300字）
3. 实现思路 — 关键技术方案和实现步骤，列出3-5个关键步骤（200-300字）
4. 风险评估 — 实施风险分析、回滚方案、兼容性考虑（150-200字）
5. 参考方案 — 业界类似实践或参考资料，至少2个参考（150-200字）

输出格式: 直接输出Markdown格式的完整Plan，不要用JSON包裹。"""


def _build_full_prompt(item: StrategyItem, standard_plan: str) -> str:
    return f"""以下是已审核通过的标准版优化Plan：

{standard_plan}

请在此基础上补充以下完整版内容：

1. 伪代码 / 架构变更 — 关键代码变更的伪代码或架构草图（标记变更点）
2. 数据对比 — 优化前后的量化对比预估（性能指标、资源消耗等）
3. 优先级与依赖 — 该Plan的实施优先级排序理由，以及与其他优化项的依赖关系

追加在标准版Plan的末尾，用分隔线分隔。"""


def generate_standard_plan(
    item: StrategyItem, workspace: Path, llm_adapter=None, plan_index: int = 1,
    memory_context: str = "",
) -> str | None:
    if llm_adapter is None:
        return None
    prompt = append_memory_context(_build_standard_prompt(item), memory_context)
    response = llm_adapter.invoke(
        system_prompt="你是一位策略架构师。请按照用户要求的格式输出完整的优化Plan。",
        user_prompt=prompt, stage_name="strategy_architect",
    )
    from onep.llm.adapters import display_usage
    display_usage()
    plan_id = f"{plan_index:03d}-{item.title.replace(' ', '-').replace('/', '-')[:50]}"
    plan_path = save_plan(workspace, plan_id, response)
    item.draft_plan(plan_path)
    return plan_path


def generate_full_plan(
    item: StrategyItem, standard_plan_content: str, workspace: Path, llm_adapter=None,
    memory_context: str = "",
) -> str | None:
    if llm_adapter is None:
        return None
    prompt = append_memory_context(
        _build_full_prompt(item, standard_plan_content), memory_context
    )
    response = llm_adapter.invoke(
        system_prompt="你是一位策略架构师。请在标准版Plan的基础上补充完整版内容。",
        user_prompt=prompt, stage_name="strategy_architect",
    )
    from onep.llm.adapters import display_usage
    display_usage()
    full_content = standard_plan_content + "\n" + response
    plan_id = item.plan_path.split("/")[-1].replace(".md", "") if item.plan_path else "full-plan"
    plan_path = save_plan(workspace, plan_id + "-full", full_content)
    item.expand_plan()
    item.plan_path = plan_path
    return plan_path
