import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router";
import {
  Activity,
  BookOpen,
  Command,
  FolderKanban,
  FileText,
  Home,
  Moon,
  Plus,
  Search,
  Settings,
  Sun,
  Wifi,
  WifiOff,
} from "lucide-react";
import { useStudioHealth } from "../queries";
import { useUIStore } from "../store";
import { cn } from "../lib/utils";
import { Button, DiagnosticsProvider, Hint, Modal } from "./ui";
import { ProductComposer } from "./product-composer";

const nav = [
  { to: "/", label: "首页", icon: Home, end: true },
  { to: "/projects", label: "项目", icon: FolderKanban },
  { to: "/runs", label: "运行", icon: Activity },
  { to: "/knowledge", label: "知识", icon: BookOpen },
  { to: "/articles", label: "文章", icon: FileText },
];

export function AppShell({ children }: { children: ReactNode }) {
  const openComposer = useUIStore((state) => state.openComposer);
  const theme = useUIStore((state) => state.theme);
  const setTheme = useUIStore((state) => state.setTheme);
  const health = useStudioHealth();
  const connection = health.isError ? "offline" : "connected";
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
        openComposer();
      }
    };
    addEventListener("keydown", shortcut);
    return () => removeEventListener("keydown", shortcut);
  }, [openComposer]);

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
        { label: "开始一次交付", icon: Plus, run: () => openComposer() },
        {
          label: "切换主题",
          icon: theme === "dark" ? Sun : Moon,
          run: () => setTheme(theme === "dark" ? "light" : "dark"),
        },
        { label: "打开设置", icon: Settings, run: () => navigate("/settings") },
      ].filter((item) => item.label.includes(query.trim())),
    [navigate, openComposer, query, setTheme, theme],
  );

  return (
    <DiagnosticsProvider>
      <div className="shell">
        <header className="studio-header">
          <div className="studio-header-inner">
            <Link className="studio-wordmark" to="/" aria-label="OnePTeam 首页">
              <span className="orbit-logomark" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span>
                <strong>OnePTeam</strong>
                <small>产品 · 交付 · 知识</small>
              </span>
            </Link>
            <nav className="studio-nav" aria-label="全局导航">
              {nav.map(({ to, label, end }) => (
                <NavLink key={to} to={to} end={end}>
                  {label}
                </NavLink>
              ))}
            </nav>
            <div className="studio-actions">
              <button
                className="command-trigger"
                onClick={() => setCommands(true)}
                aria-label="打开命令面板"
              >
                <Search size={15} />
                <span>跳转或搜索</span>
                <kbd>⌘K</kbd>
              </button>
              <Hint text={connectionLabel}>
                <div
                  className={cn(
                    "connection",
                    ready && "ready",
                    health.isError && "offline",
                  )}
                  role="status"
                  aria-label={connectionLabel}
                >
                  {ready ? <Wifi size={14} /> : <WifiOff size={14} />}
                  <span>{connectionLabel}</span>
                </div>
              </Hint>
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
              <Hint text="设置">
                <Link
                  className="header-settings"
                  to="/settings"
                  aria-label="打开设置"
                >
                  <Settings size={17} />
                </Link>
              </Hint>
            </div>
          </div>
        </header>

        <div className="shell-main">
          <main key={location.pathname} className="page-enter">
            {children}
          </main>
        </div>

        <nav className="mobile-nav" aria-label="移动端导航">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
          <button onClick={() => openComposer()} aria-label="开始一次交付">
            <Plus size={20} />
            <span>新任务</span>
          </button>
        </nav>

        <ProductComposer />
        <Modal
          open={commands}
          onOpenChange={setCommands}
          title="去哪里，或做什么？"
          detail="快速跳转、开始交付或调整工作空间。"
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
    </DiagnosticsProvider>
  );
}
