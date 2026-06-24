# OnePTeam — 多 Agent 软件开发团队设计规格

## 项目概述

OnePTeam 是一个由多个 AI Agent 组成的全栈软件开发团队。用户通过 CLI 输入需求或提供已有代码库，系统自动编排产品经理、UI/UX 设计师、架构师、研发工程师、测试工程师、DevOps 工程师、代码分析师等角色，完成从产品定义到部署发布的全链路工作。

## 技术选型

| 维度 | 选择 | 说明 |
|------|------|------|
| Agent 框架 | CrewAI + LangGraph 分层 | CrewAI 顶层编排，LangGraph 复杂子流程 |
| 交互界面 | CLI (Click + Rich) | MVP 阶段 CLI，后续扩展 Web UI |
| 后端语言 | Python | 与 CrewAI/LangGraph 运行时一致 |
| 目标软件栈 | Python 后端 + React Web + React Native | 前后端分离，Web + Mobile 共享设计语言 |
| 部署方式 | Docker Compose 本地部署 | MVP 阶段本地容器化 |
| 持久化 | Git 仓库 + SQLite + state.yaml | Git 为主数据源，SQLite 存元数据 |
| 文档语言 | 中文 | 沟通和业务文档用中文 |
| 代码语言 | 英文 | 标识符、commit message 用英文 |
| LLM 默认 | DeepSeek V4 | 性价比高，代码能力强 |
| LLM 复杂任务 | GPT 5.5 | 架构/需求/设计等需深度推理 |

## 系统架构

五层架构，每层职责清晰：

```
🖥️  交互层 (CLI)      — Click + Rich，终端命令与进度展示
🧭  编排层 (CrewAI)    — Crew/Agent/Task 定义，阶段流转
🕸️  子流程层 (LangGraph) — 代码审查回路、测试失败重试、人工审核
🧰  工具层             — 文件/Git/Shell/Docker 操作封装
💾  持久化层           — Git 仓库 + SQLite + LangGraph Checkpoint
```

关键原则：
- Agent 不直接操作底层，所有文件/Git/Docker 操作通过工具层接口
- CrewAI 决定 WHAT（阶段顺序和交付物），LangGraph 处理 HOW（复杂分支和回退）
- 持久化层对上层透明，编排层通过统一接口读写状态

## Agent 角色设计

共 7 个角色，按流水线顺序排列：

| 顺序 | 角色 | 模型 | 输入 | 输出 | 核心工具 |
|------|------|------|------|------|----------|
| 1 | 📋 产品经理 | GPT 5.5 | 用户需求 | PRD.md | 需求模板引擎，PRD 导出 |
| 2 | 🎨 UI/UX 设计师 | GPT 5.5 | PRD + 设计需求 | DESIGN.md | 布局生成，组件选型，交互流程 |
| 3 | 📐 架构师 | GPT 5.5 | PRD + 设计稿 | ARCHITECTURE.md, DB Schema, API Spec | 架构图生成 (Mermaid), Schema 设计 |
| 4 | 💻 研发工程师 | DeepSeek V4 | 架构设计 + API Spec | 源代码, Dockerfile, docker-compose.yml | 文件读写, Shell, Git, Linter |
| 5 | 🧪 测试工程师 | DeepSeek V4 | 源代码 + 架构设计 | TEST_REPORT.md, 测试代码 | pytest/vitest, 覆盖率, E2E |
| 6 | 🚀 DevOps 工程师 | DeepSeek V4 | 源码 + Dockerfile | DEPLOY_LOG.md, 运行中的服务 | Docker CLI, Compose, 健康检查 |
| * | 🔬 代码分析师 | GPT 5.5 | Git URL/本地目录 | OPTIMIZATION_REPORT.md | AST 解析, 复杂度分析, 依赖图 |

> 代码分析师仅在 Brownfield 模式下激活，不参与 Greenfield 流水线。

### 模型分配策略

- **GPT 5.5**：产品经理、UI/UX 设计师、架构师、代码分析师 — 需要深度推理和创造性判断
- **DeepSeek V4**：研发工程师、测试工程师、DevOps 工程师 — 任务量大，性价比优先

## Pipeline 工作流

### 双入口设计

| 模式 | CLI 命令 | 起点 | 适用场景 |
|------|----------|------|----------|
| Greenfield | `onep create "需求"` | 用户需求描述 | 从零构建新项目 |
| Brownfield | `onep analyze <url/path>` | 已有代码库 | 分析、讨论、优化已有项目 |

### Greenfield 模式 (6 阶段)

```
用户需求输入
  → Stage 1: 📋 产品经理 (PRD.md) [✋审核]
  → Stage 2: 🎨 UI/UX 设计师 (DESIGN.md)
  → Stage 3: 📐 架构师 (ARCHITECTURE.md) [✋审核]
  → Stage 4: 💻 研发工程师 (源代码) [🔀代码审查回路]
  → Stage 5: 🧪 测试工程师 (测试报告) [🔀失败重试回路]
  → Stage 6: 🚀 DevOps 工程师 (部署)
  → ✅ 交付
```

### Brownfield 模式 (5 阶段)

```
Git URL / 本地目录
  → Phase 1: 📥 代码摄取 (Clone, 索引, 结构识别)
  → Phase 2: 🔬 多维度分析 (质量, 架构, 性能, 安全, 测试)
  → Phase 3: 💡 优化报告 (OPTIMIZATION_REPORT.md) [✋审核]
  → Phase 4: 💬 多轮讨论 (CLI 交互式，逐项确认)
  → Phase 5: 🛠️ 执行优化 (复用 Greenfield Stage 4-6)
  → ✅ 交付
```

### LangGraph 子流程

**🔀 代码审查回路**：研发 Agent 生成代码 → 自我审查 (lint + 逻辑检查) → 发现问题则修正 → 通过后 commit

**🔁 测试失败恢复回路**：运行测试 → 失败则分析原因 → 自动修复 / 标记需人工介入 → 重跑 (最多 3 轮) → 全部通过后进入部署

### 人工介入点（灵活模式）

- **默认审核门禁**：PRD 完成后、架构设计完成后（Greenfield）/ 优化报告完成后 + 多轮讨论确认（Brownfield）
- **随时暂停**：任何阶段用户可通过 `onep pause` 暂停，查看产物或修改后 `onep resume`
- **测试失败阈值**：修复 3 轮仍失败时暂停，避免无限循环
- **用户可随时介入**修改任何阶段的输出

## CLI 命令设计

### 命令体系

```
# 新建项目
onep create "需求描述"
onep create --from-file requirements.md

# 分析已有项目
onep analyze <git-url|local-path>
onep analyze <path> --focus performance,security

# 流程控制
onep status          # 查看流水线进度
onep pause           # 暂停流水线
onep resume          # 恢复流水线
onep approve         # 确认审核
onep reject "理由"   # 驳回并附带反馈

# 产物查看
onep show prd|design|architecture|report|log

# 项目管理
onep list                 # 列出所有项目
onep open <project-name>  # 打开已有项目
onep config               # 查看/修改配置
```

### 设计原则
- CLI 命令采用插件式注册，`cli/` 目录下每个文件一个命令模块，后续扩展只需新增文件
- 终端使用 Rich 库提供彩色进度面板和格式化输出

## 项目结构与数据模型

### 磁盘目录

```
~/.onep/
├── config.yaml              # 全局配置 (LLM keys, 默认设置)
├── meta.db                  # SQLite 元数据库
└── projects/
    └── <project-name>/
        ├── workspace/       # Git 仓库 (项目产物)
        │   ├── docs/        # PRD.md, DESIGN.md, ARCHITECTURE.md
        │   ├── backend/     # Python 后端源码
        │   ├── frontend/    # React 前端源码
        │   ├── docker-compose.yml
        │   └── Dockerfile
        └── .onep/
            ├── state.yaml       # 流水线运行时状态
            └── checkpoints/     # LangGraph checkpoint
```

### 元数据表 (SQLite)

- **projects**: 项目基本信息 (name, mode, status, current_stage, workspace_path)
- **stage_runs**: 阶段执行记录 (agent_name, model_used, token_count, output_files, error)
- **approvals**: 审核记录 (decision, feedback)
- **conversations**: Agent 对话摘要 (role, content)

### 状态一致性

- Git 是主数据源，state 是缓存。恢复时以 Git 实际状态为准修正元数据
- 事务性写入：先 Git commit 成功，再更新 state.yaml 和 SQLite

## 错误处理与恢复

### 三级错误分类

| 级别 | 条件 | 策略 | 恢复 |
|------|------|------|------|
| 🔴 致命 | API 密钥无效、磁盘满、Git 仓库损坏 | 立即停止，提示用户修复 | 从最近 checkpoint 恢复 |
| 🟡 可重试 | LLM 超时、API 限流、依赖安装失败 | 指数退避重试 (最多 3 次) | 3 次失败降级为致命 |
| 🟢 可降级 | 次要工具不可用、可选分析跳过 | 跳过步骤，记录警告 | 流水线继续，报告中标记 |

### Checkpoint 恢复

- 每个 Stage 完成后自动创建 checkpoint (LangGraph 原生)
- 子流程中每轮迭代也可创建中间 checkpoint
- `onep resume` 时自动检测已完成阶段，从断点继续

## 系统代码结构 (onep 包)

```
onep/
├── main.py                    # CLI 入口
├── config.py                  # 全局配置加载
├── cli/                       # CLI 命令 (可插拔)
│   ├── create.py, analyze.py, status.py, show.py, config.py, approve.py
├── orchestrator/              # CrewAI 编排层
│   ├── crew.py                # Crew 工厂 + 模式路由
│   ├── greenfield.py          # Greenfield 流水线
│   └── brownfield.py          # Brownfield 流水线
├── agents/                    # Agent 定义
│   ├── registry.py            # Agent 注册表
│   ├── pm.py, designer.py, architect.py, developer.py, tester.py, devops.py, analyzer.py
├── subflows/                  # LangGraph 子流程
│   ├── code_review.py         # 代码审查回路
│   └── test_retry.py          # 测试失败重试回路
├── tools/                     # 工具层
│   ├── filesystem.py, git.py, shell.py, docker.py, code_analyzer.py, test_runner.py
├── persistence/               # 持久化层
│   ├── database.py, state.py, models.py
└── llm/                       # LLM 适配层
    ├── router.py              # 模型路由 (任务→模型映射)
    ├── deepseek.py, openai.py
```

## MVP 范围

- 目标：用极简 Web 应用需求走通 Greenfield 全链路，验证编排架构
- 示例需求：一个支持登录的记事本应用
- 测试 Agent 和 DevOps Agent 先做精简版（基础冒烟测试 + 单容器部署）
- Brownfield 模式在 Greenfield 链路验证通过后启动

## 后续迭代

- Web UI 管理台（在稳定 API 层之上构建）
- 云端部署适配（DeployTarget 接口抽象 → 云/K8s 实现）
- 多技术栈扩展（通过 Agent 注册表 + 工具集注入）
- 更多 Brownfield 分析维度（性能 profiling、安全 CVE 扫描）
