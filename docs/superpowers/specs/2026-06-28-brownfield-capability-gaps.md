# Brownfield 能力对齐 Claude Code

## 差距 1：代码修改精度 ✅

EditTool 已实现。对齐 Claude Code Edit 行为：

- `old_string` + `new_string` 精确替换
- `replace_all: bool` 控制单次/全部替换
- 非唯一时报错提示"加更多上下文"
- 不影响 FileWriteTool（新建文件仍用它）

## 差距 2：问题发现质量

### 2a：Scanner 读完整文件内容

当前 Scanner 只传文件路径列表给 LLM。改为传完整内容：

```python
# 旧: 只发路径
prompt = SCAN_PROMPT.format(file_list="\n".join(paths))

# 新: 发送完整内容
prompt = SCAN_PROMPT.format(
    files="\n".join(f"{path}\n```\n{content}\n```" for path, content in batch)
)
```

单个 batch 超出 token 限制时自动拆分。

### 2b：文件分析缓存

缓存文件：`workspace/scan_cache.jsonl`

```jsonl
{"file":"src/cache.py","hash":"a1b2c3","is_strategy":true,"reason":"包含LRU淘汰策略"}
{"file":"src/utils.py","hash":"d4e5f6","is_strategy":false,"reason":"纯工具函数"}
```

首次扫描：每个文件读完整内容 → LLM 分类 → 写缓存。再次扫描：hash 匹配 → 复用缓存。

### 2c：Layer 1B Re-check

Scanner（宽松）和 Analyzer（深度）之间加一层快筛：

```
for each strategy_file:
    prompt = "以下文件是否有值得优化的策略逻辑？回答 keep/drop + 理由"
    → LLM 快速判断（用 default_model，低成本）
    keep → 进入 Layer 2
    drop → 丢弃，原因写入 scan_cache
```

## 差距 3：项目上下文

### 3a：自动生成

首次 `onep analyze` 完成后，生成 `workspace/project_context.md`：

```markdown
# Project Context: <name>

## Tech Stack
- Python 3.12 + FastAPI
- ...

## Directory Structure
- backend/ — API
- tests/ — pytest

## Code Conventions
- async/await
- Pydantic v2

## Key Patterns
- Repository pattern
```

### 3b：手动补充

如源码根目录存在 `CLAUDE.md` 或 `ONEP.md`，内容合并入上下文。

### 3c：注入点

| 入口 | 注入时机 |
|------|---------|
| Layer 1 Scanner | 每个 batch 的 system prompt 附加项目上下文 |
| Layer 1B Re-check | 同上 |
| Layer 2 Analyzer | system prompt 开头注入 |
| Workbench 对话 | 每条消息的 context 注入 |
| `/plan` `/expand` | prompt 注入 |
| `/execute` | Agent system prompt 注入 |
| `/rescan` | 复用 Layer 1+2 |
| `onep optimize` 每轮 | 自动注入所有子阶段 |

### 实现方式

通过一个 `load_project_context(workspace: Path) -> str` 函数，所有 LLM 调用点统一调用。

## 实现分阶段

| 阶段 | 内容 |
|------|------|
| 1 | Scanner 改为读完整文件内容 + 缓存 |
| 2 | Layer 1B Re-check |
| 3 | 项目上下文自动生成 + 注入 |
