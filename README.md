# OnePTeam

由多个 AI Agent 组成的全栈软件开发团队。用户只需用自然语言描述需求，系统自动编排产品经理、UI/UX 设计师、架构师、研发工程师、测试工程师和 DevOps 工程师协同工作，完成从产品定义到部署发布的全链路交付。

## 架构

```
🖥️  交互层 (CLI)      — Click + Rich，终端命令与进度展示
🧭  编排层 (CrewAI)    — Agent 团队编排，阶段流转控制
🕸️  子流程层 (LangGraph) — 代码审查回路、测试失败重试
🧰  工具层             — 文件/Git/Shell/Docker 安全封装
💾  持久化层           — SQLite 元数据 + Git 仓库 + 状态文件
```

## 快速开始

### 安装

```bash
pip install -e .
```

### 配置

首次运行会自动创建配置文件 `~/.onep/config.yaml`，按需填入 API 密钥：

```yaml
llm:
  default_model: deepseek/deepseek-chat
  default_provider: deepseek
  complex_model: openai/gpt-5.5
  complex_provider: openai
  models:
    deepseek:
      api_key: "sk-your-key"
      api_base: https://api.deepseek.com/v1
    openai:
      api_key: "sk-your-key"
      api_base: https://api.openai.com/v1
```

### 使用

```bash
# 创建一个新项目
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

## Agent 团队

| 角色 | 模型 | 职责 |
|------|------|------|
| 📋 产品经理 | GPT 5.5 | 需求分析 → 用户故事 → 功能规格 → PRD |
| 🎨 UI/UX 设计师 | GPT 5.5 | 页面布局 → 交互流程 → 组件选型 → 视觉规范 |
| 📐 架构师 | GPT 5.5 | 系统架构 → 数据模型 → API 契约 → 技术选型 |
| 💻 研发工程师 | DeepSeek V4 | 后端 API + 前端页面 + Docker 配置 |
| 🧪 测试工程师 | DeepSeek V4 | 单元测试 + 集成测试 + 测试报告 |
| 🚀 DevOps 工程师 | DeepSeek V4 | Docker 部署 + 健康检查 + 部署日志 |

## 流水线

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

## 技术栈

- **编排框架**: CrewAI + LangGraph
- **CLI**: Click + Rich
- **持久化**: SQLite + Git (GitPython) + YAML
- **LLM 适配**: LiteLLM (DeepSeek + OpenAI)
- **目标产物**: FastAPI + React (TypeScript) + Docker Compose

## 项目结构

```
onep/
├── main.py                    # CLI 入口
├── config.py                  # 全局配置 (~/.onep/config.yaml)
├── cli/                       # 命令行模块 (可插拔)
│   ├── create.py              # onep create / run
│   ├── status.py              # onep status / pause / resume / approve / reject
│   └── show.py                # onep show (prd|design|architecture|report|log)
├── orchestrator/              # CrewAI 编排层
│   ├── crew.py                # Crew 工厂
│   ├── greenfield.py          # Greenfield 6 阶段流水线
│   └── runner.py              # 流水线执行引擎
├── agents/                    # Agent 定义
│   ├── registry.py            # Agent 注册表 (装饰器模式)
│   ├── pm.py, designer.py, architect.py
│   ├── developer.py, tester.py, devops.py
├── subflows/                  # LangGraph 子流程
│   ├── code_review.py         # 代码审查回路
│   └── test_retry.py          # 测试失败重试回路
├── tools/                     # 工具层
│   ├── filesystem.py, git.py, shell.py
│   ├── docker.py, lint.py
├── persistence/               # 持久化层
│   ├── database.py, state.py, models.py
└── llm/                       # LLM 适配层
    ├── router.py, adapters.py
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 运行 CLI
python -m onep.main --help
```

## License

MIT
