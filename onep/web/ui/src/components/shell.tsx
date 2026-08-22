import { ReactNode, useEffect, useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router";
import {
  Activity,
  BookOpen,
  Bot,
  ChevronLeft,
  Command,
  FolderKanban,
  LayoutDashboard,
  Menu,
  Moon,
  Plus,
  Search,
  Settings,
  Sun,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useHealth, useLiveEvents } from "../queries";
import { useUIStore } from "../store";
import { cn } from "../lib/utils";
import { Button, Hint, Modal } from "./ui";
import { NewTaskSheet } from "./new-task";

const nav = [
  { to: "/", label: "控制台", icon: LayoutDashboard, end: true },
  { to: "/projects", label: "项目", icon: FolderKanban },
  { to: "/tasks", label: "任务", icon: Activity },
  { to: "/knowledge", label: "知识", icon: BookOpen },
];

export function AppShell({ children }: { children: ReactNode }) {
  const collapsed = useUIStore((state) => state.sidebarCollapsed);
  const toggle = useUIStore((state) => state.toggleSidebar);
  const setComposer = useUIStore((state) => state.setComposerOpen);
  const theme = useUIStore((state) => state.theme);
  const setTheme = useUIStore((state) => state.setTheme);
  const health = useHealth();
  const connection = useLiveEvents();
  const [commands, setCommands] = useState(false);
  const [query, setQuery] = useState("");
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommands((value) => !value);
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") {
        event.preventDefault();
        setComposer(true);
      }
    };
    addEventListener("keydown", shortcut);
    return () => removeEventListener("keydown", shortcut);
  }, [setComposer]);

  const ready = health.data?.status === "ready" && connection === "connected";
  const connectionLabel = health.isError
    ? "服务离线"
    : ready
      ? "系统就绪"
      : connection === "offline"
        ? "网络离线"
        : health.data?.worker.ready === false
          ? "Worker 未就绪"
          : "正在重连";
  const commandsList = useMemo(
    () =>
      [
        ...nav.map((item) => ({
          label: `前往${item.label}`,
          icon: item.icon,
          run: () => navigate(item.to),
        })),
        { label: "新建任务", icon: Plus, run: () => setComposer(true) },
        {
          label: "切换主题",
          icon: theme === "dark" ? Sun : Moon,
          run: () => setTheme(theme === "dark" ? "light" : "dark"),
        },
        { label: "打开设置", icon: Settings, run: () => navigate("/settings") },
      ].filter((item) => item.label.includes(query.trim())),
    [navigate, query, setComposer, setTheme, theme],
  );

  return (
    <div className={cn("shell", collapsed && "shell-collapsed")}>
      <aside className="sidebar">
        <div className="brand-mark">
          <span>
            <Bot size={20} />
          </span>
          <div>
            <b>OnePTeam</b>
            <small>Agent Operations</small>
          </div>
        </div>
        <nav>
          {nav.map(({ to, label, icon: Icon, end }) => (
            <Hint key={to} text={label}>
              <NavLink
                to={to}
                end={end}
                className={({ isActive }) => cn(isActive && "active")}
              >
                <Icon size={18} />
                <span>{label}</span>
              </NavLink>
            </Hint>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <NavLink to="/settings">
            <Settings size={18} />
            <span>设置</span>
          </NavLink>
          <Button
            size="icon"
            variant="ghost"
            onClick={toggle}
            aria-label="折叠侧栏"
          >
            {collapsed ? <Menu size={17} /> : <ChevronLeft size={17} />}
          </Button>
        </div>
      </aside>
      <div className="shell-main">
        <header className="topbar">
          <button className="command-trigger" onClick={() => setCommands(true)}>
            <Search size={16} />
            <span>搜索项目或执行命令</span>
            <kbd>⌘ K</kbd>
          </button>
          <div className="topbar-actions">
            <div
              className={cn(
                "connection",
                ready && "ready",
                health.isError && "offline",
              )}
            >
              {ready ? <Wifi size={14} /> : <WifiOff size={14} />}
              <span>{connectionLabel}</span>
            </div>
            <Hint text="切换主题">
              <Button
                size="icon"
                variant="ghost"
                aria-label="切换主题"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              >
                {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
              </Button>
            </Hint>
            <Button variant="primary" onClick={() => setComposer(true)}>
              <Plus size={16} />
              新建任务
            </Button>
          </div>
        </header>
        <main key={location.pathname} className="page-enter">
          {children}
        </main>
      </div>
      <NewTaskSheet />
      <Modal
        open={commands}
        onOpenChange={setCommands}
        title="命令面板"
        detail="快速跳转、创建任务或调整界面。"
      >
        <div className="command-panel">
          <label>
            <Command size={17} />
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入命令…"
            />
          </label>
          <div>
            {commandsList.map(({ label, icon: Icon, run }) => (
              <button
                key={label}
                onClick={() => {
                  run();
                  setCommands(false);
                  setQuery("");
                }}
              >
                <Icon size={17} />
                <span>{label}</span>
                <kbd>↵</kbd>
              </button>
            ))}
          </div>
        </div>
      </Modal>
    </div>
  );
}
