import {
  createContext,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
  useContext,
  useState,
} from "react";
import { Dialog, Tooltip } from "radix-ui";
import { AlertTriangle, ChevronRight, RotateCw, X } from "lucide-react";
import { useRouteError } from "react-router";
import { cn, statusLabel, summarize } from "../lib/utils";

export function Button({
  className,
  variant = "secondary",
  size = "md",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "icon";
}) {
  return (
    <button
      className={cn("button", `button-${variant}`, `button-${size}`, className)}
      {...props}
    />
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return <section className={cn("card", className)} {...props} />;
}

export function Badge({
  value,
  children,
}: {
  value: string;
  children?: ReactNode;
}) {
  return (
    <span className={cn("badge", `badge-${value || "unknown"}`)}>
      <i />
      {children || statusLabel[value] || value || "未知"}
    </span>
  );
}

export function Empty({
  icon,
  title,
  detail,
  action,
}: {
  icon?: ReactNode;
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-orbit" aria-hidden="true">
        <i />
        <i />
        <div className="empty-icon">{icon}</div>
      </div>
      <b>{title}</b>
      {detail && <p>{detail}</p>}
      {action}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} />;
}

export function LoadFailure({
  title = "数据加载失败",
  detail = "服务暂时没有返回有效数据，请稍后重试。",
  onRetry,
}: {
  title?: string;
  detail?: string;
  onRetry: () => void;
}) {
  return (
    <div role="alert">
      <Empty
        icon={<AlertTriangle />}
        title={title}
        detail={detail}
        action={
          <Button onClick={onRetry}>
            <RotateCw size={14} />
            重试
          </Button>
        }
      />
    </div>
  );
}

export function PageTitle({
  eyebrow,
  title,
  detail,
  actions,
}: {
  eyebrow: string;
  title: string;
  detail?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-title">
      <div>
        <span>{eyebrow}</span>
        <h1>{title}</h1>
        {detail && <p>{detail}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function SectionTitle({
  eyebrow,
  title,
  meta,
  action,
}: {
  eyebrow?: string;
  title: string;
  meta?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        {eyebrow && <span>{eyebrow}</span>}
        <h2>{title}</h2>
      </div>
      <div className="section-meta">
        {meta}
        {action}
      </div>
    </div>
  );
}

export function JsonInspector({
  value,
  label = "查看原始数据",
}: {
  value: unknown;
  label?: string;
}) {
  const openDiagnostic = useContext(DiagnosticContext);
  if (openDiagnostic)
    return (
      <button
        type="button"
        className="raw-data-trigger"
        onClick={() => openDiagnostic({ label, value })}
      >
        <ChevronRight size={13} />
        {label}
      </button>
    );
  return (
    <details className="raw-data">
      <summary>
        <ChevronRight size={14} />
        {label}
      </summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}

type DiagnosticPayload = { label: string; value: unknown };
const DiagnosticContext = createContext<
  ((payload: DiagnosticPayload) => void) | null
>(null);

export function DiagnosticsProvider({ children }: { children: ReactNode }) {
  const [diagnostic, setDiagnostic] = useState<DiagnosticPayload | null>(null);
  return (
    <DiagnosticContext.Provider value={setDiagnostic}>
      {children}
      <Modal
        open={!!diagnostic}
        onOpenChange={(open) => !open && setDiagnostic(null)}
        title={diagnostic?.label || "技术详情"}
        detail="完整运行证据仅在需要诊断时展示。"
        side
        wide
      >
        <pre className="diagnostic-code">
          {JSON.stringify(diagnostic?.value, null, 2)}
        </pre>
      </Modal>
    </DiagnosticContext.Provider>
  );
}

export function RecordRow({
  title,
  detail,
  meta,
  status,
}: {
  title: string;
  detail?: unknown;
  meta?: ReactNode;
  status?: string;
}) {
  return (
    <div className="record-row">
      {status && <Badge value={status} />}
      <div>
        <b>{title}</b>
        {detail !== undefined && <p>{summarize(detail)}</p>}
      </div>
      {meta && <aside>{meta}</aside>}
    </div>
  );
}

export function Hint({
  text,
  children,
}: {
  text: string;
  children: ReactNode;
}) {
  return (
    <Tooltip.Provider delayDuration={350}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content className="tooltip" sideOffset={8}>
            {text}
            <Tooltip.Arrow className="tooltip-arrow" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export function Modal({
  open,
  onOpenChange,
  title,
  detail,
  children,
  footer,
  wide = false,
  side = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  detail?: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  side?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content
          className={cn(
            "dialog-content",
            wide && "dialog-wide",
            side && "dialog-side",
          )}
        >
          <header>
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              {detail && <Dialog.Description>{detail}</Dialog.Description>}
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="关闭">
                <X size={18} />
              </Button>
            </Dialog.Close>
          </header>
          <div className="dialog-body">{children}</div>
          {footer && <footer>{footer}</footer>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function RouteError() {
  const error = useRouteError();
  return (
    <main className="route-error">
      <AlertTriangle size={28} />
      <h1>页面暂时无法显示</h1>
      <p>{error instanceof Error ? error.message : "发生了未知错误。"}</p>
      <Button onClick={() => location.assign("#/")}>返回控制台</Button>
    </main>
  );
}
