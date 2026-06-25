# 策略分析系统设计规格

## 项目概述

扩展 OnePTeam 的 Brownfield 模式，增加策略分析能力。用户输入代码库地址（Git URL 或本地路径），系统自动扫描代码中的业务策略和算法策略，发现可优化点，通过交互式对话逐步细化优化方向，生成结构化优化 Plan 但不自动执行。

## 核心流程

三层 LLM 分析 + 交互式对话 + 两阶段 Plan 生成：

```
用户输入 (onep analyze <url/path> --mode strategy)
  → Layer 1: 代码分析师 (DeepSeek V4) — 快速扫描，定位策略密集文件
  → Layer 2: 策略架构师 (GPT 5.5) — 深度分析，提取策略意图和优化点
  → Layer 3: 策略架构师 + 架构师 (GPT 5.5) — 交互式对话，生成 Plan
  → 产出: 标准版 Plan → (审核通过后) 完整版 Plan
```

## Agent 协作分工

| Agent | 模型 | Layer | 职责 |
|-------|------|-------|------|
| 代码分析师 | DeepSeek V4 | 1 | 文件级策略扫描，过滤非策略代码 |
| 策略架构师 | GPT 5.5 | 2 + 3 | 策略理解、优化发现、对话交互、Plan 生成 |
| 架构师 | GPT 5.5 | 3 | Plan 结构化校验、技术可行性评估 |

### 策略架构师 Agent 定义

- **角色**: 业务策略与算法策略的深度分析专家
- **目标**: 理解代码中承载的业务/算法策略，发现可优化点，生成结构化的优化 Plan
- **能力**: 策略意图识别、策略模式对比、量化影响评估、多方案权衡、对话引导
- **输入**: Layer 1 标记的策略密集文件 + 用户对话反馈和提示
- **输出**: 优化清单 (Layer 2) + 标准版/完整版 Plan (Layer 3) + 对话响应

## Layer 1: 快速扫描

- **执行者**: 代码分析师 Agent (DeepSeek V4)
- **输入**: 代码库的全部文件/模块
- **方法**: 按文件粒度并行扫描，每文件判定 "是否包含策略逻辑" (yes/no + 一句话理由)
- **过滤**: 纯工具代码、样板文件、配置常量、测试文件
- **输出**: 策略密集文件清单

不依赖任何预定义规则，完全由 LLM 自主判定什么算"策略"。

## Layer 2: 深度分析

- **执行者**: 策略架构师 Agent (GPT 5.5)
- **输入**: Layer 1 输出的策略密集文件
- **方法**: 深度阅读每个标记文件，理解其中的策略意图，判断是否存在优化空间
- **输出**: 优化清单，每条包含：
  - 标题
  - 文件位置 (file:line)
  - 策略类型标签 (如: 推荐策略、LLM 策略、缓存策略等)
  - 影响评估 (high/medium/low)
  - 问题摘要 (2-3 句描述当前策略的问题)

## Layer 3: 交互式对话

### CLI 命令

```bash
# 启动策略分析
onep analyze <git-url|local-path> --mode strategy
onep analyze ./my-repo --mode strategy --name my-analysis

# 恢复之前的分析会话
onep strategy resume <project-name>

# 查看分析进度
onep strategy status <project-name>

# 导出分析成果
onep strategy export <project-name> --format md
onep strategy export <project-name> --format json --items 1,3,5
```

### 对话模式

纯自然语言对话：进入工作台后，Agent 和用户可以自由对话。Agent 自动识别用户在讨论哪个优化方向，自然语言切换上下文。

### Slash 命令 (11个)

| 命令 | 功能 |
|------|------|
| `/list` | 查看所有优化方向及各自状态 |
| `/focus <n>` | 显式切换到第 n 个方向 |
| `/search <关键词>` | 在所有方向中搜索匹配项 |
| `/plan <n>` | 为第 n 个方向生成标准版 Plan |
| `/expand <n>` | 将第 n 个方向的标准版 Plan 扩展为完整版 |
| `/compare <n> <m>` | 对比两个方向的权衡 |
| `/merge <n> <m>` | 将两个相关方向合并为一个 |
| `/discard <n>` | 忽略此方向，不再出现在工作台 |
| `/save` | 手动保存当前工作台状态 |
| `/status` | 查看整体分析进度 |
| `/exit` | 退出对话模式 |

### 交互示例

```
$ onep analyze ./recommendation-engine --mode strategy

🔬 Code Analyzer: 扫描 247 个文件，发现 38 个策略密集文件...
🧠 Strategy Architect: 深度分析完成，发现 15 个策略优化方向：

  [1] [推荐策略] 全局热度排序忽略用户画像 — ProductRanker.java:45 — 影响: 高
  [2] [LLM策略] Prompt 模板缺少负例样本 — chain.py:120 — 影响: 中
  [3] [缓存策略] 全量刷新而非增量失效 — cache.py:30 — 影响: 高
  ...12 more (type /list to see all)

💬 You: 展开说说第 3 个缓存策略的发现

🧠 Strategy Architect: cache.py 中的 CacheManager 使用全量刷新策略...
  当前行为: 每 5 分钟从 DB 加载全部 200 万条数据重建缓存
  核心问题: 实际变化率 < 2%，98% 的加载是冗余的
  建议方向: 基于 binlog 的增量失效 + 惰性加载
  预估收益: 缓存刷新 CPU 开销减少 90%，内存峰值降 60%

💬 You: 这个方向可以，出个标准版 plan

🧠 + 📐: 协同生成中...
  [3] plans/cache-incremental-invalidation-plan.md ✓
  状态: pending_review

💬 You: /exit
🧠 Strategy Architect: 工作台已保存。恢复: onep strategy resume my-analysis
```

## Plan 结构

### 标准版 Plan

| 章节 | 内容 |
|------|------|
| 基本信息 | 文件位置、策略类型、影响评估、版本 |
| 问题描述 | 当前策略的行为、场景和缺陷 |
| 优化方向 | 建议的新策略方向 |
| 实现思路 | 关键技术方案和步骤 |
| 风险评估 | 实施风险、回滚方案 |
| 参考方案 | 业界类似实践或参考资料 |

### 完整版 Plan

标准版全部内容 + 以下附加章节：

| 附加章节 | 内容 |
|----------|------|
| 伪代码/架构变更 | 变更后的架构草图或关键伪代码 |
| 数据对比 | 优化前后的量化对比预估 |
| 优先级与依赖 | 该 Plan 的优先级排序理由，与其他 Plan 的依赖关系 |

完整版通过 `/expand <n>` 命令触发，仅在标准版经人工审核通过后生成。

## 工作台数据模型

### StrategyItem

| 字段 | 类型 | 说明 |
|------|------|------|
| id | str | 唯一标识 |
| title | str | 优化方向标题 |
| status | ItemStatus | pending / discussing / plan_drafted / plan_reviewed / discarded |
| tags | list[str] | 策略类型标签 |
| file_location | str | 主文件位置 |
| summary | str | Layer 2 发现的问题摘要 |
| impact | str | 影响评估 (high/medium/low) |
| discussion_summary | str | Layer 3 对话摘要 |
| plan_path | str\|None | Plan 文件路径 |
| plan_version | str | none / standard / full |
| created_at | str | 创建时间 |
| updated_at | str | 更新时间 |

### DialogueTurn

| 字段 | 类型 | 说明 |
|------|------|------|
| id | str | 唯一标识 |
| item_id | str\|None | 当前讨论的方向 (None 表示全局对话) |
| role | str | user / agent / system |
| content | str | 对话内容 |
| slash_command | str\|None | 如果本条是 / 命令触发 |
| created_at | str | 时间戳 |

### 磁盘布局

```
~/.onep/projects/<project-name>/.onep/
├── state.yaml                  # 现有流水线状态
├── checkpoints/                # 现有 LangGraph checkpoint
├── strategy/
│   ├── workbench.yaml          # 工作台元数据 + 所有 StrategyItem
│   ├── dialogue.jsonl          # 对话历史 (追加写入)
│   └── plans/                  # 优化 Plan 文件
│       ├── 001-*.md
│       └── 002-*.md
```

### 持久化策略

- 对话历史项目级持久化到 `~/.onep/projects/<name>/.onep/strategy/`
- 可随时通过 `onep strategy resume <name>` 恢复上次对话
- 退出对话模式或使用 `/save` 时自动保存工作台状态
- 对话历史以 JSONL 格式追加写入，支持流式持久化

## 代码变更范围

### 新增文件

```
onep/agents/strategy_architect.py    # 策略架构师 Agent
onep/cli/analyze.py                  # onep analyze 命令
onep/cli/strategy.py                 # onep strategy resume/status/export
onep/orchestrator/brownfield.py      # Brownfield 模式流水线
onep/strategy/__init__.py
onep/strategy/scanner.py             # Layer 1: 文件扫描调度 + 并行化
onep/strategy/analyzer.py            # Layer 2: 策略深度分析
onep/strategy/workbench.py           # Layer 3: 工作台管理 + 对话引擎
onep/strategy/planner.py             # Plan 生成 (标准版/完整版)
onep/strategy/persistence.py         # 工作台持久化
onep/strategy/models.py              # StrategyItem / DialogueTurn 等数据模型
```

### 修改文件

```
onep/persistence/models.py           # 新增 StrategyItem / DialogueTurn / ItemStatus
onep/persistence/database.py         # 新增对话历史表
onep/orchestrator/crew.py            # 增加 brownfield 模式路由
```
