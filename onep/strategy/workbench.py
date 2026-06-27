"""Layer 3: Interactive dialogue workbench with slash command support."""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from onep.strategy.models import (
    WorkbenchState, StrategyItem, DialogueTurn, ItemStatus, PlanVersion,
)
from onep.strategy.persistence import save_workbench, append_dialogue
from onep.strategy.planner import generate_standard_plan, generate_full_plan

console = Console()

SLASH_COMMANDS = {
    "list": "list", "focus": "focus", "search": "search",
    "plan": "plan", "expand": "expand", "compare": "compare",
    "merge": "merge", "discard": "discard", "save": "save",
    "status": "status", "read": "read", "ls": "ls",
    "help": "help", "exit": "exit",
}

HELP_TEXT = """\
[bold]可用命令:[/bold]
  [bold]/list[/bold]                查看所有优化方向
  [bold]/focus[/bold] <n>           切换到第 n 个方向进行讨论
  [bold]/search[/bold] <keyword>    按关键词搜索方向
  [bold]/plan[/bold] <n>            为第 n 个方向生成标准版优化 Plan
  [bold]/expand[/bold] <n>          为标准版 Plan 生成完整实施方案
  [bold]/compare[/bold] <n> <m>     对比两个方向
  [bold]/merge[/bold] <n> <m>       合并两个方向为一个
  [bold]/discard[/bold] <n>         忽略/丢弃某个方向
  [bold]/read[/bold] <file>         读取源码树中的文件
  [bold]/ls[/bold] <dir>            列出源码树目录内容
  [bold]/status[/bold]              查看当前分析进度
  [bold]/save[/bold]                保存工作台
  [bold]/help[/bold]                显示此帮助
  [bold]/exit[/bold]                保存并退出"""


def parse_input(user_input: str) -> tuple[str | None, str | None, str]:
    text = user_input.strip()
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0][1:]
        args = parts[1] if len(parts) > 1 else ""
        if cmd in SLASH_COMMANDS:
            return cmd, args, ""
        return None, None, text
    return None, None, text


def handle_slash_command(
    cmd: str, args: str, wb: WorkbenchState, workspace: Path, llm_adapter=None,
) -> WorkbenchState:
    if cmd == "list":
        _cmd_list(wb)
    elif cmd == "focus":
        item_id = _resolve_item_id(args, wb)
        if item_id:
            wb.current_item_id = item_id
            item = _find_item(wb, item_id)
            console.print(f"[green]已切换到: [{item_id}] {item.title if item else '?'}[/green]")
        else:
            console.print(f"[red]未找到方向: {args}[/red]")
    elif cmd == "search":
        keyword = args.lower()
        found = [i for i in wb.items if keyword in i.title.lower() or keyword in " ".join(i.tags).lower()]
        if found:
            console.print(f"[bold]搜索 '{keyword}' 结果:[/bold]")
            for item in found:
                _print_item(item)
        else:
            console.print(f"[yellow]未找到匹配 '{keyword}' 的方向[/yellow]")
    elif cmd == "plan":
        _cmd_generate_plan(args, wb, workspace, llm_adapter, version="standard")
    elif cmd == "expand":
        _cmd_generate_plan(args, wb, workspace, llm_adapter, version="full")
    elif cmd == "compare":
        ids = args.split()
        if len(ids) >= 2:
            _cmd_compare(ids[0], ids[1], wb)
        else:
            console.print("[red]用法: /compare <n> <m>[/red]")
    elif cmd == "merge":
        ids = args.split()
        if len(ids) >= 2:
            _cmd_merge(ids[0], ids[1], wb)
        else:
            console.print("[red]用法: /merge <n> <m>[/red]")
    elif cmd == "discard":
        item_id = _resolve_item_id(args, wb)
        if item_id:
            item = _find_item(wb, item_id)
            if item:
                item.discard()
                console.print(f"[yellow]已忽略: [{item_id}] {item.title}[/yellow]")
    elif cmd == "read":
        _cmd_read(args, wb)
    elif cmd == "ls":
        _cmd_ls(args, wb)
    elif cmd == "save":
        save_workbench(workspace, wb)
        console.print("[green]工作台已保存。[/green]")
    elif cmd == "status":
        _cmd_status(wb)
    elif cmd == "help":
        console.print(HELP_TEXT)
    elif cmd == "exit":
        save_workbench(workspace, wb)
        console.print(f"[green]工作台已保存。恢复会话: onep strategy resume {wb.project_name}[/green]")
    return wb


def _resolve_item_id(args: str, wb: WorkbenchState) -> str | None:
    args = args.strip()
    if args.startswith("si-"):
        return args if _find_item(wb, args) else None
    if args.isdigit():
        idx = int(args) - 1
        active = [i for i in wb.items if i.status != ItemStatus.DISCARDED]
        if 0 <= idx < len(active):
            return active[idx].id
    return None


def _find_item(wb: WorkbenchState, item_id: str) -> StrategyItem | None:
    for item in wb.items:
        if item.id == item_id:
            return item
    return None


def _print_item(item: StrategyItem) -> None:
    impact_color = {"high": "red", "medium": "yellow", "low": "dim"}
    color = impact_color.get(item.impact, "white")
    status_icon = {ItemStatus.PENDING: "○", ItemStatus.DISCUSSING: "●",
                   ItemStatus.PLAN_DRAFTED: "📋", ItemStatus.PLAN_REVIEWED: "✅",
                   ItemStatus.DISCARDED: "✗"}
    icon = status_icon.get(item.status, "?")
    tags_str = ", ".join(item.tags) if item.tags else ""
    console.print(
        f"  [{icon}] [{item.id}] [{color}]{item.title}[/{color}] — {item.file_location}"
        + (f" [{tags_str}]" if tags_str else "")
    )


def _cmd_list(wb: WorkbenchState) -> None:
    active = [i for i in wb.items if i.status != ItemStatus.DISCARDED]
    discarded = [i for i in wb.items if i.status == ItemStatus.DISCARDED]
    console.print(f"\n[bold]优化方向 ({len(active)} 个活跃)[/bold]")
    for item in active:
        _print_item(item)
    if discarded:
        console.print(f"\n[dim]已忽略 ({len(discarded)} 个)[/dim]")


def _cmd_status(wb: WorkbenchState) -> None:
    total = len(wb.items)
    active = len([i for i in wb.items if i.status != ItemStatus.DISCARDED])
    drafted = len([i for i in wb.items if i.status == ItemStatus.PLAN_DRAFTED])
    reviewed = len([i for i in wb.items if i.status == ItemStatus.PLAN_REVIEWED])
    discarded = len([i for i in wb.items if i.status == ItemStatus.DISCARDED])
    table = Table(title=f"分析进度: {wb.project_name}")
    table.add_column("指标", style="cyan")
    table.add_column("数量")
    for label, val in [("源路径", wb.source_path), ("优化点总数", str(total)),
                       ("活跃中", str(active)), ("Plan 已生成", str(drafted)),
                       ("Plan 已审核", str(reviewed)), ("已忽略", str(discarded)),
                       ("扫描完成", "✓" if wb.scan_complete else "○"),
                       ("分析完成", "✓" if wb.analysis_complete else "○")]:
        table.add_row(label, val)
    console.print(table)


def _cmd_read(args: str, wb: WorkbenchState) -> None:
    """Read a file from the source tree and display it."""
    file_path = args.strip() or (wb.current_item.file_location.split(":")[0] if wb.current_item else "")
    if not file_path:
        console.print("[red]用法: /read <file> 或先用 /focus 选择一个方向[/red]")
        return
    full = Path(wb.source_path) / file_path
    if not full.exists():
        console.print(f"[red]文件不存在: {file_path}[/red]")
        return
    content = full.read_text()
    max_lines = 200
    lines = content.split("\n")
    if len(lines) > max_lines:
        content = "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    console.print(Panel(content, title=f"📄 {file_path}", border_style="dim"))


def _cmd_ls(args: str, wb: WorkbenchState) -> None:
    """List files in the source tree directory."""
    dir_path = args.strip() or "."
    full = (Path(wb.source_path) / dir_path).resolve()
    if not str(full).startswith(str(Path(wb.source_path).resolve())):
        console.print(f"[red]路径超出源码范围: {dir_path}[/red]")
        return
    if not full.exists():
        console.print(f"[red]目录不存在: {dir_path}[/red]")
        return
    items = sorted(full.iterdir(), key=lambda p: (not p.is_dir(), p.name))
    lines = []
    for p in items:
        suffix = "/" if p.is_dir() else ""
        lines.append(f"  {'📁' if p.is_dir() else '📄'} {p.name}{suffix}")
    console.print(f"[bold]{dir_path}/[/bold]\n" + "\n".join(lines[:50]))
    if len(items) > 50:
        console.print(f"[dim]... 还有 {len(items) - 50} 个条目[/dim]")


def _cmd_generate_plan(args: str, wb: WorkbenchState, workspace: Path, llm_adapter=None, version: str = "standard") -> None:
    item_id = _resolve_item_id(args, wb)
    if not item_id:
        console.print(f"[red]未找到方向: {args}[/red]")
        return
    item = _find_item(wb, item_id)
    if not item:
        return
    if version == "standard":
        active = [i for i in wb.items if i.status != ItemStatus.DISCARDED]
        plan_index = active.index(item) + 1 if item in active else 1
        path = generate_standard_plan(item, workspace, llm_adapter, plan_index)
        if path:
            console.print(f"[green][{item.id}] Plan 已生成: {path}[/green]")
        else:
            console.print("[yellow]Plan 生成需要 LLM 连接（当前不可用）。[/yellow]")
    elif version == "full":
        if not item.plan_path or item.plan_version != PlanVersion.STANDARD:
            console.print("[red]请先生成标准版 Plan，审核通过后再生成完整版。[/red]")
            return
        plan_content = Path(item.plan_path).read_text() if item.plan_path else ""
        path = generate_full_plan(item, plan_content, workspace, llm_adapter)
        if path:
            console.print(f"[green][{item.id}] 完整版 Plan 已生成: {path}[/green]")
        else:
            console.print("[yellow]完整版 Plan 生成需要 LLM 连接（当前不可用）。[/yellow]")


def _cmd_compare(id_a: str, id_b: str, wb: WorkbenchState) -> None:
    item_a = _find_item(wb, _resolve_item_id(id_a, wb) or id_a)
    item_b = _find_item(wb, _resolve_item_id(id_b, wb) or id_b)
    if not item_a or not item_b:
        console.print("[red]至少一个方向未找到。[/red]")
        return
    table = Table(title=f"对比: [{item_a.id}] vs [{item_b.id}]")
    table.add_column("维度"); table.add_column(item_a.title); table.add_column(item_b.title)
    for label, va, vb in [("影响", item_a.impact, item_b.impact),
                          ("标签", ", ".join(item_a.tags), ", ".join(item_b.tags)),
                          ("文件", item_a.file_location, item_b.file_location),
                          ("摘要", item_a.summary[:100], item_b.summary[:100])]:
        table.add_row(label, va, vb)
    console.print(table)


def _cmd_merge(id_a: str, id_b: str, wb: WorkbenchState) -> None:
    item_a = _find_item(wb, _resolve_item_id(id_a, wb) or id_a)
    item_b = _find_item(wb, _resolve_item_id(id_b, wb) or id_b)
    if not item_a or not item_b:
        console.print("[red]至少一个方向未找到。[/red]")
        return
    merged = StrategyItem(
        title=f"{item_a.title} + {item_b.title}",
        file_location=f"{item_a.file_location}, {item_b.file_location}",
        summary=f"[合并自 {item_a.id}] {item_a.summary}\n[合并自 {item_b.id}] {item_b.summary}",
        impact=_higher_impact(item_a.impact, item_b.impact),
        tags=list(set(item_a.tags + item_b.tags)),
    )
    item_a.discard(); item_b.discard()
    wb.items.append(merged)
    console.print(f"[green]已合并为: [{merged.id}] {merged.title}[/green]")


def _higher_impact(a: str, b: str) -> str:
    order = {"high": 3, "medium": 2, "low": 1}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _read_item_file(source_path: str, file_location: str) -> str | None:
    """Read the file referenced by a StrategyItem, truncated to a reasonable size."""
    file_part = file_location.split(":")[0]
    file_path = Path(source_path) / file_part
    if not file_path.exists():
        return None
    try:
        content = file_path.read_text()
        if len(content) > 3000:
            content = content[:3000] + "\n... (文件过长，已截断)"
        return content
    except Exception:
        return None


def _build_dialogue_context(wb: WorkbenchState, user_message: str) -> str:
    current_item = _find_item(wb, wb.current_item_id) if wb.current_item_id else None
    context_parts = [f"项目: {wb.project_name}", f"源路径: {wb.source_path}"]
    if current_item:
        context_parts.append(f"\n当前讨论方向: [{current_item.id}] {current_item.title}")
        context_parts.append(f"文件位置: {current_item.file_location}")
        context_parts.append(f"问题摘要: {current_item.summary}")
        context_parts.append(f"标签: {', '.join(current_item.tags)}")
        context_parts.append(f"影响: {current_item.impact}")

        file_content = _read_item_file(wb.source_path, current_item.file_location)
        if file_content:
            context_parts.append(f"\n相关代码:\n```\n{file_content}\n```")
    recent = wb.dialogue[-10:] if wb.dialogue else []
    if recent:
        context_parts.append("\n最近对话:")
        for turn in recent:
            role_label = "用户" if turn.role == "user" else "Agent"
            context_parts.append(f"[{role_label}]: {turn.content[:200]}")
    context_parts.append(f"\n用户消息: {user_message}")
    return "\n".join(context_parts)


def run_dialogue_loop(workspace: Path, wb: WorkbenchState, llm_adapter=None) -> WorkbenchState:
    console.print(Panel.fit(
        f"[bold green]策略分析对话模式[/bold green]\n"
        f"项目: {wb.project_name}\n发现 {len(wb.items)} 个优化方向\n\n"
        f"输入自然语言与Agent讨论，或使用 / 命令操作",
        title="Strategy Workbench",
    ))
    console.print(HELP_TEXT + "\n")

    while True:
        try:
            user_input = console.input("[bold cyan]💬 You:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            save_workbench(workspace, wb)
            console.print("\n[green]工作台已保存。[/green]")
            break
        if not user_input:
            continue
        cmd, args, message = parse_input(user_input)
        if cmd:
            if cmd == "exit":
                handle_slash_command(cmd, args, wb, workspace, llm_adapter)
                break
            else:
                handle_slash_command(cmd, args, wb, workspace, llm_adapter)
            append_dialogue(workspace, DialogueTurn(
                role="user", content=message or f"/{cmd} {args}".strip(),
                item_id=wb.current_item_id,
                slash_command=f"/{cmd} {args}".strip() if cmd else None,
            ))
        else:
            append_dialogue(workspace, DialogueTurn(
                role="user", content=message, item_id=wb.current_item_id,
            ))
            if llm_adapter is not None:
                context = _build_dialogue_context(wb, message)
                console.print(f"\n[bold green]🧠 Strategy Architect:[/bold green] ", end="")
                response_parts: list[str] = []
                try:
                    for token in llm_adapter.invoke_stream(
                        system_prompt="你是一位策略架构师，正在与用户讨论代码策略优化。根据用户的问题提供有帮助的深入分析。回答要具体，引用代码中的实际策略逻辑。用中文回复。",
                        user_prompt=context, stage_name="strategy_architect",
                    ):
                        console.print(token, end="")
                        response_parts.append(token)
                except Exception:
                    pass
                console.print("\n")
                response = "".join(response_parts)
                if response:
                    append_dialogue(workspace, DialogueTurn(
                        role="agent", content=response, item_id=wb.current_item_id,
                    ))
            else:
                console.print("\n[yellow]LLM 不可用（请配置 API 密钥）。Slash 命令仍然可用。[/yellow]\n")
    return wb
