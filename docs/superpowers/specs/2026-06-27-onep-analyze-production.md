# onep analyze 生产级改进

## 优先级

A（可靠性） > C（结果共享） > B（成本可控）

## A：可靠性 — Pipeline State Machine

### 状态机

```
INIT → SCANNING → SCAN_DONE → ANALYZING → ANALYZE_DONE → DIALOGUE_ACTIVE → COMPLETED
  ↓                     ↓              ↓
FAILED ←────────────── FAILED ←────── FAILED
  ↓                     ↓              ↓
SCANNING (resume)   SCANNING (resume)  ANALYZING (resume)
```

状态持久化到 `~/.onep/projects/<name>/pipeline_state.yaml`，每次状态变更立即 `flush()`。

### CLI

```bash
onep analyze ./repo --name myproj              # 首次运行
onep analyze ./repo --name myproj --resume     # 从断点继续
onep analyze ./repo --name myproj --from-layer 2  # 重跑分析层
onep analyze ./repo --no-dialogue              # 只跑 Layer 1+2
```

### Layer 1 容错

逐批持久化到 `scan_results.jsonl`，checkpoint 记录已完成和失败的 batch：

```yaml
scan_state:
  total_batches: 10
  completed: [0, 1, 2, 4, 5, 6, 7, 8, 9]
  failed: [{batch: 3, error: "rate limit exhausted", files: 50, retries: 3}]
```

- 瞬态错误：重试 3 次，指数退避
- 重试耗尽：跳过该 batch，标记文件为 `is_strategy=True, reason="LLM不可用，标记待人工审查"`
- 后续 batch 照常继续
- `--resume` 只重跑 failed batch

### Layer 2 容错

- 流式解析：每遇到完整一行 JSON 立即写入 `analysis_items.jsonl`
- 解析失败不影响已产出 items
- 零产出 → 标记 FAILED，建议 `--from-layer 2` 重跑
- `--resume` 时如已有 ANALYZE_DONE 状态，跳过 Layer 2

### Layer 3 容错

保持现状。对话已有 `save_workbench` + `save_plan` 持久化。

---

## C：结果共享 — 导出 Markdown 报告

### CLI

```bash
onep analyze ./repo --export report.md         # 分析 + 导出
onep export myproject                          # 对已有项目单独导出
onep export myproject --format json            # JSON 格式
```

### 报告格式

单文件自包含 Markdown，可提交到 git：

```markdown
# 策略分析报告: myproject

## 概览
- 源路径: /path/to/repo
- 分析时间: 2026-06-27 14:30 UTC
- 扫描文件: 847 个
- 策略密集文件: 23 个
- 发现优化方向: 5 个

## 优化方向

### 1. [high] 缓存策略缺少淘汰机制
- 文件: src/cache.py:30
- 标签: 缓存策略, 性能
- 摘要: 当前使用无限增长的内存缓存...

### 2. [high] LLM Prompt 重复注入
- 文件: src/llm/prompts.py:45
...

## 附录
- 扫描统计
- 分析参数
- 成本摘要
```

### Git 工作流

```bash
onep analyze ./repo --export analysis.md
git add analysis.md
git commit -m "add strategy analysis report"
git push
```

---

## B：成本可控 — 预算估算 + 硬上限

### 模型定价配置

`~/.onep/config.yaml` 新增 `pricing` 字段（$/1M tokens）：

```yaml
llm:
  pricing:
    deepseek/deepseek-chat:        {input: 0.14, output: 0.28}
    deepseek/deepseek-v4-pro:      {input: 0.50, output: 1.00}
    openai/gpt-4o:                 {input: 2.50, output: 10.00}
    openai/gpt-4.1:                {input: 2.00, output: 8.00}
```

内置默认价格，用户可改。

### 估算公式

```
scanner_cost = num_batches × (
    batch_input_tokens × default_model.input_price +
    batch_estimated_output_tokens × default_model.output_price
)

analyzer_cost = strategy_files × (
    estimated_input_per_file × complex_model.input_price +
    estimated_output_per_file × complex_model.output_price
) × avg_tool_rounds
```

- input tokens ≈ 字符数 ÷ 3
- scanner output tokens ≈ 文件数 × 35
- 误差通常在 ±30% 以内

### CLI

```bash
onep analyze ./repo --max-cost 5.00

# 开始前：
#   Files to scan: 847
#   Estimated cost: ~$2.80 (scanner: $0.80, analyzer: ~$2.00)
#   Budget: $5.00
#   Continue? [Y/n]

# 执行中每步显示花费和剩余预算
# 超预算自动停止，已有结果不丢
```

---

## 实现分阶段

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| 1 | Pipeline state machine + checkpoint | A |
| 2 | Layer 1 逐批持久化 + retry | A |
| 3 | Layer 2 流式解析 + 零产出检测 | A |
| 4 | Markdown 导出 | C |
| 5 | 成本估算 + 硬上限 | B |
