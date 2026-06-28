# OnePTeam

由多个 AI Agent 组成的全栈软件开发团队。支持两种模式：

- **Greenfield**：用自然语言描述需求，Agent 团队自动完成从 PRD 到部署的全链路交付
- **Brownfield**：分析存量代码库，发现优化方向，生成 Plan，执行代码改进，持续迭代

## 架构

```
交互层 (CLI)      — Click + Rich，终端命令与进度展示
编排层            — Greenfield 6 阶段流水线 + Brownfield 分析优化循环
Agent 层          — 8 个 Agent，装饰器注册，工具可插拔
工具层            — 10 个 CrewAI 兼容工具，自建流式 Tool Calling 引擎
策略分析引擎       — Scanner(缓存+Re-check) → Analyzer(流式) → Workbench(对话+执行)
记忆系统           — SQLite 向量+FTS5 混合检索，跨会话上下文
持久化层           — SQLite 元数据 + YAML 状态 + JSONL 日志
LLM 适配层         — LiteLLM 多模型路由 + 流式 Tool Calling + 成本追踪
```

## 快速开始

### 安装

```bash
conda create -n onep python=3.13 -y
conda activate onep
pip install -e .
pip install -e ".[dev]"
```

### 配置

#### API 密钥

在项目根目录创建 `.env` 文件：

```bash
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-your-openai-key
OPENAI_API_BASE=https://api.openai.com/v1
```

#### 模型配置

`~/.onep/config.yaml`（首次运行自动创建）：

```yaml
llm:
  default_model: deepseek/deepseek-chat
  default_provider: deepseek
  complex_model: openai/gpt-4o
  complex_provider: openai
  pricing:
    deepseek/deepseek-chat:   {input: 0.14, output: 0.28}
    openai/gpt-4o:            {input: 2.50, output: 10.00}
pipeline:
  auto_approve: false
  max_retries: 3
```

## 使用

### Greenfield — 新建项目

```bash
onep create "做一个支持登录的记事本应用"
onep run myapp
onep status
onep show prd myapp
onep pause myapp / onep resume myapp / onep approve myapp
```

### Brownfield — 存量代码分析+优化

```bash
# 分析代码库
onep analyze ./repo --max-cost 5.00

# 在 workbench 中交互
/focus 3        # 选中优化方向
/plan 3         # 生成优化 Plan
/execute 3      # 执行代码改动+测试
/rescan         # 重新扫描

# 全自动优化（可下班跑）
onep optimize ./repo --max-rounds 5 --auto-approve low,medium \
  --test-command "pytest tests/unit -q" \
  --integration-test-command "pytest -q" \
  --max-cost 20.00

# 导出报告
onep export myproject
onep export myproject --format json

# 恢复会话
onep strategy resume myproject
```

### 管理命令

```bash
onep status              # 查看所有项目
onep delete myproject    # 删除项目（名称匹配所有同名项目）
onep delete abc123       # ID 前缀精确匹配
onep memory status       # 记忆库统计
onep memory search "缓存"
onep memory import myproject
```

## Agent 团队

| Agent | 模型 | 职责 | 工具 |
|-------|------|------|------|
| 产品经理 | 复杂模型 | 需求分析 → PRD | — |
| UI/UX 设计师 | 复杂模型 | 设计文档 | — |
| 架构师 | 复杂模型 | 系统架构 + 技术方案 | file_read/write/list, grep, edit, memory |
| 研发工程师 | 默认模型 | 代码实现 | file_read/write/list, edit, grep, shell, lint, memory |
| 测试工程师 | 默认模型 | 测试编写+运行 | file_read/write, grep, shell, memory |
| DevOps 工程师 | 默认模型 | Docker 部署 | file_read/write, shell, docker, memory |
| 代码分析师 | 默认模型 | 文件扫描分类 | file_read/list, memory |
| 策略架构师 | 复杂模型 | 深度分析+Plan+对话 | file_read/list, grep, memory |

## Brownfield 流水线

```
源码
  → Layer 1: 全量扫描（读文件完整内容 → LLM 分类 → hash 缓存）
  → Layer 1B: Re-check（过滤误报，drop 明显不是策略的文件）
  → Layer 2: 深度分析（策略架构师 + Tool Calling + 流式输出）
  → Layer 3: 交互式对话
      /list    — 查看优化方向
      /focus   — 选中讨论
      /plan    — 生成优化 Plan
      /execute — 执行代码改动+测试（LLM 自主循环）
      /rescan  — 重新扫描
      /export  — 导出报告
```

### Workbench 命令

| 命令 | 功能 |
|------|------|
| `/list` | 查看所有优化方向 |
| `/focus <n>` | 切换到第 n 个方向 |
| `/search <kw>` | 搜索方向 |
| `/plan <n>` | 生成标准版 Plan |
| `/expand <n>` | 生成完整版 Plan |
| `/approve <n>` | 审核 Plan |
| `/execute <n>` | 执行开发+测试（LLM 自主：grep→read→edit→lint→test→fix） |
| `/compare <n> <m>` | 对比两个方向 |
| `/merge <n> <m>` | 合并两个方向 |
| `/discard <n>` | 丢弃方向 |
| `/read <file>` | 读取源码文件 |
| `/ls <dir>` | 列出目录 |
| `/rescan` | 重新扫描源码 |
| `/export <file>` | 导出当前分析报告 |
| `/status` | 查看进度 |
| `/help` | 帮助 |
| `/exit` | 保存退出 |

## `onep optimize` — 全自动优化

```bash
onep optimize ./repo --max-rounds 5 --auto-approve low,medium --max-cost 20.00
```

安全闸门：

| 闸门 | 机制 |
|------|------|
| 影响级别 | `high` 必须人审，`low/medium` 自动执行 |
| 分支隔离 | 每个 Plan 使用独立 branch + worktree |
| 启动条件 | 源仓库必须位于 named branch 且 tracked/untracked 均干净 |
| 开发循环 | 同组并行开发，单一 LLM Developer 根据反馈最多修复 3 次 |
| 测试 | 使用真实进程退出码，不采信 LLM 对测试结果的描述 |
| 评审 | 独立、只读的结构化 code reviewer |
| 提交 | 测试与评审均通过后只创建一个 commit |
| 回滚 | 失败 Plan 恢复 tracked 文件，仅删除该 Plan 新建的 untracked 文件 |
| 集成 | 开发完成后按依赖、影响、发现顺序串行集成并运行整体测试 |
| 成本 | 按稳定 call ID 记录实际 token；预算模式缺少模型价格时拒绝启动 |

完整运行记录保存在
`~/.onep/projects/<name>/workspace/optimize/runs/<run-id>/`，包含所有成功、
失败和跳过 Plan、每轮测试/评审、最终 diff、失败原因及报告。

## 工具系统

| 工具 | 功能 |
|------|------|
| `FileReadTool` | 读取文件 |
| `FileWriteTool` | 写入文件 |
| `EditTool` | 精确字符串替换（对齐 Claude Code Edit 行为） |
| `FileListTool` | 列出目录 |
| `GrepTool` | 跨文件搜索 |
| `ShellTool` | 执行 shell 命令（破坏性命令自动拦截） |
| `LintTool` | Ruff 代码检查 |
| `GitTool` | Git 操作 |
| `DockerTool` | Docker Compose |
| `MemoryTool` | 记忆搜索+写入 |

## 记忆系统

跨会话持久化记忆，支持向量语义 + FTS5 关键词混合检索：

```bash
onep memory status
onep memory search "缓存策略"
onep memory import myproject
onep memory clean
```

## 技术栈

- CLI: Click + Rich
- LLM: LiteLLM (DeepSeek + OpenAI)，自建流式 Tool Calling 引擎
- Agent: CrewAI Agent 定义 + 自研执行循环
- 持久化: SQLite + YAML + JSONL
- 向量检索: SQLite FTS5 + cosine similarity + MMR + temporal decay

## 项目结构

```
onep/
├── main.py
├── config.py
├── cli/
│   ├── analyze.py            # onep analyze
│   ├── optimize_cmd.py       # onep optimize
│   ├── export_cmd.py         # onep export
│   ├── create.py             # onep create / run
│   ├── status.py             # onep status / pause / resume / delete
│   ├── show.py               # onep show
│   ├── strategy_cmd.py       # onep strategy
│   └── memory_cmd.py         # onep memory
├── orchestrator/
│   ├── greenfield.py, brownfield.py
│   ├── runner.py, crew.py
├── agents/
│   ├── registry.py
│   ├── pm.py, designer.py, architect.py
│   ├── developer.py, tester.py, devops.py
│   ├── analyzer.py, strategy_architect.py
├── strategy/
│   ├── scanner.py, scan_cache.py, analyzer.py
│   ├── workbench.py, planner.py, persistence.py
│   ├── models.py, pipeline_state.py, retry.py
│   ├── optimize_engine.py, project_context.py
├── tools/
│   ├── filesystem.py, edit.py, grep.py
│   ├── git.py, shell.py, docker.py, lint.py
│   └── memory.py
├── memory/
│   ├── schema.py, embeddings.py, manager.py
│   ├── search.py, query_expansion.py
│   ├── hooks.py, context.py
├── llm/
│   ├── adapters.py, router.py, cost.py
└── persistence/
    ├── database.py, models.py, state.py
```

## 开发

```bash
conda activate onep
pip install -e ".[dev]"
pytest tests/ -v          # 175 tests
python -m onep.main --help
```

## License

MIT
