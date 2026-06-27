# OnePTeam

由多个 AI Agent 组成的全栈软件开发团队。用户只需用自然语言描述需求，系统自动编排产品经理、UI/UX 设计师、架构师、研发工程师、测试工程师和 DevOps 工程师协同工作，完成从产品定义到部署发布的全链路交付。

同时内置**策略分析引擎**，可对存量代码库进行多层级深度分析，发现架构优化点并生成改进方案。

## 架构

```
🖥️  交互层 (CLI)      — Click + Rich，终端命令与进度展示
🧭  编排层 (CrewAI)    — Greenfield 全链路开发 + Brownfield 策略分析
🕸️  子流程层 (LangGraph) — 代码审查回路、测试失败重试
🧰  工具层             — 文件/Git/Shell/Docker 安全封装
💾  持久化层           — SQLite 元数据 + Git 仓库 + YAML 状态文件
🧠  LLM 适配层         — LiteLLM 多模型路由 (DeepSeek + OpenAI)
```

## 快速开始

### 安装

```bash
# 创建 conda 环境并安装
conda create -n onep python=3.13 -y
conda activate onep
pip install -e .

# 安装开发依赖（含测试框架）
pip install -e ".[dev]"
```

### 配置

#### API 密钥（.env 文件，推荐）

在项目根目录创建 `.env` 文件（已加入 `.gitignore`，不会被提交到 Git）：

```bash
cp .env.example .env
```

编辑 `.env` 填入真实的 API 密钥：

```bash
# DeepSeek
DEEPSEEK_API_KEY=sk-your-deepseek-key
DEEPSEEK_API_BASE=https://api.deepseek.com/v1

# OpenAI
OPENAI_API_KEY=sk-your-openai-key
OPENAI_API_BASE=https://api.openai.com/v1
```

环境变量优先级高于配置文件，推荐使用 `.env` 管理密钥。

#### 模型配置（~/.onep/config.yaml）

首次运行会自动创建 `~/.onep/config.yaml`。模型路由规则：

| 任务类型 | 使用模型 | 涵盖的 Agent |
|---------|---------|------------|
| 复杂任务 | `complex_model` | 产品经理、UI/UX 设计师、架构师、策略架构师 |
| 常规任务 | `default_model` | 研发工程师、测试工程师、DevOps 工程师、代码分析师 |

```yaml
llm:
  # 常规任务（代码生成、测试、部署、扫描）
  default_model: deepseek/deepseek-chat
  default_provider: deepseek

  # 复杂任务（需求分析、设计、架构、策略分析）
  complex_model: openai/gpt-4o
  complex_provider: openai

  # 可选：为特定 Provider 配置额外模型
  models: {}

pipeline:
  auto_approve: false     # 是否跳过人工审核点
  max_retries: 3           # 测试/部署失败最大重试次数
  test_timeout: 300        # 测试超时（秒）
```

> **模型名格式**: `provider/model-name`，如 `openai/gpt-4o`、`openai/gpt-4.1`、`deepseek/deepseek-chat`、`deepseek/deepseek-v4-pro`。

> **安全提示：** 不要在 `config.yaml` 中写入 API 密钥，也不要把 `.env` 文件提交到 Git。密钥统一通过环境变量管理。

### 使用

```bash
# Greenfield 模式：从零创建新项目
onep create "做一个支持登录的记事本应用"

# 运行开发流水线
onep run myapp

# 查看流水线状态
onep status

# 查看产物
onep show prd myapp
onep show architecture myapp

# 流程控制
onep pause myapp
onep resume myapp
onep approve myapp
```

### Brownfield 模式：存量代码分析

```bash
# 分析本地代码库的策略优化点
onep analyze /path/to/existing/project

# 指定项目名称
onep analyze ./my-repo -n my-analysis

# 从 Git 仓库 URL 直接分析
onep analyze https://github.com/user/repo.git -n repo-analysis

# 恢复之前的分析会话（进入交互式对话）
onep strategy resume my-analysis

# 查看分析进度
onep strategy status my-analysis

# 导出分析报告
onep strategy export my-analysis          # Markdown 格式
onep strategy export my-analysis -f json  # JSON 格式
```

## Agent 团队

| 角色 | 模型 | 职责 |
|------|------|------|
| 📋 产品经理 | 复杂模型 | 需求分析 → 用户故事 → 功能规格 → PRD |
| 🎨 UI/UX 设计师 | 复杂模型 | 页面布局 → 交互流程 → 组件选型 → 视觉规范 |
| 📐 架构师 | 复杂模型 | 系统架构 → 数据模型 → API 契约 → 技术选型 |
| 💻 研发工程师 | 默认模型 | 后端 API + 前端页面 + Docker 配置 |
| 🧪 测试工程师 | 默认模型 | 单元测试 + 集成测试 + 测试报告 |
| 🚀 DevOps 工程师 | 默认模型 | Docker 部署 + 健康检查 + 部署日志 |
| 🔍 代码分析师 | 默认模型 | 文件扫描 → 策略密集度识别 |
| 🏗️ 策略架构师 | 复杂模型 | 深度分析 → 优化方向识别 → Plan 生成 |

## 流水线

### Greenfield（新建项目）

```
用户需求
  → Stage 1: 📋 产品经理 (PRD.md) [审核点]
  → Stage 2: 🎨 UI/UX 设计师 (DESIGN.md)
  → Stage 3: 📐 架构师 (ARCHITECTURE.md) [审核点]
  → Stage 4: 💻 研发工程师 (源代码) [代码审查回路]
  → Stage 5: 🧪 测试工程师 (测试报告) [失败重试回路]
  → Stage 6: 🚀 DevOps 工程师 (部署)
  → ✅ 交付
```

### Brownfield（存量代码分析）

```
代码库
  → Layer 1: 🔍 快速扫描 — 代码分析师 Agent 遍历文件，识别策略密集文件
  → Layer 2: 🏗️ 深度分析 — 策略架构师 Agent 分析优化方向，生成 StrategyItem 列表
  → Layer 3: 💬 交互式对话 — 11 个 slash 命令驱动的对话工作台，逐项审查与 Plan 生成
  → 📋 导出报告 (Markdown / JSON)
```

## 技术栈

- **编排框架**: CrewAI + LangGraph
- **CLI**: Click + Rich
- **持久化**: SQLite + Git (GitPython) + YAML + JSONL
- **LLM 适配**: LiteLLM (DeepSeek + OpenAI)，支持 .env 环境变量注入
- **Agent 注册**: 装饰器驱动的可插拔注册表
- **目标产物 (Greenfield)**: FastAPI + React (TypeScript) + Docker Compose
- **策略分析 (Brownfield)**: 3 层管道 (Scanner → Analyzer → Workbench)

## 项目结构

```
onep/
├── main.py                    # CLI 入口
├── config.py                  # 全局配置 (~/.onep/config.yaml)
├── cli/                       # 命令行模块 (可插拔)
│   ├── analyze.py             # onep analyze — Brownfield 策略分析入口
│   ├── create.py              # onep create / run
│   ├── status.py              # onep status / pause / resume / approve / reject
│   ├── show.py                # onep show (prd|design|architecture|report|log)
│   └── strategy_cmd.py        # onep strategy resume / status / export
├── orchestrator/              # CrewAI 编排层
│   ├── crew.py                # Crew 工厂
│   ├── greenfield.py          # Greenfield 6 阶段流水线
│   ├── brownfield.py          # Brownfield 扫描+分析 Prompt 模板
│   └── runner.py              # 流水线执行引擎
├── agents/                    # Agent 定义
│   ├── registry.py            # Agent 注册表 (装饰器模式)
│   ├── pm.py, designer.py, architect.py
│   ├── developer.py, tester.py, devops.py
│   ├── analyzer.py            # 代码分析师（策略扫描）
│   └── strategy_architect.py  # 策略架构师（深度分析）
├── strategy/                  # 策略分析引擎
│   ├── models.py              # 数据模型 (StrategyItem, WorkbenchState, ItemStatus)
│   ├── scanner.py             # Layer 1: 文件遍历、批量扫描、JSONL 解析
│   ├── analyzer.py            # Layer 2: LLM 响应解析 → StrategyItem
│   ├── workbench.py           # Layer 3: 交互式对话工作台 (11 slash 命令)
│   ├── planner.py             # Plan 生成器 (standard / full)
│   └── persistence.py         # YAML (workbench.yaml) + JSONL (dialogue.jsonl)
├── subflows/                  # LangGraph 子流程
│   ├── code_review.py         # 代码审查回路
│   └── test_retry.py          # 测试失败重试回路
├── tools/                     # 工具层
│   ├── filesystem.py, git.py, shell.py
│   ├── docker.py, lint.py
├── persistence/               # 持久化层
│   ├── database.py, state.py, models.py
└── llm/                       # LLM 适配层
    ├── router.py              # 模型路由
    └── adapters.py            # LiteLLM 适配器
```

## 命令速查

| 命令 | 说明 |
|------|------|
| `onep create <需求>` | Greenfield：用自然语言创建新项目 |
| `onep run <项目>` | 运行开发流水线 |
| `onep status` | 查看所有项目流水线进度 |
| `onep pause/resume <项目>` | 暂停/恢复流水线 |
| `onep approve/reject <项目>` | 通过/拒绝当前审核点 |
| `onep show <产物> <项目>` | 查看产物 (prd/design/architecture/report/log) |
| `onep analyze <路径\|URL>` | Brownfield：分析存量代码库 |
| `onep strategy resume <项目>` | 恢复策略分析会话 |
| `onep strategy status <项目>` | 查看策略分析进度 |
| `onep strategy export <项目>` | 导出分析报告 |

## 开发

```bash
# 激活 conda 环境
conda activate onep

# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 运行 CLI
python -m onep.main --help
```

## License

MIT
