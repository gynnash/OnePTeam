"""Brownfield pipeline: Scan → Analyze → Dialogue."""
from __future__ import annotations

from crewai import Task

from onep.agents.registry import get_agent
from onep.persistence.models import Project, PipelineState


BROWNFIELD_STAGES = [
    {"name": "scan", "agent": "analyzer", "description": "策略文件扫描"},
    {"name": "analyze", "agent": "strategy_architect", "description": "深度策略分析"},
]

SCAN_PROMPT = """请分析以下文件，判定每个文件是否包含业务策略或算法策略逻辑。

策略逻辑包括：
- 推荐算法、排序算法、匹配算法
- LLM prompt 链、Agent 工作流、模型路由
- 缓存策略、限流策略、资源分配策略
- 业务规则、定价策略、风控规则、风险评分
- 任何影响系统行为的非平凡决策逻辑

不属於策略逻辑：
- 纯工具函数（字符串处理、日期格式化）
- 配置常量或枚举
- 简单 CRUD（无决策逻辑）
- 样板代码（中间件、日志、路由注册）
- 测试文件

待分析文件列表：
{file_list}

对每个文件输出一行 JSON：
{{"file": "<path>", "is_strategy": true/false, "reason": "<一句话理由，中文>"}}

只输出 JSON，每行一个文件，不要其他内容。"""

ANALYZE_PROMPT = """请对以下策略密集文件进行深度分析，发现可优化点。

策略密集文件列表：
{file_list}

项目根目录: {source_root}

对每个发现的优化点，输出一行 JSON：
- title: 优化方向标题（简洁，10字以内）
- file_location: 主文件位置（如 "cache.py:30"）
- tags: 策略类型标签数组（如 ["缓存策略", "性能"]）
- impact: 影响评估（"high" / "medium" / "low"）
- summary: 问题摘要（2-3句，描述当前策略问题和优化方向）

要求：
- 只输出确实存在优化空间的发现，不为每个文件都生成条目
- 同一策略问题涉及多个文件时合并为一个条目
- 影响评估基于实际分析，不全部标 high
- 按影响程度从高到低排序

⚠️ 特别关注 LLM 输出质量问题，以下问题通常应标为 high 影响：
- Prompt 设计缺陷：冗余、歧义、缺少关键约束、示例不足
- Token 浪费：重复注入未缓存的内容、过长的 system prompt
- 输出格式脆弱：JSON 解析容易失败、字段名不一致、缺少 schema 校验
- 模型路由不当：复杂任务用了弱模型、缺少 fallback、未用 caching
- Agent 循环失控：缺少 max_iter 限制、工具调用死循环风险
- 流式处理缺失：可流式场景用了非流式，用户等待体验差

只输出 JSON，每行一个对象，不要其他内容。"""


SCAN_PROMPT_FULL = """请分析以下文件内容，判定是否包含业务策略或算法策略逻辑。

策略逻辑包括：
- 推荐算法、排序算法、匹配算法
- LLM prompt 链、Agent 工作流、模型路由
- 缓存策略、限流策略、资源分配策略
- 业务规则、定价策略、风控规则、风险评分
- 任何影响系统行为的非平凡决策逻辑

不属于策略逻辑：
- 纯工具函数（字符串处理、日期格式化）
- 配置常量或枚举
- 简单 CRUD（无决策逻辑）
- 样板代码（中间件、日志、路由注册）
- 测试文件

文件内容:
{file_block}

对每个文件输出一行 JSON：
{{"file": "<path>", "is_strategy": true/false, "reason": "<一句话理由>", ""}}

只输出 JSON，每行一个文件，不要其他内容。"""


RECHECK_PROMPT = """判定以下文件是否有值得优化的策略逻辑。

文件: {file_path}
内容:
```
{content}
```

输出一行 JSON：
{{"verdict": "keep" | "drop", "reason": "<一句话>"}}

drop 的情况：
- 虽然有策略关键词但实现已合理
- 纯样板代码被误标为策略
- 决策逻辑简单清晰无优化空间"""


def build_brownfield_tasks(project: Project, state: PipelineState) -> list[Task]:
    """Build CrewAI Task list for the Brownfield pipeline."""
    tasks = []
    for stage in BROWNFIELD_STAGES:
        task = Task(
            description=f"Execute {stage['name']} for project {project.name}",
            expected_output=f"Stage {stage['name']} completed.",
            agent=get_agent(
                stage["agent"],
                workspace=str(project.workspace_path),
                source_id=f"brownfield:{project.name}",
            ),
        )
        tasks.append(task)
    return tasks
