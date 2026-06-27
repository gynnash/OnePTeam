# onep optimize — 优化循环设计

## 概述

Brownfield 分析（`onep analyze`）之后，支持对优化方向进行开发实现和测试验证，形成"分析 → Plan → 开发 → 测试 → 再分析"的持续优化循环。

## 产品定位

- `onep analyze` + Workbench `/execute` — **半自动**，人在回路中审核每一步
- `onep optimize` — **全自动+安全闸门**，一行命令跑完，中间不需人工介入

两者共享底层 Optimize Engine。

---

## 共享引擎：Optimize Engine

```
optimize_engine.execute(item, source_path, workspace)
    ├── Step 1: architect_refine
    │   输入: StrategyItem + Plan + 相关源码
    │   Agent: architect + FileReadTool + FileWriteTool
    │   输出: 技术实现方案
    │
    ├── Step 2: developer_implement
    │   输入: 技术方案 + 源码
    │   Agent: developer + FileReadTool+FileWriteTool+ShellTool+LintTool
    │   输出: 代码改动 + lint 检查
    │
    ├── Step 3: tester_verify
    │   输入: 改动文件列表 + 源码
    │   Agent: tester + FileReadTool + ShellTool
    │   输出: {passed: bool, test_output: str}
    │
    └── 返回: {success, files_changed, test_output, error?}
```

每步有流式输出、agent trace、token 统计。

---

## B 模式：`/execute` — Workbench 半自动

在 Layer 3 对话中，已 `/focus 3` 和 `/plan 3` 审核通过后：

```
💬 You: /execute 3

  ═══ Step 1/3: 架构细化 ═══
  Agent: 架构师 | Model: openai/gpt-4o
  tokens: 1200 in + 450 out = 1650 total

  ═══ Step 2/3: 代码实现 ═══
  Agent: 研发工程师 | Tools: file_read, file_write, shell, lint
  调用 file_write(path='src/cache.py')
  调用 shell(command='pytest tests/test_cache.py -q')
  tokens: 3400 in + 890 out = 4290 total

  ═══ Step 3/3: 测试验证 ═══
  Agent: 测试工程师
  ✅ 12 passed, 0 failed

✅ 优化 #3 执行完成
  改动文件: src/cache.py, tests/test_cache.py
  Git: commit a3f2b1c
```

跑完就停，用户可手动 `/analyze` 开启下一轮。

---

## C 模式：`onep optimize` — 全自动+闸门

### CLI

```bash
onep optimize ./repo \
  --max-rounds 5 \
  --auto-approve low,medium \
  --max-cost 20.00
```

### 影响级别标准

| 级别 | 标准 | 示例 |
|------|------|------|
| high | 影响功能正确性、数据安全、API 变更、用户可感知 | 缓存 key 冲突、SQL 注入、LLM 输出崩溃 |
| medium | 影响性能/成本/可维护性，不影响正确性 | token 浪费、缺少重试、代码重复 |
| low | 纯代码质量、风格 | 变量命名、函数拆分、类型标注 |

硬规则：API 签名变更、DB schema 变更一律标 high。

用户在 `/plan` 审核时可手动覆盖 `--impact medium`。

### 流程

```
for round in range(max_rounds):
    items = analyze_layer(source_path)    # Layer 1 + 2
    for item in items:
        if item.impact not in auto_approve:
            skipped.append(item); continue  # 闸门①: 等人审
        if not tracker.can_continue():
            break                            # 闸门②: 预算用完
        plan = generate_plan(item)
        result = optimize_engine.execute(item, source_path, workspace)
        if result.success:
            git.commit(...)                    # 闸门③: 测试通过
        else:
            git.revert(...)                    # 闸门③: 测试失败回滚
    if not any_new_items():
        break

generate_report(skipped, completed, failed, tracker)
```

### 闸门

| 闸门 | 时机 | 检查 |
|------|------|------|
| 影响级别 | Plan 生成后 | high → 跳过，记录到报告 |
| 成本 | 每一步前 | 剩余预算是否够 |
| 测试 | 开发完成后 | pytest 不通过 → git revert |

### 输出

| 输出 | 终端 | 持久化 |
|------|------|--------|
| 每轮进度 | ✓ 打印摘要 | 追加 `workspace/optimize_log.jsonl` |
| 完整报告 | ✓ 打印 | 写入 `workspace/optimize_report.md` |

报告可用 `onep export <name>` 重新导出到项目目录。

---

## 实现分阶段

| 阶段 | 内容 |
|------|------|
| 1 | Optimize Engine（architect_refine + developer_implement + tester_verify） |
| 2 | `/execute` — Workbench 集成 |
| 3 | `onep optimize` — 全自动命令 + 闸门 + 报告 |
